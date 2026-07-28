"""Engine orchestrator — async event loop wiring FeedMux→BiasEngine→Scanner→Manager.

run_wave_engine() is the main entry point, called from bot_paper.py when
VAISRAVANA_ENGINE=wave.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

from wave.models import Tick, TickContext
from wave.feed import FeedMux, refetch_klines, MAX_AGE_S
from wave.bias import read_bias, read_confidence
from wave.scanner import scan
from wave.manager import WaveManager
from wave.risk import ModeGuard, KillSwitch, PairExcluder
from wave.smczones import SMCZoneCache
from wave.structure import ema_update
from wave.db import init_wave_db

log = logging.getLogger(__name__)

# ── Shared state for Telegram commands ────────────────────────────────────
wave_state: dict = {"waves": [], "closed_today": []}
# engine.py's run_wave_engine writes active waves + closed waves here on each
# poll cycle. bot_paper.py's /wave and /surf command handlers read from it.

# Owner /stop flag — set by the wave Telegram listener; the engine loop
# checks it every tick and halts cleanly (cancels the run coroutine).
stop_requested: bool = False


class ContextStore:
    """Holds live TickContext per pair, updated on every tick."""

    def __init__(self, pairs: list[str], tfs: list[str]):
        self._contexts: dict[str, TickContext] = {}
        for p in pairs:
            ctx = TickContext(pair=p)
            ctx.klines = {tf: [] for tf in tfs}
            self._contexts[p] = ctx

    def get(self, pair: str) -> TickContext:
        return self._contexts[pair]

    def update_from_tick(self, tick: Tick) -> TickContext:
        """Update context from a live tick and return it."""
        ctx = self._contexts.get(tick.pair)
        if ctx is None:
            ctx = TickContext(pair=tick.pair)
            self._contexts[tick.pair] = ctx

        ctx.price = tick.price
        ctx.mark = tick.mark or tick.price
        ctx.bid = tick.bid
        ctx.ask = tick.ask
        ctx.last_tick_ts = time.time()

        # Book imbalance
        if tick.bid and tick.ask:
            ctx.book_imbalance = (tick.bid - tick.ask) / (tick.ask + tick.bid + 1e-9) * -100

        return ctx

    def update_kline(self, pair: str, tf: str, kline: dict) -> None:
        """Store a kline update in context."""
        ctx = self._contexts.get(pair)
        if ctx is None:
            return
        if tf not in ctx.klines:
            ctx.klines[tf] = []
        if kline.get("is_final"):
            ctx.klines[tf].append(kline)
            if len(ctx.klines[tf]) > 200:
                ctx.klines[tf] = ctx.klines[tf][-200:]


# ── Async engine ──────────────────────────────────────────────────────────────


async def run_wave_engine(conn, surface, notifier, guard, exchange, kill):
    """Main wave engine async entry point."""
    log.info("Wave Engine starting...")

    # Params
    raw_pairs = os.getenv("VAISRAVANA_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
    from symbols import resolve_symbol
    pairs = [resolve_symbol(p) for p in raw_pairs]
    log.info("Wave Engine pairs=%s (resolved from %s)", pairs, raw_pairs)
    tfs = ["1m", "5m", "15m"]
    ws_url = os.getenv("BINANCE_WS_URL", "wss://fapi.binance.com/ws")
    proxy_url = os.getenv("HTTPS_PROXY", "")

    # Init DB tables
    init_wave_db(conn)

    # State
    ctx_store = ContextStore(pairs, tfs)
    zone_cache = SMCZoneCache()
    manager = WaveManager()
    manager.conn = conn
    excluder = PairExcluder()
    last_tick_time = time.time()
    _diag_n = 0  # diagnostic tick counter

    # ── Paper wallet (fake $10 balance + fees + survival sizing) ──
    from wave.paper_wallet import get_wallet
    wallet = get_wallet()

    # ── Handlers ──────────────────────────────────────────────────────────

    async def on_tick(tick: Tick) -> None:
        pair = tick.pair
        nonlocal last_tick_time
        # Owner /stop — halt cleanly at the next tick.
        if stop_requested or os.path.exists("/data/.wave_stop"):
            log.info("owner /stop (or .wave_stop flag) received — halting wave engine")
            try:
                os.remove("/data/.wave_stop")
            except OSError:
                pass
            raise asyncio.CancelledError("owner /stop")
        last_tick_time = time.time()
        ctx = ctx_store.update_from_tick(tick)
        ctx.ema_15m = ema_update(ctx.ema_15m, tick.price, 20)
        bias = read_bias(pair, tick, ctx)
        signal_age = time.time() - tick.ts if tick.ts else 0
        confidence = read_confidence(bias, ctx, ctx.structure_score, 0.5, signal_age)

        if excluder.is_excluded(pair):
            return

        if not manager.in_cooldown(pair, "BUY"):
            cand = scan(pair, "BUY", "1m", bias, confidence, ctx, zone_cache, adx=20)
            if cand:
                wave = manager.open(cand, bias, confidence, ctx, surface, wallet)
                if wave:
                    # open_fee already charged inside open(); report it
                    open_fee = (wave.notional * wallet.fee_rate) if wallet else 0.0
                    await notify_wave_open(notifier, wave, wallet, open_fee)

        if not manager.in_cooldown(pair, "SELL"):
            cand = scan(pair, "SELL", "1m", bias, confidence, ctx, zone_cache, adx=20)
            if cand:
                wave = manager.open(cand, bias, confidence, ctx, surface, wallet)
                if wave:
                    open_fee = (wave.notional * wallet.fee_rate) if wallet else 0.0
                    await notify_wave_open(notifier, wave, wallet, open_fee)

        for wave in list(manager.waves.values()):
            if wave.pair != pair:
                continue
            manager.on_tick(wave, tick, ctx, bias, confidence, zone_cache)
            action = manager.evaluate_exit(wave, tick, ctx, bias, confidence, zone_cache)
            if action:
                econ = manager.close(wave, action.reason, tick.price, wallet)
                await notify_wave_close(notifier, wave, wallet, econ)
            scale_action = manager.maybe_scale(wave, ctx, bias)
            if scale_action and scale_action.type == "PARTIAL":
                pass

        manager.tick_cooldowns()

        # ── Paper wallet: stop the engine if balance is gone ──
        if wallet is not None and wallet.is_broke:
            log.info("PAPER wallet broke (balance<=%.2f) — engine halting", wallet.stop_at)
            try:
                notifier.send_message(
                    f"💀 **Paper wallet empty** (${wallet.balance:.4f})\n"
                    f"Wave Engine stopping. Top up VAISRAVANA_PAPER_BALANCE or /clean."
                )
            except Exception:
                pass
            raise asyncio.CancelledError("paper wallet broke")

    async def on_kline(tf: str, kline: dict) -> None:
        pair = kline.get("s", "")
        if not pair:
            return
        ctx_store.update_kline(pair, tf, kline)
        if kline.get("is_final") and tf in ("15m", "1h", "5m"):
            klines_list = ctx_store.get(pair).klines.get(tf, [])
            if len(klines_list) >= 11:
                zone_cache.refresh(pair, tf, klines_list)
        # Feed ema_1h from the 1h close so read_bias()'s 40%-weight
        # mtf_ema component is actually live (it was always 0 before).
        if tf == "1h" and kline.get("is_final"):
            ctx = ctx_store.get(pair)
            if ctx is not None:
                ctx.ema_1h = ema_update(ctx.ema_1h, float(kline["close"]), 20)
        # Feed ema_15m from the 15m close — this is the decision-timeframe
        # EMA that read_bias() compares against live price. Without it,
        # ema_15m stays == price (updated only from ticks) and mtf_ema is
        # always ~0, so the bot reads neutral and never trades.
        if tf == "15m" and kline.get("is_final"):
            ctx = ctx_store.get(pair)
            if ctx is not None:
                ctx.ema_15m = ema_update(ctx.ema_15m, float(kline["close"]), 20)

    # ── Feed ──────────────────────────────────────────────────────────────

    feed = FeedMux(
        on_tick=on_tick,
        on_kline=on_kline,
        ws_url=ws_url,
        proxy_url=proxy_url or None,
    )

    # Notify startup
    try:
        await notify_startup(notifier, pairs, surface)
    except Exception:
        log.debug("startup notification failed")

    # WS connection with REST fallback.
    # IMPORTANT: feed.connect() loops on the read socket forever (it only
    # returns on disconnect), so we must NOT await it with a short timeout.
    # Instead we pass on_ready: the moment the initial subscribe succeeds,
    # ws_ok flips True and the REST fallback is skipped. If Binance is truly
    # unreachable, the WS layer logs a warning and retries with backoff; the
    # REST poll loop is started independently as a safety net.
    ws_ok = [False]

    def _mark_ws_ok():
        ws_ok[0] = True

    async def _ws_runner():
        try:
            await feed.connect(pairs, on_ready=_mark_ws_ok)
        except asyncio.CancelledError:
            log.info("FeedMux cancelled")
        except Exception as e:
            log.warning("FeedMux failed (%s)", e)

    ws_task = asyncio.create_task(_ws_runner())
    log.info("WS TASK CREATED — sleeping 10s for live feed to establish")
    await asyncio.sleep(10)
    log.info("SLEEP DONE — ws_ok=%s", ws_ok[0])

    # ALWAYS run the REST poll loop as a parallel safety net (never block on
    # ws_task — feed.connect() loops forever, so awaiting it would starve
    # the REST poll task). Both run concurrently; if WS ever comes up it
    # simply adds live ticks on top of the REST feed.
    rest_task = asyncio.create_task(
        _rest_poll_loop(pairs, on_tick, on_kline, ctx_store, manager, wave_state)
    )
    log.info("REST POLL TASK CREATED (parallel safety net)")
    await asyncio.gather(ws_task, rest_task)
    log.info("WS/REST TASKS DONE")


# ── REST fallback ────────────────────────────────────────────────────────────


async def _rest_poll_loop(pairs, on_tick, on_kline, ctx_store, manager, wave_state):
    """REST polling fallback — fetches prices every 5s when WS unavailable."""
    import functools
    import urllib.request as _ur

    log.info("Starting REST poll loop (5s interval)")
    loop = asyncio.get_event_loop()
    cycles = 0
    while True:
        cycles += 1
        try:
            for pair in pairs:
                url = f"https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol={pair}"
                try:
                    req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    raw = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, functools.partial(_ur.urlopen, req, timeout=8)
                        ), timeout=10
                    )
                    data = json.loads(raw.read().decode())
                    bid = float(data.get("bidPrice", 0))
                    ask = float(data.get("askPrice", 0))
                    # bookTicker has no lastPrice — derive mid from bid/ask.
                    price = (bid + ask) / 2.0 if (bid and ask) else 0.0
                    volume = 0.0
                    if price:
                        tick = Tick(
                            pair=pair, price=price, qty=volume, side="",
                            bid=bid, ask=ask, mark=price,
                            ts=time.time(), source="rest_poll",
                        )
                        await on_tick(tick)
                except Exception as e:
                    log.error("REST poll %s failed: %s", pair, e)

                try:
                    klines = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, functools.partial(refetch_klines, pair, "15m", limit=20)
                        ), timeout=10
                    )
                except asyncio.TimeoutError:
                    klines = []
                    log.debug("REST poll klines timeout for %s", pair)
                for k in klines:
                    k["tf"] = "15m"
                    k["s"] = pair
                    await on_kline("15m", k)

                # 1h context (every 12 cycles ≈ 60s) so ema_1h stays live
                # even on REST-only fallback. Needed by read_bias()'s 40% mtf_ema.
                if cycles % 12 == 0:
                    try:
                        kl1h = await asyncio.wait_for(
                            loop.run_in_executor(
                                None, functools.partial(refetch_klines, pair, "1h", limit=20)
                            ), timeout=10
                        )
                        for k in kl1h:
                            k["tf"] = "1h"
                            k["s"] = pair
                            await on_kline("1h", k)
                    except Exception:
                        pass

            if cycles % 6 == 0:
                log.info("REST poll heartbeat cycle=%d pairs=%d open=%d",
                         cycles, len(pairs), 0)
            # Refresh shared state for Telegram commands
            wave_state["waves"] = list(manager.waves.values())
            wave_state["closed_today"] = list(getattr(manager, "closed_today", []))

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("REST poll loop error: %s", e)

        await asyncio.sleep(5)


# ── Notifications (Telegram) ─────────────────────────────────────────────────


async def notify_startup(notifier, pairs, surface):
    """Send startup notification."""
    try:
        ver = "wave-0.1.0"
        notifier.notify_startup(
            version=ver,
            pairs=pairs,
            decision_tf="1m",
            tfs=["1m", "5m", "15m"],
            cycle_s=0,
            llm_mode="off",
            open_trades=0,
        )
    except Exception as e:
        log.debug("startup card failed: %s", e)


async def notify_wave_open(notifier, wave, wallet=None, open_fee=0.0):
    """Notify on wave open — clean, professional card."""
    try:
        side_icon = "🟢" if wave.side == "BUY" else "🔴"
        lev = getattr(wave, "leverage", 1) or 1
        margin = getattr(wave, "margin", 0.0) or 0.0
        notn = getattr(wave, "notional", 0.0) or 0.0
        tp = getattr(wave, "tp_price", None)
        tp_s = f"{tp:.6f}" if tp else "—"
        bal = wallet.balance if wallet else 0.0
        unreal = getattr(wallet, "unrealized", 0.0) if wallet else 0.0
        used = getattr(wallet, "used", 0.0) if wallet else 0.0
        equity = bal + unreal
        lines = [
            f"🌊 <b>WAVE OPEN</b> {side_icon} {wave.side} {wave.pair}",
            f"<code>  Entry : {wave.entry_price:.6f}</code>",
            f"<code>  SL    : {wave.sl_price:.6f}</code>",
            f"<code>  TP    : {tp_s}</code>",
            f"<code>  Size  : {wave.size:.2f} ({notn:.2f}$ notional)</code>",
            f"<code>  Lev   : {lev}x   Margin: {margin:.4f}$</code>",
            f"<code>  Conf  : {wave.confidence:.2f}</code>",
            f"<code>  Fee   : -{open_fee:.4f}$</code>",
            f"",
            f"<b>Balance</b>",
            f"<code>  equity : {equity:.4f}$   used: {used:.4f}$</code>",
            f"<code>  unreal : {unreal:+.4f}$  realized: {bal:+.4f}$</code>",
        ]
        notifier.send_message("\n".join(lines))
    except Exception:
        pass


async def notify_wave_close(notifier, wave, wallet=None, econ=None):
    """Notify on wave close — realized PnL + fees."""
    try:
        side_icon = "🟢" if wave.side == "BUY" else "🔴"
        econ = econ or {"close_fee": 0.0, "net": 0.0}
        close_fee = econ.get("close_fee", 0.0)
        net = econ.get("net", 0.0)
        pnl_icon = "🟢" if net >= 0 else "🔴"
        bal = wallet.balance if wallet else 0.0
        unreal = getattr(wallet, "unrealized", 0.0) if wallet else 0.0
        used = getattr(wallet, "used", 0.0) if wallet else 0.0
        equity = bal + unreal
        lines = [
            f"🌊 <b>WAVE CLOSE</b> {side_icon} {wave.side} {wave.pair}",
            f"<code>  Exit  : {wave.live_r:+.2f}R  ({wave.close_reason})</code>",
            f"<code>  {pnl_icon} Net : {net:+.4f}$</code>",
            f"<code>  Fee   : -{close_fee:.4f}$</code>",
            f"",
            f"<b>Balance</b>",
            f"<code>  equity : {equity:.4f}$   used: {used:.4f}$</code>",
            f"<code>  unreal : {unreal:+.4f}$  realized: {bal:+.4f}$</code>",
        ]
        notifier.send_message("\n".join(lines))
    except Exception:
        pass


def build_wave_card(waves: list, wallet=None) -> str:
    """Build a Telegram /wave card: open waves + portfolio metrics."""
    if wallet is not None:
        m = wallet.snapshot(waves)
        head = [
            f"🌊 <b>Wave Engine — {len(waves)} open</b>",
            f"<code>  Balance   : {m['balance']:.4f}$</code>",
            f"<code>  Used (margin): {m['used']:.4f}$</code>",
            f"<code>  Free       : {m['free']:.4f}$</code>",
            f"<code>  Unrealized: {m['unrealized']:+.4f}$</code>",
            f"<code>  Peak       : {m['peak']:.4f}$  (target {m['max_target']:.0f}$)</code>",
        ]
    else:
        head = [f"🌊 <b>Wave Engine — {len(waves)} open</b>"]
    if not waves:
        return "\n".join(head + ["", "  <i>scanning… no active waves</i>"])
    rows = []
    for w in waves:
        side_icon = "🟢" if w.side == "BUY" else "🔴"
        lev = getattr(w, "leverage", 1) or 1
        tp = getattr(w, "tp_price", None)
        tp_s = f"{tp:.4f}" if tp else "—"
        unreal = 0.0
        notn = getattr(w, "notional", 0.0) or 0.0
        if w.entry_price:
            risk_per_r = notn * (abs(w.entry_price - w.anchor) / w.entry_price)
            unreal = w.live_r * risk_per_r
        rows.append(
            f"  {side_icon} {w.side} <b>{w.pair}</b> ({w.tf})\n"
            f"     E <code>{w.entry_price:.4f}</code> SL <code>{w.sl_price:.4f}</code> "
            f"TP <code>{tp_s}</code>\n"
            f"     R <code>{w.live_r:+.2f}</code> | {lev}x | "
            f"unreal <code>{unreal:+.4f}$</code> | C <code>{w.confidence:.2f}</code>"
        )
    return "\n".join(head + [""] + rows)


def build_surf_card(closed_waves: list, wallet=None) -> str:
    """Build a /surf card of recent closed waves with aggregated stats."""
    if not closed_waves:
        return "🏄 <b>No closed waves yet.</b>"
    r_values = [w.live_r for w in closed_waves if w.live_r != 0]
    pnl_values = [getattr(w, "pnl_usd", 0.0) or 0.0 for w in closed_waves]
    median_r = sorted(r_values)[len(r_values) // 2] if r_values else 0.0
    wins = sum(1 for r in r_values if r > 0)
    total = len(r_values)
    wr = (wins / total * 100) if total else 0.0
    sum_pnl = sum(pnl_values)
    sum_fee = sum(getattr(w, "fees_usd", 0.0) or 0.0 for w in closed_waves)
    lines = [
        f"🏄 <b>Wave Surf Report</b>",
        f"<code>  Closed : {total}</code>",
        f"<code>  Win    : {wr:.1f}%  ({wins}/{total})</code>",
        f"<code>  Median R: {median_r:+.3f}</code>",
        f"<code>  Net PnL: {sum_pnl:+.4f}$</code>",
        f"<code>  Fees   : -{sum_fee:.4f}$</code>",
    ]
    if wallet is not None:
        m = wallet.snapshot()
        lines.append(f"<code>  Balance: {m['balance']:.4f}$</code>")
    return "\n".join(lines)

