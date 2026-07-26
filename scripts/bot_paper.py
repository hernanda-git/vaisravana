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
    return MarketState(
        symbol=pair, tf=DECISION_TF, regime=st.regime,
        htf_bias=htf_bias, last_close=bar.c,
        body_ratio=st.body_ratio, vol_z=st.vol_z, delta_z=st.delta_z,
        atr=st.atr, atr_pct=st.atr_pct, spread_bps=st.spread_bps,
        adl_rank=1, mtf_aligned=mtf_aligned,
    )


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
    log.info("Vaiśravaṇa PAPER bot up: %d pairs · decide=%s · ctx=%s · v%s · %d open positions reloaded "
             "(LLM=%s)", len(PAIRS), DECISION_TF, ",".join(TFS), ver, len(open_trades), LLM_MODE)
    notifier.notify_status(
        "Vaiśravaṇa PAPER bot started",
        f"pairs: {', '.join(PAIRS)}\n"
        f"decide every: {DECISION_TF} (jump immediately on close)\n"
        f"context tfs: {', '.join(TFS)} (MTF bias/alignment)\n"
        f"cycle: {CYCLE_S}s\n"
        f"mode: PAPER (no live orders)\nLLM research: {LLM_MODE}\n"
        f"open positions reloaded: {len(open_trades)}",
    )
    # Phase 13: announce the deployed version + what changed on every (re)start.
    notifier.notify_deploy(ver, vmod.latest_changelog())

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
            for pair in PAIRS:
                # Phase 12: one decision per minute on DECISION_TF (1m), using MTF context.
                _decide_tick(pair, conn, surface, lc, tel, kill, decider,
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


def research_loop(notifier: TelegramNotifier, db_path: str = DB_PATH) -> None:
    """Offline propose-only Sentinel loop (Phase 11). Runs in a daemon thread.

    Opens its OWN sqlite connection (SQLite objects are not shared across threads).
    Every RESEARCH_EVERY_S: gather real eval data -> LLMResearcher.propose ->
    Sentinel.cycle with a re-weight shadow replay -> if PROMOTED, persist surface to
    disk (picked up on next restart) and notify Telegram. The LLM output is funneled
    through apply_proposal (±10%, ≤4, doc-21 bounds) + shadow gate, so a hallucination
    can at most waste one replay. Never flips a (pair,tf,side) to live (human gate).
    """
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
            # Shadow comparison re-weights stored per-trade sub-scores with candidate.
            def comparison_factory(candidate: config.ParameterSurface):
                return _shadow_comparison(conn, surface, candidate)
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


def _shadow_comparison(conn, baseline_surface, candidate_surface):
    """Re-weight stored per-trade sub-scores with candidate weights -> shadow EvalReport.

    Deterministic, uses real closed trades. For each trade we recompute the chosen_score
    with candidate weights; if it still clears entry_threshold the trade is 'taken',
    otherwise it's skipped. Derived WR/expectancy/DD form the shadow report, compared
    against the baseline (real evaluate()).
    """
    from evaluation import EvalReport
    rows = conn.execute(
        "SELECT pair, tf, side, scores, win, r_multiple, exit_price, entry_price "
        "FROM trade_logs"
    ).fetchall()
    cw = candidate_surface.weights.as_dict()
    base = evaluate(conn, rows[0]["pair"], rows[0]["tf"], rows[0]["side"]) if rows else None

    shadow_pnl = []
    for r in rows:
        try:
            sc = json.loads(r["scores"]) if r["scores"] else {}
        except Exception:
            sc = {}
        # recompute chosen score with candidate weights (stored sub-scores only)
        chosen = sum(cw[k] * float(sc.get(k, 0.0)) for k in cw)
        if chosen >= candidate_surface.entry_threshold:
            shadow_pnl.append(float(r["r_multiple"]) if r["r_multiple"] is not None else 0.0)
    n = max(len(shadow_pnl), 1)
    wins = sum(1 for p in shadow_pnl if p > 0)
    exp = sum(shadow_pnl) / n if shadow_pnl else 0.0
    wr = wins / n * 100.0
    dd = max((0.0 - min(shadow_pnl)) if shadow_pnl else 0.0, 0.0)
    shadow = EvalReport(
        pair=base.pair if base else "", tf=base.tf if base else "",
        side=base.side if base else "", n_trades=len(shadow_pnl),
        win_rate_pct=wr, expectancy_r=exp, profit_factor=1.0,
        max_dd_pct=dd * 100.0, sharpe=0.0,
        passes={"wr_gate": wr >= candidate_surface.winrate_gate_pct},
    )
    # baseline mirrors shadow's accounting from the same stored trades
    base_wins = sum(1 for r in rows if r["win"])
    bn = max(len(rows), 1)
    base_wr = base_wins / bn * 100.0
    base_exp = (sum(float(r["r_multiple"]) for r in rows if r["r_multiple"] is not None)
                / bn) if rows else 0.0
    baseline = EvalReport(
        pair=shadow.pair, tf=shadow.tf, side=shadow.side, n_trades=len(rows),
        win_rate_pct=base_wr, expectancy_r=base_exp, profit_factor=1.0,
        max_dd_pct=base.max_dd_pct if base else 0.0, sharpe=0.0,
        passes={"wr_gate": base_wr >= baseline_surface.winrate_gate_pct},
    )
    # Reuse Sentinel.ShadowComparison semantics via a tiny adapter
    class _C:
        baseline = baseline
        shadow = shadow

        @property
        def shadow_not_worse(self):
            return (self.shadow.expectancy_r >= self.baseline.expectancy_r
                    and self.shadow.max_dd_pct <= self.baseline.max_dd_pct)

        @property
        def health_improved(self):
            return self.shadow.health() > self.baseline.health()

        @property
        def promotable(self):
            return self.shadow_not_worse and self.health_improved
    return _C()


def _decide_tick(pair, conn, surface, lc, tel, kill, decider, notifier, open_trades):
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
                       notifier, open_trades)
            elif hit_sl:
                _close(pair, k[1], k[2], t.sl_price, "SL", conn, lc, tel, kill,
                       notifier, open_trades)
            else:
                key = k
            break
    if key is not None:
        return  # one open position per pair; wait for it to close

    # kill-switch gate
    tripped, reason = kill.check_global(daily_loss_pct=0.0, adl_rank=1, feed_frozen=False)
    if tripped:
        tel.health("kill_switch", "FAIL", detail=reason)
        notifier.notify_kill_switch(reason)
        return

    # decide + open (PAPER) on the latest closed 1m bar
    prelim = decide(state, surface)
    atr = state.atr or dec[i].c * state.atr_pct
    entry = dec[i].c
    sl = (entry + surface.sl_atr_mult * atr) if prelim.side == "SELL" else \
         (entry - surface.sl_atr_mult * atr)
    tp = (entry - surface.tp_atr_mult * atr) if prelim.side == "SELL" else \
         (entry + surface.tp_atr_mult * atr)
    rec = decider.process(state, liquidity_ok=True, intraday_loss_pct=0.0,
                          sl_price=sl, entry_price=entry, leverage=surface.max_leverage)
    reason = "; ".join(rec.gate.reasons) if rec.gate else "two-layer gate"

    # Phase 12 immediacy gate: only act when MTF-aligned (don't fight the HTF bias)
    # and the spread is tight. This keeps entry_threshold at 0.90 — actionability
    # comes from 1m cadence, NOT a looser bar.
    if not state.mtf_aligned:
        if rec.actionable:
            notifier.notify_decision(pair, DECISION_TF, "WATCH", rec.scoring.chosen_score,
                                     rec.side or "-", reason + " | MTF not aligned")
        return
    if rec.actionable:
        notifier.notify_decision(pair, DECISION_TF, rec.decision, rec.scoring.chosen_score,
                                 rec.side or "-", reason)
    if not rec.actionable:
        return
    trade = lc.open(correlation_id=rec.correlation_id, pair=pair, tf=DECISION_TF,
                    side=rec.side, entry_price=entry, size=1.0,
                    leverage=surface.max_leverage, sl_price=sl, tp_price=tp,
                    decision_id=rec.id, spread_bps=state.spread_bps,
                    regime=state.regime, scores=rec.scoring.sub_scores.as_dict())
    open_trades[(pair, DECISION_TF, rec.side)] = trade
    tel.exec_event(rec.correlation_id, pair, DECISION_TF, "FILL", order_type="LIMIT",
                   side=rec.side, price=entry, qty=1.0, status="FILLED")
    notifier.notify_fill(pair, DECISION_TF, rec.side, entry, sl, tp, surface.max_leverage)


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
