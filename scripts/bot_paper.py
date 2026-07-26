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

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import logging  # noqa: E402

from config import default_surface  # noqa: E402
from db import init_db  # noqa: E402
from decision import DecisionOrchestrator  # noqa: E402
from engines import MarketState  # noqa: E402
from evaluation import evaluate  # noqa: E402
from lifecycle import TradeLifecycle  # noqa: E402
from marketdata import Candle  # noqa: E402
from safety import KillSwitch  # noqa: E402
from scoring import decide  # noqa: E402
from telegram_bot import TelegramNotifier  # noqa: E402
from telemetry import Telemetry  # noqa: E402

log = logging.getLogger("vaisravana.bot")

PAIRS = os.getenv("VAISRAVANA_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
TFS = os.getenv("VAISRAVANA_TFS", "5m,15m").split(",")
FETCH_URL = "https://fapi.binance.com/fapi/v1/klines?symbol={s}&interval={t}&limit={n}"
FETCH_LIMIT = int(os.getenv("VAISRAVANA_KLINES", "600"))
CYCLE_S = int(os.getenv("VAISRAVANA_CYCLE_S", "30"))
DB_PATH = os.getenv("VAISRAVANA_DB", "/data/vaisravana.db")


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


def reload_open_trades(conn: sqlite3.Connection, lc: TradeLifecycle) -> dict:
    """Deprecated: use TradeLifecycle.get_open_positions()."""
    return lc.get_open_positions()


def run() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    conn = init_db(DB_PATH)
    surface = default_surface()
    lc = TradeLifecycle(conn)
    tel = Telemetry(conn)
    kill = KillSwitch(daily_loss_limit_pct=surface.daily_loss_limit_pct)
    decider = DecisionOrchestrator(conn, surface)
    notifier = TelegramNotifier(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.getenv("NOTIFY_CHAT_ID", ""),
    )
    open_trades: dict[tuple, object] = lc.get_open_positions()
    log.info("Vaiśravana PAPER bot up: %d pairs x %d tfs, %d open positions reloaded",
             len(PAIRS), len(TFS), len(open_trades))
    notifier.notify_status(
        "Vaiśravaṇa PAPER bot started",
        f"pairs: {', '.join(PAIRS)}\ntfs: {', '.join(TFS)}\n"
        f"mode: PAPER (no live orders)\nopen positions reloaded: {len(open_trades)}",
    )

    last_status = 0.0
    while True:
        try:
            for pair in PAIRS:
                for tf in TFS:
                    _cycle(pair, tf, conn, surface, lc, tel, kill, decider,
                           notifier, open_trades)
            # periodic status every ~30 min
            if time.time() - last_status > 1800:
                _report_status(conn, notifier)
                last_status = time.time()
        except Exception as e:  # never die silently — Surface restarts, but report first
            log.exception("loop error: %s", e)
            notifier.send_message(f"⚠️ **Vaiśravaṇa loop error**\n_{e}_")
            time.sleep(30)
            continue
        time.sleep(CYCLE_S)


def _cycle(pair, tf, conn, surface, lc, tel, kill, decider, notifier, open_trades):
    candles = fetch_klines(pair, tf, FETCH_LIMIT)
    if len(candles) < 60:
        return
    i = len(candles) - 1
    bar = candles[i]
    state = build_state(pair, tf, candles, i)
    atr = state.atr or bar.c * state.atr_pct
    entry = bar.c

    key = None  # set if a position is open
    # 1. manage existing position for this (pair,tf): check TP/SL on last bar
    for k in list(open_trades.keys()):
        if k[0] == pair and k[1] == tf:
            t = open_trades[k]
            hit_tp = (t.side == "BUY" and bar.h >= t.tp_price) or \
                     (t.side == "SELL" and bar.l <= t.tp_price)
            hit_sl = (t.side == "BUY" and bar.l <= t.sl_price) or \
                     (t.side == "SELL" and bar.h >= t.sl_price)
            if hit_tp:
                _close(pair, tf, k[2], t.tp_price, "TP", conn, lc, tel, kill,
                       notifier, open_trades)
            elif hit_sl:
                _close(pair, tf, k[2], t.sl_price, "SL", conn, lc, tel, kill,
                       notifier, open_trades)
            else:
                key = k
            break

    if key is not None:
        return  # one open position per (pair,tf,side); wait for it to close

    # 2. kill-switch gate
    tripped, reason = kill.check_global(daily_loss_pct=0.0, adl_rank=1,
                                        feed_frozen=False)
    if tripped:
        tel.health("kill_switch", "FAIL", detail=reason)
        notifier.notify_kill_switch(reason)
        return

    # 3. decide + open (PAPER)
    prelim = decide(state, surface)
    sl = (entry + surface.sl_atr_mult * atr) if prelim.side == "SELL" else \
         (entry - surface.sl_atr_mult * atr)
    tp = (entry - surface.tp_atr_mult * atr) if prelim.side == "SELL" else \
         (entry + surface.tp_atr_mult * atr)
    rec = decider.process(state, liquidity_ok=True, intraday_loss_pct=0.0,
                          sl_price=sl, entry_price=entry, leverage=surface.max_leverage)
    reason = "; ".join(rec.gate.reasons) if rec.gate else "two-layer gate"
    notifier.notify_decision(pair, tf, rec.decision, rec.scoring.chosen_score,
                             rec.side or "-", reason)
    if not rec.actionable:
        return
    trade = lc.open(correlation_id=rec.correlation_id, pair=pair, tf=tf,
                    side=rec.side, entry_price=entry, size=1.0,
                    leverage=surface.max_leverage, sl_price=sl, tp_price=tp,
                    decision_id=rec.id, spread_bps=state.spread_bps,
                    regime=state.regime, scores=rec.scoring.sub_scores.as_dict())
    open_trades[(pair, tf, rec.side)] = trade
    tel.exec_event(rec.correlation_id, pair, tf, "FILL", order_type="LIMIT",
                   side=rec.side, price=entry, qty=1.0, status="FILLED")
    notifier.notify_fill(pair, tf, rec.side, entry, sl, tp, surface.max_leverage)


def _close(pair, tf, side, exit_price, reason, conn, lc, tel, kill, notifier, open_trades):
    t = open_trades.pop((pair, tf, side), None)
    if t is None:
        return
    res = lc.close(t, exit_price=exit_price, close_reason=reason)
    kill.record_close(pair, tf, side, win=bool(res["win"]))
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
        lines.append("_no trades yet_")
    notifier.notify_status("Vaiśravaṇa status (30m)", "\n".join(lines))


if __name__ == "__main__":
    run()
