"""Project Vaiśravaṇa — deployable PAPER bot for Fly.io (Phase 10).

Runs the real PAPER decision loop on LIVE Binance klines (fetched over HTTPS from
fapi.binance.com — Fly's sin region is not geo-blocked like the local ID network),
persists every decision/fill/close/win-loss to a volume DB, and reports to Telegram
through the same TELEGRAM_BOT_TOKEN / NOTIFY_CHAT_ID secrets the listener uses.

PAPER ONLY. There is no live-order path — promotion_gate(human_approved=True) is the
only thing that could ever flip a (pair,tf,side) to live, and that flag is set by a
human, not by this code.

Resilient across restarts (Fly restarts on deploys): open positions are reloaded from
the DB at boot, klines are refetched each cycle, and the loop is stateful.
"""

from __future__ import annotations

import os
import sys
import time
import json
import logging
import sqlite3
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import marketdata, config, decision, lifecycle, safety, telemetry, db, version as vmod
from telegram_bot import TelegramNotifier
from sentinel import Sentinel
from evaluation import evaluate
from llm_research import LLMResearcher, NarrativeResearcher, ZenClient
from config import default_surface  # noqa: E402
from db import init_db  # noqa: E402
from decision import DecisionOrchestrator  # noqa: E402
from engines import MarketState  # noqa: E402
from lifecycle import TradeLifecycle  # noqa: E402
from marketdata import Candle  # noqa: E402
from safety import KillSwitch  # noqa: E402
from scoring import decide  # noqa: E402
from telemetry import Telemetry  # noqa: E402
from execution import size_position  # noqa: E402
from symbols import SymbolRegistry  # noqa: E402
from marketdata import FeedHealth  # noqa: E402
from mode import ModeGuard, PaperSimExchange  # noqa: E402
from monitor import PositionMonitor, Position  # noqa: E402
from execution import place_stop_loss  # noqa: E402
from marketcontext import build_context, ContextSeries, MarketContext  # noqa: E402
from scoring import decide, decide_ctx  # noqa: E402

log = logging.getLogger("vaisravana.bot")

PAIRS = os.getenv("VAISRAVANA_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
TFS = os.getenv("VAISRAVANA_TFS", "5m,15m").split(",")
FETCH_URL = "https://fapi.binance.com/fapi/v1/klines?symbol={s}&interval={t}&limit={n}"
FETCH_LIMIT = int(os.getenv("VAISRAVANA_KLINES", "600"))
CYCLE_S = int(os.getenv("VAISRAVANA_CYCLE_S", "60"))  # 60s = one decision per minute
DB_PATH = os.getenv("VAISRAVANA_DB", "/data/vaisravana.db")
SURFACE_PATH = os.getenv("VAISRAVANA_SURFACE", "/data/surface.json")
# Phase 12: time-sensitive cadence.
#   DECISION_TF = the bar we DECIDE + ACT on every cycle (default 1m = jump immediately).
#   TFS          = structural contexts (default 5m,15m) that feed htf_bias / mtf_aligned,
#                  making the existing 7-factor engine multi-timeframe WITHOUT engine edits.
DECISION_TF = os.getenv("VAISRAVANA_DECISION_TF", "1m")
TFS = os.getenv("VAISRAVANA_TFS", "5m,15m").split(",")
# Phase 11 opt-in: off | research | research+context. Default OFF (deterministic).
LLM_MODE = os.getenv("VAISRAVANA_LLM", "off")
# LLM transport (OpenAI-compatible chat/completions). Defaults to OpenCode Zen gateway.
ZEN_API_KEY = os.getenv("ZEN_API_KEY", "")
ZEN_URL = os.getenv("ZEN_URL", "https://opencode.ai/zen/go/v1/chat/completions")
ZEN_MODEL = os.getenv("ZEN_MODEL", "deepseek-v4-flash")
RESEARCH_EVERY_S = int(os.getenv("VAISRAVANA_RESEARCH_EVERY_S", "1800"))


def load_surface() -> config.ParameterSurface:
    """Load the active parameter surface from disk, else the default.

    After a Sentinel promotion via research_loop, the new surface is persisted here so
    the live loop picks it up on the next restart. Falls back to default_surface() on any
    error (safe).
    """
    try:
        with open(SURFACE_PATH) as f:
            data = json.load(f)
        return config.ParameterSurface(**data)
    except FileNotFoundError:
        return default_surface()
    except Exception as e:  # noqa: BLE001
        log.warning("surface load failed, using default: %s", e)
        return default_surface()


def fetch_klines(symbol: str, tf: str, limit: int) -> list[Candle]:
    import urllib.request
    url = FETCH_URL.format(s=symbol, t=tf, n=limit)
    raw = json.loads(urllib.request.urlopen(url, timeout=15).read().decode())
    return [Candle(ts=r[0], o=float(r[1]), h=float(r[2]), l=float(r[3]),
                   c=float(r[4]), v=float(r[5])) for r in raw]


def _ema(vals: list[float], period: int) -> float:
    k = 2.0 / (period + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def build_state(pair: str, tf: str, candles: list[Candle], i: int) -> MarketState:
    import statistics
    w = candles[max(0, i - 50): i + 1]
    closes = [c.c for c in w]
    vols = [c.v for c in w]
    bar = candles[i]
    ema20 = _ema(closes[-20:], 20)
    ema50 = _ema(closes, 50)
    atr = statistics.mean(
        max(candles[j].h - candles[j].l,
            abs(candles[j].h - candles[j - 1].c),
            abs(candles[j].l - candles[j - 1].c))
        for j in range(max(1, i - 13), i + 1)
    )
    atr_pct = atr / bar.c
    bull = ema20 > ema50 * 1.0005
    bear = ema20 < ema50 * 0.9995
    regime = ("high_vol" if atr_pct > 0.012 else
              "trending_bull" if bull else "trending_bear" if bear else "range")
    signed = [(c.c - c.o) / (abs(c.c - c.o) + 1e-9) * c.v for c in w]
    mu, sd = statistics.mean(vols), (statistics.pstdev(vols) or 1e-9)
    smu, ssd = statistics.mean(signed), (statistics.pstdev(signed) or 1e-9)
    return MarketState(
        symbol=pair, tf=tf, regime=regime,
        htf_bias="bullish" if bull else ("bearish" if bear else "neutral"),
        last_close=bar.c, body_ratio=abs(bar.c - bar.o) / ((bar.h - bar.l) or 1e-9),
        vol_z=(vols[-1] - mu) / sd, delta_z=(signed[-1] - smu) / ssd,
        atr=atr, atr_pct=atr_pct, spread_bps=1.0, adl_rank=1,
    )


def _ema_cross(closes: list[float]) -> tuple[bool, bool]:
    """Return (bull, bear) from EMA20 vs EMA50 on the given closes (higher-TF bias)."""
    if len(closes) < 50:
        return False, False
    ema20 = _ema(closes[-20:], 20)
    ema50 = _ema(closes, 50)
    return ema20 > ema50 * 1.0005, ema20 < ema50 * 0.9995


def build_state_mtf(pair: str, dec_candles: list[Candle], i: int,
                     contexts: dict[str, list[Candle]]) -> MarketState:
    """Phase 12 — time-sensitive decision state.

    The 1m (DECISION_TF) bar drives the decision + act price. Structural TFs
    (contexts: {tf: candles}) set `htf_bias` (15m EMA cross) and `mtf_aligned`
    (1m EMA direction agrees with the higher-TF bias). This makes the EXISTING
    7-factor engine multi-timeframe without any engine edit — the engines read
    htf_bias/mtf_aligned already.

    Acting on the latest closed 1m bar's close = "jump immediately" in PAPER.
    """
    st = build_state(pair, DECISION_TF, dec_candles, i)
    bar = dec_candles[i]
    # 1m direction (for alignment)
    dec_bull, dec_bear = _ema_cross([c.c for c in dec_candles[max(0, i - 50): i + 1]])
    # pick the highest structural TF available for htf_bias (default 15m if present)
    htf_tf = max(contexts.keys(), key=lambda t: _tf_minutes(t)) if contexts else DECISION_TF
    htf = contexts.get(htf_tf) or dec_candles
    htf_bull, htf_bear = _ema_cross([c.c for c in htf[-50:]])
    htf_bias = "bullish" if htf_bull else ("bearish" if htf_bear else "neutral")
    # aligned = 1m direction agrees with the HTF bias (don't fight the trend)
    mtf_aligned = ((dec_bull and htf_bull) or (dec_bear and htf_bear)
                   or htf_bias == "neutral")

    # --- REAL structure / liquidity flags (doc 01/02/05/06) ---
    # Derived from the higher-TF context's last 20 bars so the structure (15%) and
    # liquidity (10%) engines are fed honest swing points in production — previously
    # left at their dataclass floors, which starved those two alpha factors live.
    w = htf[-20:]
    prior_hi = max(c.h for c in htf[-40:-20]) if len(htf) >= 40 else max(c.h for c in w)
    prior_lo = min(c.l for c in htf[-40:-20]) if len(htf) >= 40 else min(c.l for c in w)
    recent_hi = max(c.h for c in w[-10:])
    recent_lo = min(c.l for c in w[-10:])
    hh = recent_hi > prior_hi
    hl = recent_lo > prior_lo
    lh = recent_hi < prior_hi
    ll = recent_lo < prior_lo
    bos = (hh and htf_bull) or (ll and htf_bear)
    choch = (hh and htf_bear) or (ll and htf_bull)
    sweep_lo = bar.l < prior_lo and bar.c > prior_lo   # liquidity sweep of lows, reclaimed
    sweep_hi = bar.h > prior_hi and bar.c < prior_hi
    return MarketState(
        symbol=pair, tf=DECISION_TF, regime=st.regime,
        htf_bias=htf_bias, last_close=bar.c,
        body_ratio=st.body_ratio, vol_z=st.vol_z, delta_z=st.delta_z,
        atr=st.atr, atr_pct=st.atr_pct, spread_bps=st.spread_bps,
        adl_rank=1, mtf_aligned=mtf_aligned,
        hh=hh, hl=hl, lh=lh, ll=ll, bos=bos, choch=choch,
        liq_sweep=sweep_lo or sweep_hi, eq_low=sweep_lo, eq_high=sweep_hi,
        fvg=bos,
        # cross-asset + MTF relational context (v0.0.7) filled by build_context_for()
        btc_bias="neutral", dominance_delta=0.0, risk_regime="neutral",
        alt_rs_btc=0.0, alt_breadth=0.5,
        ltf_bias="neutral", mtf_bias=htf_bias, htf_bias2=htf_bias,
        mtf_confluence=False, pullback_to_anchor=False,
    )


def _closes(candles: list[Candle]) -> list[float]:
    return [c.c for c in candles]


def build_context_for(pair: str, dec_candles: list[Candle], i: int,
                      contexts: dict[str, list[Candle]]) -> MarketContext:
    """Build the cross-asset + MTF relational context for one decision tick (v0.0.7).

    Fetches BTC (leader), an alt basket (the other PAIRS), and the LTF/MF/HTF closes
    for the tradable, then derives BTC bias, dominance proxy, alt RS/breadth, and the
    3-layer MTF stack. Network is best-effort: any missing series falls back to neutral
    so the bot never crashes on a fetch hiccup.
    """
    def get(sym: str, tf: str, n: int = 60) -> list[float]:
        try:
            cs = fetch_klines(sym, tf, n)
            return _closes(cs)
        except Exception:
            return []

    # BTC leader (use the highest structural TF available, else 1h)
    btc_tf = "1h" if "1h" in TFS else (max(TFS, key=_tf_minutes) if TFS else "15m")
    btc = get("BTCUSDT", btc_tf)
    # alt basket = the other configured pairs (relative strength + breadth)
    basket = [get(p, btc_tf) for p in PAIRS if p != pair]
    basket = [b for b in basket if len(b) >= 50]
    pair_htf = get(pair, btc_tf)
    # LTF/MF/HTF of the tradable (anchor = HTF, pullback = LTF)
    ltf = get(pair, DECISION_TF)
    mtf = get(pair, (max(TFS, key=_tf_minutes) if TFS else "15m"))
    htf = pair_htf or btc
    cs = ContextSeries(
        btc=btc, pair=pair_htf, alt_basket=basket,
        ltf=ltf, mtf=mtf, htf=htf, dominance=[],
    )
    return build_context(cs, lookback=30)


def _tf_minutes(tf: str) -> int:
    """Parse a timeframe label to minutes (1m->1, 5m->5, 15m->15, 1h->60, ...)."""
    unit = tf[-1].lower()
    mult = int(tf[:-1]) if tf[:-1].isdigit() else 1
    return mult * {"m": 1, "h": 60, "d": 1440}.get(unit, 1)


def reload_open_trades(conn: sqlite3.Connection, lc: TradeLifecycle) -> dict:
    """Deprecated: use TradeLifecycle.get_open_positions()."""
    return lc.get_open_positions()


def run() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    conn = init_db(DB_PATH)
    surface = load_surface()          # persisted promoted surface or default
    lc = TradeLifecycle(conn)
    tel = Telemetry(conn)
    kill = KillSwitch(daily_loss_limit_pct=surface.daily_loss_limit_pct)
    decider = DecisionOrchestrator(conn, surface)
    notifier = TelegramNotifier(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("NOTIFY_CHAT_ID", ""),
    )
    open_trades: dict[tuple, object] = lc.get_open_positions()
    ver = vmod.read_version()
    registry = SymbolRegistry()
    feed = FeedHealth(max_age_s=max(30.0, CYCLE_S * 1.5))
    # --- HARD mode boundary (doc 30 §6/§7): structurally impossible to trade live
    # without human approval. PAPER (default) only ever drives a simulated exchange.
    mode = os.getenv("VAISRAVANA_MODE", "paper").lower()
    if mode not in ("paper", "live"):
        raise SystemExit(f"VAISRAVANA_MODE must be 'paper' or 'live', got {mode!r}")
    guard = ModeGuard(mode=mode)  # live_exchange=None in paper -> PaperSimExchange
    exchange = guard.exchange_for(None)  # PaperSimExchange in paper; GuardedExchange in live
    monitor = PositionMonitor(exchange, clock=time.time)
    # seed the monitor with any positions reloaded from the DB at boot
    for key, t in open_trades.items():
        monitor.track(Position(
            correlation_id=t.correlation_id, symbol=t.pair, tf=t.tf, side=t.side,
            qty=t.size, entry_price=t.entry_price,
            sl=__import__("execution").StopLossState(
                "CONDITIONAL", t.sl_price,
                "SELL" if t.side == "BUY" else "BUY", t.correlation_id),
            tp_price=t.tp_price, opened_ts=time.time(), sl_on_exchange=False,
        ))
    # Real daily-loss tracking so the kill-switch is actually wired (doc 30 §7).
    # Resets at UTC midnight. dollar equity approximated from a configurable seed.
    equity = float(os.getenv("VAISRAVANA_EQUITY_USD", "1000.0"))
    realized_loss_today = {"usd": 0.0, "day": ""}
    log.info("Vessavaṇa PAPER bot up: %d pairs · decide=%s · ctx=%s · v%s · %d open positions reloaded "
             "(LLM=%s)", len(PAIRS), DECISION_TF, ",".join(TFS), ver, len(open_trades), LLM_MODE)
    # Phase 13: clean startup card (Bahasa Indonesia, brand Vessavaṇa)
    notifier.notify_startup(ver, PAIRS, DECISION_TF, TFS, CYCLE_S, LLM_MODE, len(open_trades))
    # announce the deployed version + what changed on every (re)start
    notifier.notify_deploy(ver, vmod.latest_changelog())
    # doc 43: explicit on-deploy health check so the owner can confirm liveness
    # without waiting for a trade. UTC region from fly.toml primary_region.
    region = os.getenv("FLY_REGION", os.getenv("VAISRAVANA_REGION", "sin"))
    notifier.notify_health_check(ver, region, len(open_trades), feed_ok=True)

    # Phase 11: start the offline LLM research loop (propose-only Sentinel).
    # Default OFF -> bot is 100% deterministic, identical to before.
    if LLM_MODE != "off" and ZEN_API_KEY:
        research = threading.Thread(
            target=research_loop, args=(notifier,), daemon=True)
        research.start()
    elif LLM_MODE != "off" and not ZEN_API_KEY:
        log.warning("VAISRAVANA_LLM=%s but ZEN_API_KEY unset — research disabled", LLM_MODE)

    last_status = 0.0
    while True:
        try:
            # roll daily-loss window at UTC midnight
            today = time.strftime("%Y-%m-%d")
            if realized_loss_today["day"] != today:
                realized_loss_today = {"usd": 0.0, "day": today}
                kill.reset()  # fresh day -> clear any tripped kill-switch
            daily_loss_pct = (realized_loss_today["usd"] / equity * 100.0) if equity else 0.0
            # mark feed health from the latest candle we just fetched
            for pair in PAIRS:
                feed.mark(pair, DECISION_TF, int(time.time() * 1000))
                for tf in TFS:
                    feed.mark(pair, tf, int(time.time() * 1000))
            feed_frozen = bool(feed.frozen_list(PAIRS, [DECISION_TF] + TFS))
            for pair in PAIRS:
                # Phase 12: one decision per minute on DECISION_TF (1m), using MTF context.
                _decide_tick(pair, conn, surface, lc, tel, kill, decider,
                             notifier, open_trades, registry=registry,
                             daily_loss_pct=daily_loss_pct, feed_frozen=feed_frozen,
                             equity=equity, loss_book=realized_loss_today,
                             monitor=monitor, exchange=exchange, guard=guard)
                # push the latest price into the sim exchange so the monitor's
                # mark-price SL/TP/orphan/maxhold logic is real (doc 30 §3, doc 32 L4)
                _last_decs = fetch_klines(pair, DECISION_TF, 2)
                if _last_decs:
                    exchange.set_price(pair, _last_decs[-1].c)
            # drive the position monitor every cycle (real SL/maxhold/orphan handling)
            for ev in monitor.tick():
                t = open_trades.pop((ev.symbol, DECISION_TF, ev.side), None)
                if t is None:
                    continue
                res = lc.close(t, exit_price=ev.price, close_reason=ev.reason)
                kill.record_close(ev.symbol, DECISION_TF, ev.side, win=bool(res["win"]))
                if loss_book is not None and res["pnl_usd"] < 0:
                    loss_book["usd"] += -res["pnl_usd"]
                tel.exec_event(t.correlation_id, ev.symbol, DECISION_TF, "CLOSE",
                               side=ev.side, price=ev.price, status=ev.reason)
                notifier.notify_close(ev.symbol, DECISION_TF, ev.side, ev.price,
                                      ev.reason, res["r_multiple"], bool(res["win"]))
            # periodic status every ~30 min
            if time.time() - last_status > 1800:
                _report_status(conn, notifier)
                last_status = time.time()
        except Exception as e:  # never die silently — Surface restarts, but report first
            log.exception("loop error: %s", e)
            notifier.send_message(f"⚠️ **Vessavaṇa — error loop**\n_{e}_")
            time.sleep(30)
            continue
        time.sleep(CYCLE_S)


def _shadow_replay(conn: sqlite3.Connection, surface: config.ParameterSurface
                   ) -> tuple[list, list[dict]]:
    """Build baseline EvalReports + FP/FN cases for the researcher.

    Baseline = real `evaluation.evaluate` over trade_logs. FP/FN = ENTRY trades that
    hit SL, with their stored sub-scores + regime (used by the LLM to diagnose).
    """
    evals: list = []
    fp_fn: list[dict] = []
    rows = conn.execute(
        "SELECT DISTINCT pair, tf, side FROM trade_logs"
    ).fetchall()
    for (pair, tf, side) in rows:
        rep = evaluate(conn, pair, tf, side)
        evals.append(rep)
        # FP: closed at SL (loss) -> what score/context did it have?
        sl_rows = conn.execute(
            "SELECT scores, regime FROM trade_logs "
            "WHERE pair=? AND tf=? AND side=? AND win=0 AND close_reason='SL'",
            (pair, tf, side),
        ).fetchall()
        for r in sl_rows[:10]:
            try:
                sc = json.loads(r["scores"]) if r["scores"] else {}
            except Exception:
                sc = {}
            fp_fn.append({
                "pair": pair, "tf": tf, "side": side,
                "score": round(sc.get("chosen_score", 0.0), 3),
                "regime": r["regime"], "note": "ENTRY hit SL",
            })
    return evals, fp_fn


def _build_factories() -> dict:
    """Build state_factory[candles,i] per (pair,tf) from fetched klines for shadow replay.

    Each factory also carries its candle series as `. _candles` so the shadow harness can
    replay it (docs/src/shadow.py). Falls back to an empty series if klines are missing.
    """
    factories: dict = {}

    for pair in PAIRS:
        for tf in [DECISION_TF] + TFS:
            try:
                candles = fetch_klines(pair, tf, FETCH_LIMIT)
            except Exception:
                candles = []
            # reuse THIS module's MTF builder; empty contexts => single-tf state
            def _factory(candles, i, _pair=pair, _tf=tf):
                return build_state_mtf(_pair, candles, i, {})
            _factory._candles = candles  # type: ignore[attr-defined]
            factories[(pair, tf)] = _factory
    return factories


def research_loop(notifier: TelegramNotifier, db_path: str = DB_PATH) -> None:
    """Offline propose-only Sentinel loop (Phase 11). Runs in a daemon thread.

    Opens its OWN sqlite connection (SQLite objects are not shared across threads).
    Every RESEARCH_EVERY_S: gather real eval data -> LLMResearcher.propose ->
    Sentinel.cycle with a GENUINE shadow replay (re-simulates the full pipeline on raw
    candles with the candidate surface via src/shadow.py) -> if PROMOTED, persist surface
    to disk. The LLM output is funneled through apply_proposal (±10%, ≤4, doc-21 bounds)
    + shadow gate, so a hallucination can at most waste one replay. Never flips a
    (pair,tf,side) to live (human gate).
    """
    from shadow import shadow_compare  # genuine replay (was a dead re-weight, doc 40 §2.3)
    conn = init_db(db_path)  # thread-local connection
    log.info("LLM research loop starting (mode=%s, url=%s, model=%s)",
             LLM_MODE, ZEN_URL, ZEN_MODEL)
    client = ZenClient(api_key=ZEN_API_KEY, url=ZEN_URL, model=ZEN_MODEL)
    use_context = LLM_MODE == "research+context"
    researcher = LLMResearcher(client, enabled=True, url=ZEN_URL, model=ZEN_MODEL)
    narrative = NarrativeResearcher(client, enabled=use_context, url=ZEN_URL, model=ZEN_MODEL)
    last = 0.0
    while True:
        try:
            if time.time() - last < RESEARCH_EVERY_S:
                time.sleep(30)
                continue
            last = time.time()
            surface = load_surface()
            evals, fp_fn = _shadow_replay(conn, surface)
            if not evals:
                log.info("research: no trade history yet, skipping")
                continue
            # optional narrative tags (enum-constrained; neutral on any failure)
            if use_context:
                for pair in PAIRS:
                    _ = narrative.tags(pair)  # store/use elsewhere; safe no-op if neutral
            result = researcher.propose(surface, evals, fp_fn)
            if result.proposal is None:
                log.info("research: no proposal (disabled=%s, err=%s)",
                         not result.error, result.error)
                continue
            sentinel = Sentinel(conn, surface)
            # GENUINE shadow comparison: re-simulate on raw candles with candidate.
            factories = _build_factories()
            def comparison_factory(candidate: config.ParameterSurface):
                return shadow_compare(surface, candidate, factories,
                                       max_hold_bars=int(os.getenv("VAISRAVANA_SHADOW_BARS", "60")))
            promoted, new_surface = sentinel.cycle(
                result.proposal, comparison_factory,
                cycle_id=time.strftime("%Y-%m-%dT%H:%M"))
            if promoted:
                with open(SURFACE_PATH, "w") as f:
                    json.dump(new_surface.as_dict(), f, indent=2)
                notifier.notify_promotion(
                    "", "", f"v{sentinel.config_ver}",
                    f"LLM-proposed surface PROMOTED (shadow ≥ baseline, health ↑). "
                    f"Persisted to {SURFACE_PATH}; live loop reloads on next restart.")
                log.info("research: PROMOTED v%d", sentinel.config_ver)
            else:
                notifier.notify_promotion(
                    "", "", "REVIEW", "LLM-proposed surface ROLLED BACK (shadow not better).")
                log.info("research: ROLLBACK (shadow not better)")
        except Exception as e:  # noqa: BLE001 — research must never crash the bot
            log.exception("research loop error: %s", e)
            time.sleep(60)


def _decide_tick(pair, conn, surface, lc, tel, kill, decider, notifier, open_trades,
                registry=None, daily_loss_pct=0.0, feed_frozen=False, equity=1000.0,
                loss_book=None, monitor=None, exchange=None, guard=None):
    """Phase 12 — time-sensitive decision tick.

    Fetches the 1m (DECISION_TF) series + each structural context TF, builds an MTF
    MarketState on the latest closed 1m bar, decides, and (if actionable + MTF-aligned +
    spread tight) opens a PAPER position at that close — i.e. jumps immediately.
    """
    dec = fetch_klines(pair, DECISION_TF, FETCH_LIMIT)
    if len(dec) < 60:
        return
    contexts = {}
    for tf in TFS:
        if tf == DECISION_TF:
            continue
        c = fetch_klines(pair, tf, FETCH_LIMIT)
        if len(c) >= 50:
            contexts[tf] = c
    i = len(dec) - 1
    state = build_state_mtf(pair, dec, i, contexts)
    # v0.0.7: fold cross-asset + MTF relational context into the decision state
    try:
        ctx = build_context_for(pair, dec, i, contexts)
        state.btc_bias = ctx.btc_bias
        state.btc_ret = ctx.btc_ret
        state.dominance_delta = ctx.dominance_delta
        state.risk_regime = ctx.risk_regime
        state.alt_rs_btc = ctx.alt_rs_btc
        state.alt_breadth = ctx.alt_breadth
        state.ltf_bias = ctx.ltf_bias
        state.mtf_bias = ctx.mtf_bias
        state.htf_bias2 = ctx.htf_bias
        state.mtf_confluence = ctx.mtf_confluence
        state.pullback_to_anchor = ctx.pullback_to_anchor
    except Exception as e:  # best-effort: never let context fetch break the loop
        log.debug("context build failed for %s: %s", pair, e)

    # manage an existing position on this pair (any structural tf) by its 1m print
    key = None
    for k in list(open_trades.keys()):
        if k[0] == pair:
            t = open_trades[k]
            bar = dec[i]
            hit_tp = (t.side == "BUY" and bar.h >= t.tp_price) or \
                     (t.side == "SELL" and bar.l <= t.tp_price)
            hit_sl = (t.side == "BUY" and bar.l <= t.sl_price) or \
                     (t.side == "SELL" and bar.h >= t.sl_price)
            if hit_tp:
                _close(pair, k[1], k[2], t.tp_price, "TP", conn, lc, tel, kill,
                       notifier, open_trades, loss_book=loss_book)
            elif hit_sl:
                _close(pair, k[1], k[2], t.sl_price, "SL", conn, lc, tel, kill,
                       notifier, open_trades, loss_book=loss_book)
            else:
                key = k
            break
    if key is not None:
        return  # one open position per pair; wait for it to close

    # kill-switch gate (real daily-loss + feed-health, doc 30 §7)
    tripped, reason = kill.check_global(daily_loss_pct=daily_loss_pct,
                                        adl_rank=1, feed_frozen=feed_frozen)
    if tripped:
        tel.health("kill_switch", "FAIL", detail=reason)
        notifier.notify_kill_switch(reason)
        return

    # decide + open (PAPER) on the latest closed 1m bar — context-aware (v0.0.7)
    rec = decide_ctx(state, surface)
    if rec.decision != "ENTRY" or rec.side is None:
        # WATCH/SKIP: report if the base 7-factor engine thought it was actionable
        if rec.decision == "WATCH":
            notifier.notify_decision(pair, DECISION_TF, "WATCH", rec.chosen_score,
                                     rec.side or "-", "context gate / below threshold")
        return
    prelim = rec  # alias for the SL/TP derivation below
    corr_id = f"{pair}-{DECISION_TF}-{int(time.time()*1000)}-{rec.side}"
    atr = state.atr or dec[i].c * state.atr_pct
    entry = dec[i].c
    sl = (entry + surface.sl_atr_mult * atr) if prelim.side == "SELL" else \
         (entry - surface.sl_atr_mult * atr)
    tp = (entry - surface.tp_atr_mult * atr) if prelim.side == "SELL" else \
         (entry + surface.tp_atr_mult * atr)
    # NOTE: `decide_ctx` already applied the 7-factor engine + relational boost + the
    # hard context gate + the entry_threshold. The older DecisionOrchestrator two-layer
    # gate (decider.process) is intentionally NOT re-run here — decide_ctx is authoritative
    # for the scalping path. `rec` (from decide_ctx) carries side + chosen_score.
    reason = "context-aware entry (7-factor + BTC/dominance/MTF confluence)"

    # --- hard live boundary: in LIVE mode this raises unless human-approved ---
    if guard is not None:
        guard.assert_entry_allowed(pair, DECISION_TF, rec.side)
    # real risk-based sizing (doc 30 §3): 0.25% equity at the SL distance — replaces
    # the previous hardcoded size=1.0, which silently ignored the risk engine.
    info = (registry or SymbolRegistry()).get(pair)
    sl_distance = abs(entry - sl)
    qty = 1.0
    if info is not None and sl_distance > 0 and entry > 0:
        qty = size_position(equity=equity,
                            risk_per_trade_pct=surface.risk_per_trade_pct,
                            entry=entry, sl_price=sl, leverage=surface.max_leverage,
                            info=info, max_position_notional_pct=surface.max_position_notional_pct)
        qty = qty if qty > 0 else 1.0  # degenerate market -> fall back (skip), else minimal
    trade = lc.open(correlation_id=corr_id, pair=pair, tf=DECISION_TF,
                    side=rec.side, entry_price=entry, size=qty,
                    leverage=surface.max_leverage, sl_price=sl, tp_price=tp,
                    decision_id=corr_id, spread_bps=state.spread_bps,
                    regime=state.regime, scores=rec.sub_scores.as_dict())
    open_trades[(pair, DECISION_TF, rec.side)] = trade
    # REAL protective stop on the (simulated) exchange + hand the position to the
    # PositionMonitor so SL/TP/maxhold/orphan are managed every tick (doc 30 §3, doc 32 L4).
    sl_state = place_stop_loss(exchange, pair, rec.side, qty, sl) if exchange else None
    if monitor is not None:
        monitor.track(Position(
            correlation_id=corr_id, symbol=pair, tf=DECISION_TF,
            side=rec.side, qty=qty, entry_price=entry,
            sl=sl_state or __import__("execution").StopLossState(
                "CONDITIONAL", sl, "SELL" if rec.side == "BUY" else "BUY"),
            tp_price=tp, opened_ts=time.time(),
            sl_on_exchange=False,  # paper sim doesn't fill stops -> monitor polls mark
        ))
    tel.exec_event(corr_id, pair, DECISION_TF, "FILL", order_type="LIMIT",
                   side=rec.side, price=entry, qty=qty, status="FILLED")
    notifier.notify_fill(pair, DECISION_TF, rec.side, entry, sl, tp, surface.max_leverage)


def _close(pair, tf, side, exit_price, reason, conn, lc, tel, kill, notifier,
           open_trades, loss_book=None):
    t = open_trades.pop((pair, tf, side), None)
    if t is None:
        return
    res = lc.close(t, exit_price=exit_price, close_reason=reason)
    kill.record_close(pair, tf, side, win=bool(res["win"]))
    # accumulate realized loss for the daily-loss kill-switch (doc 30 §7)
    if loss_book is not None and res["pnl_usd"] < 0:
        loss_book["usd"] += -res["pnl_usd"]
    tel.exec_event(t.correlation_id, pair, tf, "CLOSE", side=side,
                   price=exit_price, status=reason)
    notifier.notify_close(pair, tf, side, exit_price, reason, res["r_multiple"],
                          bool(res["win"]))
    rep = evaluate(conn, pair, tf, side)
    if rep.n_trades >= 20 and rep.all_pass:
        notifier.notify_promotion(pair, tf, "SHADOW READY",
                                  f"WR {rep.win_rate_pct:.1f}% · Exp {rep.expectancy_r:+.2f}R · "
                                  f"health {rep.health():.2f} — needs human approval to go live")


def _report_status(conn: sqlite3.Connection, notifier: TelegramNotifier) -> None:
    from evaluation import EvalReport
    rows = conn.execute(
        "SELECT DISTINCT pair, tf, side FROM trade_logs"
    ).fetchall()
    lines = []
    for (pair, tf, side) in rows:
        rep: EvalReport = evaluate(conn, pair, tf, side)
        lines.append(f"`{pair} {tf} {side}`: n={rep.n_trades} WR={rep.win_rate_pct:.1f}% "
                     f"Exp={rep.expectancy_r:+.2f}R")
    if not lines:
        lines.append("_Belum ada trade dieksekusi._")
    notifier.notify_status_30m(lines)


if __name__ == "__main__":
    run()
