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
import uuid
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import marketdata, config, decision, lifecycle, safety, telemetry, db, version as vmod
from telegram_bot import TelegramNotifier
from telegram_bot import TelegramCommandListener  # noqa: E402
from sentinel import Sentinel
from evaluation import evaluate
from llm_research import LLMResearcher, NarrativeResearcher, ZenClient
from config import default_surface  # noqa: E402
from db import init_db, db_stats, paper_stats  # noqa: E402
from decision import DecisionOrchestrator  # noqa: E402
from engines import MarketState  # noqa: E402
from lifecycle import TradeLifecycle  # noqa: E402
from marketdata import Candle  # noqa: E402
from safety import KillSwitch  # noqa: E402
from scoring import decide  # noqa: E402
from telemetry import Telemetry  # noqa: E402
from execution import size_position  # noqa: E402

# v0.0.32: load a local .env (optional) so the same code runs on a bare VPS without
# editing fly.toml. python-dotenv is not a dependency — use a tiny inline parser.
def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
    except Exception as e:  # never block boot on a bad .env
        log.warning("dotenv load skipped: %s", e)

_load_dotenv()

# v0.0.32: urllib does not honor HTTP_PROXY/HTTPS_PROXY by default. Build a proxy-aware
# opener once if either var is set, so a Tencent/VPS deployment behind a proxy can reach
# Binance + Telegram. No-op when no proxy is configured.
def _install_proxy_opener() -> None:
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if not proxy:
        return
    try:
        import urllib.request as _ur
        handler = _ur.ProxyHandler({"http": proxy, "https": proxy})
        _ur.install_opener(_ur.build_opener(handler))
        log.info("proxy opener installed (%s)", proxy)
    except Exception as e:
        log.warning("proxy opener failed: %s", e)

log = logging.getLogger("vaisravana.bot")

_install_proxy_opener()

from symbols import SymbolRegistry  # noqa: E402
from marketdata import FeedHealth  # noqa: E402
from mode import ModeGuard, PaperSimExchange  # noqa: E402
from monitor import PositionMonitor, Position  # noqa: E402
from execution import place_stop_loss  # noqa: E402
from marketcontext import build_context, ContextSeries, MarketContext  # noqa: E402
from scoring import decide, decide_ctx  # noqa: E402
from strategy import active_strategies, evaluate_strategy  # noqa: E402
from config import default_profiles  # noqa: E402
from symbols import resolve_symbol, DEFAULT_UNIVERSE  # noqa: E402

PAIRS = os.getenv("VAISRAVANA_PAIRS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
TFS = os.getenv("VAISRAVANA_TFS", "5m,15m").split(",")
# v0.0.10: monitored universe defaults to the 15-pair mix (leaders + 12 requested alts).
# Resolved through symbols.resolve_symbol() so "PEPE"/"BONK" map to their 1000x contract.
PAIRS = [resolve_symbol(p) for p in
         os.getenv("VAISRAVANA_PAIRS", ",".join(DEFAULT_UNIVERSE)).split(",") if p]
# The higher structural contexts every strategy reads for bias + structure.
TFS = os.getenv("VAISRAVANA_TFS", "5m,15m").split(",")
# v0.0.32: data source is env-driven so the bot runs on any host (Fly, bare VPS, Tencent).
# Binance fapi is geo-blocked in some regions (e.g. mainland CN) — point FETCH_URL at a
# proxy/mirror there. No proxy support in urllib, so use a full URL override.
FETCH_URL = os.getenv(
    "VAISRAVANA_KLINES_URL",
    "https://fapi.binance.com/fapi/v1/klines?symbol={s}&interval={t}&limit={n}")
# Optional HTTP(S) proxy for kline + Telegram fetches (urllib reads HTTP_PROXY/HTTPS_PROXY
# only when opener is built with ProxyHandler — see _install_proxy()).
FETCH_LIMIT = int(os.getenv("VAISRAVANA_KLINES", "600"))
# v0.0.33: paper-account + fee model for the redesigned notifier.
# Fake starting balance ($10); bot "runs until balance hits 0". Each open AND close
# pays a taker fee (Binance USDⓈ-M default 0.04% per side). Fees are charged on the
# full notional (price * size), same as real futures.
FEE_RATE = float(os.getenv("VAISRAVANA_FEE_RATE", "0.0004"))
# v0.0.34: paper entries are modeled as post-only LIMIT at the decision-bar
# close (the bot already "fills" at that price) → maker fee on OPEN, taker on
# CLOSE (SL/TP/MAXHOLD exits are stop-market). Cuts modeled round-trip ~25-50%.
FEE_RATE_MAKER = float(os.getenv("VAISRAVANA_FEE_RATE_MAKER", "0.0002"))
START_BALANCE = float(os.getenv("VAISRAVANA_START_BALANCE", "10.0"))
# v0.0.33: portfolio-level exposure ceiling (goals.md: capital preservation).
# Cap concurrent positions and total margin-used so a unified SL cascade cannot
# wipe the $10 paper account. Tunable via env.
MAX_OPEN_POSITIONS = int(os.getenv("VAISRAVANA_MAX_OPEN", "5"))
MAX_TOTAL_MARGIN_PCT = float(os.getenv("VAISRAVANA_MAX_MARGIN_PCT", "50.0"))


def paper_equity(conn, open_trades: dict, get_mark) -> dict:
    """Equity snapshot for notifier footers.

    Combines DB realized PnL (paper_stats) with live unrealized PnL from marks.
    get_mark(pair) -> current price or None.
    """
    base = paper_stats(conn, start_balance=START_BALANCE, fee_rate=FEE_RATE)
    unreal = 0.0
    for (pair, _tf, side), t in open_trades.items():
        mark = get_mark(pair) if get_mark else None
        if mark is None:
            mark = t.entry_price
        d = 1.0 if side == "BUY" else -1.0
        unreal += (mark - t.entry_price) * d * t.size
    base["unrealized"] = round(unreal, 2)
    base["equity"] = round(base["balance"] + unreal, 2)
    return base

CYCLE_S = int(os.getenv("VAISRAVANA_CYCLE_S", "60"))  # 60s = one decision per minute
# v0.0.32: default to a local ./data dir (works on any host) instead of Fly-only /data.
# Set VAISRAVANA_DB=/data/vaisravana.db on Fly to keep the volume behaviour.
_DATA_DIR = os.getenv("VAISRAVANA_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))
DB_PATH = os.getenv("VAISRAVANA_DB", os.path.join(_DATA_DIR, "vaisravana.db"))
SURFACE_PATH = os.getenv("VAISRAVANA_SURFACE", os.path.join(_DATA_DIR, "surface.json"))
# v0.0.16: caretaker cron state file (deploy cooldown + excluded pairs). `/clean` removes
# it so the caretaker may re-tune immediately after a fresh start.
CRON_STATE_PATH = Path(__file__).resolve().parent.parent / ".vaisravana_cron_state.json"

# v0.0.19: tighter side-bleed floor + per-side threshold adj + post-SL cooldown.
SIDE_EXP_MIN_SAMPLES = int(os.getenv("VAISRAVANA_SIDE_MIN_SAMPLES", "20"))
SIDE_EXP_FLOOR_R = float(os.getenv("VAISRAVANA_SIDE_EXP_FLOOR", "-0.10"))
SIDE_THRESHOLD_ADJ = float(os.getenv("VAISRAVANA_SIDE_THRESHOLD_ADJ", "0.06"))
SL_COOLDOWN_TICKS = int(os.getenv("VAISRAVANA_SL_COOLDOWN", "3"))

# ── v0.0.34: survival-mode risk layer ────────────────────────────────────
# Root-cause fixes from the 2026-07-28 run post-mortem ($10 → $1.49 in 10h):
#   1. sizing scale bug — qty was computed against the static env equity
#      ($1000) instead of the LIVE paper balance ($10), producing $956-notional
#      ETH entries (one SL = -$6.22 = 60% of the account) next to $0.00 dust
#      entries on pairs missing from the SymbolRegistry.
#   2. fee bleed — 106 trades/10h at 8 bps round-trip ate $8.40 on ~breakeven
#      gross. Gates below enforce fee-aware EV, hourly throttle, session
#      filter, loss-streak cooldown and post-blowout-candle skip.
# All of this is additive risk/gate layer (ParameterSurface untouched).
MAX_NOTIONAL_X_EQUITY = float(os.getenv("VAISRAVANA_MAX_NOTIONAL_X_EQUITY", "2.0"))
MIN_NOTIONAL_USD = float(os.getenv("VAISRAVANA_MIN_NOTIONAL_USD", "5.0"))
# round-trip fee may consume at most this fraction of 1R (dollar risk at SL)
FEE_R_MAX_FRAC = float(os.getenv("VAISRAVANA_FEE_R_MAX_FRAC", "0.25"))
# TP must be at least this % move from entry (expected move >= 3x round-trip cost)
MIN_TP_MOVE_PCT = float(os.getenv("VAISRAVANA_MIN_TP_MOVE_PCT", "0.24"))
MAX_ENTRIES_PER_HOUR = int(os.getenv("VAISRAVANA_MAX_ENTRIES_PER_HOUR", "10"))
PAIR_ENTRY_SPACING_S = int(os.getenv("VAISRAVANA_PAIR_ENTRY_SPACING_S", "900"))
SESSION_BLOCK_UTC = {int(h) for h in
                     os.getenv("VAISRAVANA_SESSION_BLOCK_UTC", "0,1,2,3,4,5").split(",")
                     if h.strip().isdigit()}
LOSS_STREAK_N = int(os.getenv("VAISRAVANA_LOSS_STREAK_N", "3"))
LOSS_STREAK_COOLDOWN_S = int(os.getenv("VAISRAVANA_LOSS_STREAK_COOLDOWN_S", "1800"))
BIG_CANDLE_ATR_MULT = float(os.getenv("VAISRAVANA_BIG_CANDLE_ATR_MULT", "3.0"))
# v0.0.35 (red-team wave-1): ADX hard gate demoted 25 -> 15. 1m ADX is lag+noise;
# at 25 it blocked ~50 signals/h and fought the top-chase guard (ADX demands
# established trend, top-chase demands pullback — intersection near-empty).
# Trend quality already lives in the weighted score; the hard gate only rejects
# outright chop now.
ADX_MIN = float(os.getenv("VAISRAVANA_ADX_MIN", "15.0"))
# v0.0.35: BE-trail arms at +1.0R (was +0.5R). Run-1 evidence: the profit engine
# was MAXHOLD grinds (+$8.03); arming BE at +0.5R would scratch exactly the
# oscillating paths that mature into those winners.
BE_TRAIL_ARM_R = float(os.getenv("VAISRAVANA_BE_TRAIL_ARM_R", "1.0"))
# v0.0.35: signal-flip exit (idea validated in ajidwip/ai-trading-sequence-5m
# "AI_REVERSE"): when the engine's decision flips to a full opposite-side ENTRY
# signal while a position is open, exit at market instead of riding to SL.
# Cuts the avg loser (-1R -> approx -0.3..-0.5R) without capping winners.
SIGNAL_FLIP_EXIT = os.getenv("VAISRAVANA_SIGNAL_FLIP_EXIT", "1") == "1"

# shared risk-layer state (single-threaded decision loop → plain dict is safe)
RISK_STATE: dict = {"hour": -1, "entries_hour": 0, "pair_last_entry": {},
                    "loss_streak": 0, "cooldown_until": 0.0}
# per-trade excursion tracker {correlation_id: [mfe_r, mae_r]} — feeds the
# mfe_r/mae_r columns that were NULL for the entire first run (instrumentation
# fix: exit science is impossible without excursion data).
EXCURSIONS: dict = {}
# v0.0.34b: veto-note dedup — repetitive vetoes (session filter, pair spacing,
# hourly throttle) fire on EVERY tick of every pair; without dedup they write
# hundreds of identical GATED rows/hour into decisions_log (20k rows in run 1-2)
# and spam the log. Record each (pair, veto-class) at most once per window.
VETO_NOTE_WINDOW_S = int(os.getenv("VAISRAVANA_VETO_NOTE_WINDOW_S", "3600"))
_VETO_NOTES: dict = {}


def _veto_should_note(pair: str, veto: str) -> bool:
    """True when this (pair, veto-class) hasn't been recorded in the window."""
    key = (pair, veto.split(":", 1)[0])
    now = time.time()
    if now - _VETO_NOTES.get(key, 0.0) < VETO_NOTE_WINDOW_S:
        return False
    _VETO_NOTES[key] = now
    # opportunistic cleanup so the dict never grows unbounded
    if len(_VETO_NOTES) > 512:
        for k in [k for k, v in _VETO_NOTES.items() if now - v > VETO_NOTE_WINDOW_S]:
            del _VETO_NOTES[k]
    return True


def _record_loss_streak(win: bool) -> None:
    """v0.0.34: anti-cluster cooldown — 3 consecutive losses pause NEW entries."""
    if win:
        RISK_STATE["loss_streak"] = 0
        return
    RISK_STATE["loss_streak"] += 1
    if RISK_STATE["loss_streak"] >= LOSS_STREAK_N:
        RISK_STATE["cooldown_until"] = time.time() + LOSS_STREAK_COOLDOWN_S
        RISK_STATE["loss_streak"] = 0
        log.info("loss-streak cooldown armed: %ds", LOSS_STREAK_COOLDOWN_S)


def survival_gates(pair: str, entry: float, sl: float, tp: float, qty: float,
                   equity: float, dec_bar, atr_pct: float,
                   side: str = "") -> tuple[float, str]:
    """v0.0.34 pre-entry risk gates. Returns (qty_final, "") or (0.0, veto_reason).

    Order: cheap contextual vetoes first, then notional scaling vs LIVE equity,
    then fee-aware EV checks on the scaled size.
    v0.0.35: session filter applies to BUY only — run-1 evidence says the SELL
    edge (trending_bear) fires at all hours and the bot is frequency-starved;
    blocking 21% of hours for the proven side was unmeasured throughput loss.
    """
    import datetime as _dt
    now = time.time()
    hour = _dt.datetime.now(_dt.timezone.utc).hour
    if hour in SESSION_BLOCK_UTC and side != "SELL":
        return 0.0, f"session filter: {hour:02d}h UTC blocked (BUY only)"
    if now < RISK_STATE["cooldown_until"]:
        return 0.0, f"loss-streak cooldown: {int(RISK_STATE['cooldown_until'] - now)}s left"
    if RISK_STATE["hour"] != hour:
        RISK_STATE["hour"] = hour
        RISK_STATE["entries_hour"] = 0
    if RISK_STATE["entries_hour"] >= MAX_ENTRIES_PER_HOUR:
        return 0.0, f"hourly throttle: {RISK_STATE['entries_hour']} entries this hour"
    last = RISK_STATE["pair_last_entry"].get(pair, 0.0)
    if now - last < PAIR_ENTRY_SPACING_S:
        return 0.0, f"pair spacing: last {pair} entry {int(now - last)}s ago"
    # post-blowout-candle skip: adverse selection + liquidation noise right
    # after a bar > BIG_CANDLE_ATR_MULT x ATR.
    if dec_bar is not None and atr_pct > 0:
        rng_pct = (dec_bar.h - dec_bar.l) / (dec_bar.c or 1.0) * 100.0
        if rng_pct > BIG_CANDLE_ATR_MULT * atr_pct:
            return 0.0, f"big-candle skip: bar range {rng_pct:.2f}% > {BIG_CANDLE_ATR_MULT:.0f}x ATR {atr_pct:.2f}%"
    if entry <= 0 or qty <= 0:
        return 0.0, "invalid entry/qty"
    # ── notional scale vs LIVE equity ──
    cap = MAX_NOTIONAL_X_EQUITY * max(equity, 0.0)
    if cap <= 0:
        return 0.0, "no equity left"
    notional = qty * entry
    if notional > cap:
        qty = cap / entry
        notional = cap
    if notional < MIN_NOTIONAL_USD:
        if MIN_NOTIONAL_USD > cap:
            return 0.0, f"cannot size: min ${MIN_NOTIONAL_USD:.0f} notional > cap ${cap:.2f} (2x equity)"
        qty = MIN_NOTIONAL_USD / entry
        notional = MIN_NOTIONAL_USD
    # ── fee-aware EV gates ──
    sl_dist = abs(entry - sl)
    one_r_usd = sl_dist * qty
    fee_rt = FEE_RATE * 2.0 * notional
    if one_r_usd <= 0 or fee_rt > FEE_R_MAX_FRAC * one_r_usd:
        return 0.0, (f"EV gate: round-trip fee ${fee_rt:.4f} > "
                     f"{FEE_R_MAX_FRAC:.0%} of 1R ${one_r_usd:.4f}")
    tp_move_pct = abs(tp - entry) / entry * 100.0
    if tp_move_pct < MIN_TP_MOVE_PCT:
        return 0.0, f"EV gate: TP move {tp_move_pct:.3f}% < {MIN_TP_MOVE_PCT}% min"
    return qty, ""


def entry_allowed(state, side: str, sc: int, sexp: float) -> tuple[bool, str]:
    """v0.0.20 hierarchical HTF gate — fixes the retracement trap.

    A trade may open only if ALL hold:
      1. Side not bleeding (unchanged from v0.0.18).
      2. Pair's own HTF trend (htf_bias, EMA20/50 on highest context TF) must
         agree with the trade side — this is the PRIMARY directional signal.
      3. Higher TF (htf_bias2, 1h/4h) must agree — prevents buying a 15m
         retracement within a 1h downtrend (THE root cause of the 25% BUY WR).
      4. BTC leader (btc_bias) and risk regime only override DOWN (never UP) —
         they can block but never allow against the pair's own HTF signal.
      5. Neutral HTF with no pullback → blocked (don't chase extremes).

    Returns (allowed, reason). Pure + testable.
    """
    # 1. Side-bleed check (unchanged)
    if sc >= SIDE_EXP_MIN_SAMPLES and sexp < SIDE_EXP_FLOOR_R:
        return False, (f"{side} bleeding: exp {sexp:+.2f}R over {sc} trades "
                       f"(<{SIDE_EXP_FLOOR_R:+.2f}R floor) — side suppressed")

    # 2. Read state signals
    htf = getattr(state, "htf_bias", "neutral")   # pair's own HTF (15m/1h EMA20/50)
    htf2 = getattr(state, "htf_bias2", "neutral") # higher TF (1h/4h EMA20/50)
    btc = getattr(state, "btc_bias", "neutral")
    risk = getattr(state, "risk_regime", "neutral")
    pullback = getattr(state, "pullback_to_anchor", False)

    if side == "BUY":
        # Layer 1: pair's OWN HTF must be bullish
        if htf == "bearish":
            return False, f"BUY blocked: htf={htf} (pair's trend bearish)"
        # Layer 2: higher TF must NOT disagree (prevents retracement trap)
        if htf2 == "bearish":
            return False, f"BUY blocked: htf2={htf2} (higher TF bearish — retracement trap)"
        # Layer 3: BTC leader must not disagree
        if btc == "bearish":
            return False, "BUY blocked: BTC bearish"
        # Layer 4: risk regime must not be risk-off
        if risk == "bearish":
            return False, "BUY blocked: risk-off regime"
        # Layer 5: neutral HTF needs pullback XOR liquidity sweep
        if htf == "neutral" and not pullback and not getattr(state, "liq_sweep", False):
            return False, "BUY blocked: neutral HTF needs pullback or liquidity sweep"
        # Layer 6 (v0.0.34): top-chase guard. Run 2026-07-28: trending_bull+BUY
        # = -$6.47 at 19% WR — the bot bought extended bull tape at local tops.
        # In trending_bull, a BUY must come on a pullback, never on extension.
        if getattr(state, "regime", "") == "trending_bull" and not pullback:
            return False, "BUY blocked: extended bull tape, no pullback (top-chase guard)"
        return True, ""

    else:  # SELL
        if htf == "bullish":
            return False, f"SELL blocked: htf={htf} (pair's trend bullish)"
        if htf2 == "bullish":
            return False, f"SELL blocked: htf2={htf2} (higher TF bullish — retracement trap)"
        if btc == "bullish":
            return False, "SELL blocked: BTC bullish"
        if risk == "bullish":
            return False, "SELL blocked: risk-on regime"
        if htf == "neutral" and not pullback and not getattr(state, "liq_sweep", False):
            return False, "SELL blocked: neutral HTF needs pullback or liquidity sweep"
        return True, ""


# ── v0.0.19: ADX trend strength filter ──────────────────────────────────
def compute_cvd_z(candles, lookback: int = 15) -> float | None:
    """v0.0.35 (research wave-1): CVD / taker order-flow imbalance z-score.

    Per-bar delta = 2*takerBuyVol - vol (>0 = net aggressive buying). Z-score
    of the last bar's delta vs the trailing `lookback` bars. Strongest
    academically-backed short-horizon signal available at ZERO extra REST cost
    (klines field idx 9). Used as a directional veto:
      - veto SELL when cvd_z > +CVD_VETO_Z (aggressive buyers in control)
      - veto BUY  when cvd_z < -CVD_VETO_Z (aggressive sellers in control)
    Returns None when taker-buy data is missing.
    """
    if not candles or len(candles) < lookback + 1:
        return None
    window = candles[-(lookback + 1):]
    if all(getattr(b, "tb", 0.0) <= 0.0 for b in window):
        return None
    deltas = [2.0 * getattr(b, "tb", 0.0) - b.v for b in window]
    hist, last = deltas[:-1], deltas[-1]
    mean = sum(hist) / len(hist)
    var = sum((d - mean) ** 2 for d in hist) / max(len(hist) - 1, 1)
    sd = var ** 0.5
    if sd <= 0:
        return 0.0
    return (last - mean) / sd


CVD_VETO_Z = float(os.getenv("VAISRAVANA_CVD_VETO_Z", "1.0"))

# v0.0.35: open-interest tracker {pair: (ts, oi)} for the flush detector.
_OI_STATE: dict = {}


def oi_flush_veto(pair: str, price_falling: bool, side: str) -> str:
    """v0.0.35 (research wave-1): OI-delta x price direction gate.

    price DOWN + OI DOWN = liquidation flush (longs forcibly closing); selling
    INTO a flush fills at the flush bottom — run-1's likely SELL failure mode.
    price UP + OI DOWN = short-squeeze pop; buying it = buying the top.
    Fails open (returns "") on any fetch error — enhancement, never an
    availability risk. One REST call (weight 1) per candidate entry only.
    """
    import urllib.request
    try:
        url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={pair}"
        oi = float(json.loads(urllib.request.urlopen(url, timeout=6).read())["openInterest"])
    except Exception:
        return ""
    prev = _OI_STATE.get(pair)
    _OI_STATE[pair] = (time.time(), oi)
    if prev is None or prev[1] <= 0:
        return ""
    oi_chg_pct = (oi - prev[1]) / prev[1] * 100.0
    if side == "SELL" and price_falling and oi_chg_pct < -0.3:
        return (f"OI flush veto: price down + OI {oi_chg_pct:+.2f}% "
                f"(long-liquidation flush — don't sell the bottom)")
    if side == "BUY" and not price_falling and oi_chg_pct < -0.3:
        return (f"OI flush veto: price up + OI {oi_chg_pct:+.2f}% "
                f"(short-squeeze pop — don't buy the top)")
    return ""


def compute_adx(candles: list, period: int = 14) -> float:
    """Average Directional Index 0-100. <20 = weak/choppy, 20-40 = trending, >40 = strong.
    Returns 0 on insufficient data (safe: won't block)."""
    if len(candles) < period + 1:
        return 0.0
    tr = [max(c.h - c.l, abs(c.h - c.c), abs(c.l - c.c)) for c in candles]
    plus = [(c.h - p.h) if c.h - p.h > p.l - c.l and c.h > p.h else 0.0
            for c, p in zip(candles[1:], candles[:-1])]
    minus = [(p.l - c.l) if p.l - c.l > c.h - p.h and p.l > c.l else 0.0
             for c, p in zip(candles[1:], candles[:-1])]
    atr14 = sum(tr[-period:]) / period
    pdm = sum(plus[-period:]) / period
    ndm = sum(minus[-period:]) / period
    pdi = pdm / atr14 * 100.0 if atr14 > 0 else 0.0
    ndi = ndm / atr14 * 100.0 if atr14 > 0 else 0.0
    dx = abs(pdi - ndi) / (pdi + ndi) * 100.0 if (pdi + ndi) > 0 else 0.0
    return dx


def adx_allowed(adx_val: float, threshold: float = 25.0) -> tuple[bool, str]:
    """Block entry if ADX < threshold (choppy → MAXHOLD risk).

    ADX < 1.0 (degenerate/near-zero) is treated as unknown and allowed.
    v0.0.20: threshold raised to 25 (was 20) — stronger trend required.
    """
    if adx_val < 1.0:  # degenerate / can't compute
        return True, ""
    if adx_val < threshold:
        return False, f"ADX {adx_val:.1f} < {threshold} (weak trend — likely MAXHOLD)"
    return True, ""


# ── v0.0.19: volatility-adaptive SL scale ──────────────────────────────
def volatility_scale(pair: str, atr_pct: float,
                     all_atr: dict[str, float] | None = None) -> float:
    """Scale SL mult wider for high-vol pairs, tighter for low-vol pairs.

    sqrt(pair_ATR% / median_ATR%). Clamped [0.7, 1.5]. Falls back to 1.0."""
    if not all_atr:
        return 1.0
    vals = sorted([v for v in all_atr.values() if v > 0])
    if not vals:
        return 1.0
    median = vals[len(vals) // 2]
    if median <= 0:
        return 1.0
    return max(0.7, min(1.5, (atr_pct / median) ** 0.5))


# ── v0.0.19: pair-level weight for sizing ──────────────────────────────
PAIR_WEIGHTS: dict[str, float] = {}

# v0.0.21: profile-specific EMA periods — match signal to hold time.
# Scalp (1m hold 15m): fast EMA5/15 = ~15-bar signal = 15 min.
# Day (15m hold 4h):  EMA20/50 = ~50-bar signal = 12.5h.
# Swing (1h hold 48h): EMA50/200 = ~200-bar signal = ~200h.
PROFILE_EMA: dict[str, tuple[int, int]] = {
    "scalping": (5, 15),
    "day": (20, 50),
    "swing": (50, 200),
}

# v0.0.21: context cache — BTC/dominance data changes slowly.
_context_cache: dict = {"ts": 0.0, "data": {}}
CONTEXT_CACHE_TTL = int(os.getenv("VAISRAVANA_CONTEXT_CACHE_TTL", "300"))  # 5 min
#   TFS          = structural contexts (default 5m,15m) that feed htf_bias / mtf_aligned,
#                  making the existing 7-factor engine multi-timeframe WITHOUT engine edits.
DECISION_TF = os.getenv("VAISRAVANA_DECISION_TF", "1m")
TFS = os.getenv("VAISRAVANA_TFS", "5m,15m").split(",")
# v0.0.10: concurrent multi-strategy. The default scalping DECISION_TF (1m) drives the
# scalping profile; Day=15m and Swing=1h profiles run in parallel. Each strategy's own
# decision_tf is taken from its StrategyProfile, NOT this global, so the three horizons
# are genuinely independent (and the (pair, decision_tf, side) key keeps them apart).
PROFILES = default_profiles()
ACTIVE_PROFILES = active_strategies()
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
    # v0.0.32: urlopen uses the process-wide proxy opener installed at import time
    # (no-op when HTTPS_PROXY/HTTP_PROXY is unset), so a VPS behind a proxy reaches
    # Binance. Falls back naturally when no proxy is configured.
    raw = json.loads(urllib.request.urlopen(url, timeout=15).read().decode())
    return [Candle(ts=r[0], o=float(r[1]), h=float(r[2]), l=float(r[3]),
                   c=float(r[4]), v=float(r[5]),
                   tb=float(r[9]) if len(r) > 9 else 0.0) for r in raw]


def fetch_spread_bps(symbol: str) -> float | None:
    """v0.0.34: REAL bid/ask spread from the book ticker (instrumentation fix —
    the first run stored a hardcoded spread_bps=1.0 on every trade). Called only
    on the entry path (max a few times/hour), never in the hot loop."""
    import urllib.request
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol={symbol}"
        d = json.loads(urllib.request.urlopen(url, timeout=8).read().decode())
        bid, ask = float(d["bidPrice"]), float(d["askPrice"])
        mid = (bid + ask) / 2.0
        if mid <= 0:
            return None
        return (ask - bid) / mid * 10000.0
    except Exception:
        return None


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
    bull = ema20 > ema50 * (1 + 0.0008)
    bear = ema20 < ema50 * (1 - 0.0008)
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


def _ema_cross(closes: list[float], fast: int = 20, slow: int = 50,
               tol: float = 0.0008) -> tuple[bool, bool]:
    """Return (bull, bear) from EMA fast vs slow cross.

    v0.0.21: configurable periods + unified tolerance 0.08%.
    Default 20/50 = ~50-bar signal (12.5h on 15m).
    Scalp uses 5/15 on 1m = ~15-bar signal (15 min — matches hold time).
    """
    if len(closes) < slow:
        return False, False
    e_fast = _ema(closes[-fast:], fast) if len(closes) >= fast else _ema(closes, fast)
    e_slow = _ema(closes, slow)
    return e_fast > e_slow * (1 + tol), e_fast < e_slow * (1 - tol)


def build_state_mtf(pair: str, dec_candles: list[Candle], i: int,
                     contexts: dict[str, list[Candle]],
                     ema_fast: int = 20, ema_slow: int = 50) -> MarketState:
    """Phase 12 — time-sensitive decision state.

    v0.0.21: profile-specific EMA periods. Scalp (1m) uses 5/15 for ~15-min
    signal that matches its 15-min hold window. Day (15m) uses 20/50 (12.5h).
    Swing (1h) uses 50/200 (~200h).

    The decision TF bar drives the decision + act price. Structural TFs
    (contexts: {tf: candles}) set `htf_bias` (EMA cross) and `mtf_aligned`.
    """
    st = build_state(pair, DECISION_TF, dec_candles, i)
    bar = dec_candles[i]
    # 1m direction (for alignment)
    dec_bull, dec_bear = _ema_cross([c.c for c in dec_candles[max(0, i - 50): i + 1]],
                                    fast=5, slow=15)
    # pick the highest structural TF for htf_bias (or use dec candles with profile periods)
    htf_tf = max(contexts.keys(), key=lambda t: _tf_minutes(t)) if contexts else DECISION_TF
    htf = contexts.get(htf_tf) or dec_candles
    htf_bull, htf_bear = _ema_cross([c.c for c in htf[-(ema_slow + 20):]],
                                     fast=ema_fast, slow=ema_slow)
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
    """Build cross-asset + MTF context with caching (v0.0.21).

    BTC and dominance data change slowly; cache results for CONTEXT_CACHE_TTL.
    """
    global _context_cache
    now = time.time()
    # Check cache
    if now - _context_cache["ts"] < CONTEXT_CACHE_TTL and _context_cache["data"]:
        cached = _context_cache["data"]
        # Update per-pair MTF fields from current contexts (these change every tick)
        mtf_tf = max(contexts.keys(), key=_tf_minutes) if contexts else DECISION_TF
        mtf_htf = contexts.get(mtf_tf) or dec_candles
        ltf_bias = _ema_cross([c.c for c in dec_candles[max(0, i - 20): i + 1]],
                               fast=5, slow=15)
        mtf_bias = _ema_cross([c.c for c in mtf_htf[-(50 + 20):]], fast=20, slow=50)
        htf_bias = _bias_of(cached.get("htf_closes", []), 50)
        # Rebuild MTF fields
        ltf_b = "bullish" if ltf_bias[0] else ("bearish" if ltf_bias[1] else "neutral")
        mtf_b = "bullish" if mtf_bias[0] else ("bearish" if mtf_bias[1] else "neutral")
        htf_b = htf_bias
        biases = [b for b in (ltf_b, mtf_b, htf_b) if b != "neutral"]
        mtf_cf = len(biases) >= 2 and len(set(biases)) == 1
        pullback = _compute_pullback(ltf_b, htf_b, dec_candles, i,
                                     cached.get("pair_htf_closes", []))
        return MarketContext(
            btc_bias=cached.get("btc_bias", "neutral"),
            btc_ret=cached.get("btc_ret", 0.0),
            dominance_delta=cached.get("dom_delta", 0.0),
            risk_regime=cached.get("risk", "neutral"),
            alt_rs_btc=cached.get("alt_rs", 0.0),
            alt_breadth=cached.get("breadth", 0.5),
            ltf_bias=ltf_b, mtf_bias=mtf_b, htf_bias=htf_b,
            mtf_confluence=mtf_cf, pullback_to_anchor=pullback,
        )

    # ── Cache miss: fetch fresh data ─────────────────────
    ctx = _build_context_fresh(pair, dec_candles, i, contexts)
    return ctx


def _build_context_fresh(pair, dec_candles, i, contexts):
    """Fetch and cache fresh context data."""
    global _context_cache
    ctx = _build_context_raw(pair, dec_candles, i, contexts)
    # Cache the slow-changing fields
    _context_cache = {
        "ts": time.time(),
        "data": {
            "btc_bias": ctx.btc_bias,
            "btc_ret": ctx.btc_ret,
            "dom_delta": ctx.dominance_delta,
            "risk": ctx.risk_regime,
            "alt_rs": ctx.alt_rs_btc,
            "breadth": ctx.alt_breadth,
            "htf_closes": _get_htf_closes(pair, contexts),
            "pair_htf_closes": _get_pair_htf(pair, dec_candles, contexts),
        },
    }
    return ctx


def _get_htf_closes(pair, contexts):
    """Get BTC closes from the highest available context TF."""
    import src.marketdata as md  # noqa
    try:
        btc_tf = "1h" if "1h" in TFS else (max(TFS, key=_tf_minutes) if TFS else "15m")
        return [c.c for c in fetch_klines("BTCUSDT", btc_tf, 60)]
    except Exception:
        return []


def _get_pair_htf(pair, dec_candles, contexts):
    """Get the pair's HTF closes from context."""
    htf_tf = max(contexts.keys(), key=_tf_minutes) if contexts else DECISION_TF
    htf = contexts.get(htf_tf) or dec_candles
    return [c.c for c in htf]


def _compute_pullback(ltf_bias, htf_bias, dec_candles, i, pair_htf_closes):
    """Check if LTF retraced into HTF bias then resumed (pullback_to_anchor)."""
    if htf_bias == "neutral" or len(dec_candles) < 20:
        return False
    ltf_ret = (dec_candles[-1].c - dec_candles[max(0, i - 10)].c) / \
              (dec_candles[max(0, i - 10)].c or 1e-12)
    pair_ret = (pair_htf_closes[-1] - pair_htf_closes[max(0, len(pair_htf_closes) - 10)]) / \
               (pair_htf_closes[max(0, len(pair_htf_closes) - 10)] or 1e-12) if pair_htf_closes else 0.0
    if htf_bias == "bullish":
        return ltf_ret < 0 and pair_ret >= 0
    return ltf_ret > 0 and pair_ret <= 0


def _bias_of(closes: list[float], period: int = 50) -> str:
    """EMA20/50 bias with 0.08% tolerance."""
    if len(closes) < period:
        return "neutral"
    e20 = _ema(closes[-20:], 20)
    e50 = _ema(closes, period)
    if e20 > e50 * (1 + 0.0008):
        return "bullish"
    if e20 < e50 * (1 - 0.0008):
        return "bearish"
    return "neutral"


def _build_context_raw(pair: str, dec_candles: list[Candle], i: int,
                        contexts: dict[str, list[Candle]]) -> MarketContext:
    """Original context builder (uncached) — used on cache miss."""
    from marketcontext import build_context, ContextSeries

    def get(sym: str, tf: str, n: int = 60) -> list[float]:
        try:
            cs = fetch_klines(sym, tf, n)
            return _closes(cs)
        except Exception:
            return []

    btc_tf = "1h" if "1h" in TFS else (max(TFS, key=_tf_minutes) if TFS else "15m")
    btc = get("BTCUSDT", btc_tf)
    basket = [get(p, btc_tf) for p in PAIRS if p != pair]
    basket = [b for b in basket if len(b) >= 50]
    pair_htf = get(pair, btc_tf)
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


def _persist_decisions_log(conn, pair, tf, state, se, decision, reason=None):
    """Persist one evaluated decision (WATCH/SKIP/SUPPRESSED/ENTRY) to decisions_log.

    Best-effort: a logging failure must never break the decision loop. Reads regime/scores
    from the MarketState and score/confidence from the StrategyEntry via getattr fallbacks
    so it stays robust to schema drift.
    """
    try:
        import json as _json
        scores = getattr(state, "scores", None) or getattr(se, "sub_scores", None)
        if scores is not None:
            # scores may be a dataclass/object with as_dict(), or a dict — serialize safely
            if hasattr(scores, "as_dict"):
                scores_json = _json.dumps(scores.as_dict())
            else:
                try:
                    scores_json = _json.dumps(scores)
                except TypeError:
                    scores_json = _json.dumps(str(scores))
        else:
            scores_json = None
        conn.execute(
            "INSERT INTO decisions_log "
            "(id, correlation_id, ts, pair, tf, regime, scores_json, total_score, "
            "confidence_pct, decision, gate_a_pass, gate_b_pass, reason, config_ver, side) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"{pair}-{tf}-{int(time.time()*1000)}-{getattr(se,'side','')}",
             f"{pair}-{tf}",
             datetime.now(timezone.utc).isoformat(),
             pair, tf,
             getattr(state, "regime", None),
             scores_json,
             getattr(se, "chosen_score", None),
             getattr(se, "confidence_pct", None),
             decision, 1, 1, reason,
             vmod.read_version(),
             getattr(se, "side", None)),
        )
        conn.commit()
    except Exception as e:  # never let a log write break the loop
        log.debug("persist decisions_log failed: %s", e)


def run() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    conn = init_db(DB_PATH)
    # v0.0.10: on boot, immediately trim decisions_log older than 1 day so a long-lived
    # or restarted bot never lets the spammy audit table grow unbounded.
    try:
        db.purge_old_decisions(conn)
    except Exception as e:  # non-fatal — never block boot on housekeeping
        log.debug("boot decisions_log purge skipped: %s", e)
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

    # v0.0.21: register bot commands so / shows a hint list in Telegram
    notifier.register_commands()
    # --- HARD mode boundary (doc 30 §6/§7): structurally impossible to trade live
    # without human approval. PAPER (default) only ever drives a simulated exchange.
    mode = os.getenv("VAISRAVANA_MODE", "paper").lower()
    if mode not in ("paper", "live"):
        raise SystemExit(f"VAISRAVANA_MODE must be 'paper' or 'live', got {mode!r}")
    guard = ModeGuard(mode=mode)  # live_exchange=None in paper -> PaperSimExchange
    exchange = guard.exchange_for(None)  # PaperSimExchange in paper; GuardedExchange in live
    monitor = PositionMonitor(exchange, clock=time.time)
    # v0.0.23 T2: data-driven pair exclusion (doc 45 §3). Persisted to the data dir
    # (default ./data, portable; on Fly set VAISRAVANA_EXCLUSIONS=/data/exclusions.json).
    # Pairs with rolling WR < 40% over >=10 trades are skipped until they recover >= 50%.
    from pair_excluder import PairExcluder
    excluder = PairExcluder(os.getenv("VAISRAVANA_EXCLUSIONS",
                                       os.path.join(_DATA_DIR, "exclusions.json")))
    # v0.0.23 T3: track BUY/SELL entry share; nudge SELL threshold down
    # (never below watch) when SELL is structurally suppressed (< 25%).
    from side_balancer import SideBalancer
    side_balancer = SideBalancer()
    # v0.0.24 P0-30: boot R:R floor self-check. Flag any OPEN trade whose realized
    # R:R < 2:1. Does NOT mutate live positions; alerts + blocks that pair from NEW
    # entries until repaired. A transient sub-2:1 entry must never ship undetected
    # (the 2026-07-27 BTCUSDT 1m 1.50:1 case proved the class exists).
    from rr_scan import scan_open_rr, FLOOR as RR_FLOOR
    rr_violations = []
    try:
        rr_violations = scan_open_rr(conn, RR_FLOOR)
    except Exception as e:  # never block boot on the scan itself
        log.debug("R:R floor scan skipped: %s", e)
    rr_blocked_pairs: set[str] = set()
    if rr_violations:
        rr_blocked_pairs = {v["pair"] for v in rr_violations}
        vlist = ", ".join(f"{v['pair']} {v['tf']} {v['side']} R:R={v['rr']}" for v in rr_violations)
        log.warning("R:R floor violations among open trades: %s", vlist)
        try:
            notifier.send_message(
                f"⚠️ **Vessavaṇa — R:R floor alert**\nAturan owner 2:1 dilanggar pada posisi terbuka:\n"
                f"`{vlist}`\nPair diblokir dari entri BARU hingga diperbaiki (posisi tetap).")
        except Exception:
            pass
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

    # v0.1.1: Wave Engine moved to its own repo (hernanda-git/vaisravana-wave).
    # This repo is the MAIN bot only; VAISRAVANA_ENGINE=wave is no longer valid here.
    engine = os.getenv("VAISRAVANA_ENGINE", "legacy").lower()
    if engine == "wave":
        raise SystemExit(
            "VAISRAVANA_ENGINE=wave is not supported in this repo anymore. "
            "The wave engine lives in hernanda-git/vaisravana-wave (deployed as "
            "the bots-vaisravana-wave container). Unset VAISRAVANA_ENGINE or use 'legacy'."
        )
    # Phase 13: clean startup card (Bahasa Indonesia, brand Vessavaṇa)
    notifier.notify_startup(ver, PAIRS, DECISION_TF, TFS, CYCLE_S, LLM_MODE, len(open_trades))
    # announce the deployed version + what changed on every (re)start
    notifier.notify_deploy(ver, vmod.latest_changelog())
    # doc 43: explicit on-deploy health check so the owner can confirm liveness
    # without waiting for a trade. UTC region from fly.toml primary_region.
    region = os.getenv("FLY_REGION", os.getenv("VAISRAVANA_REGION", "sin"))
    notifier.notify_health_check(ver, region, len(open_trades), feed_ok=True)
    # doc 43: DB awareness on boot -> overall win rate + row counts + on-disk size,
    # so the owner immediately sees database growth without waiting for the 30m cycle.
    try:
        notifier.notify_db_stats(ver, db_stats(conn, DB_PATH))
    except Exception as e:  # never let a stats card break boot
        log.debug("db_stats card failed: %s", e)

    # Phase 11: start the offline LLM research loop (propose-only Sentinel).
    # Default OFF -> bot is 100% deterministic, identical to before.
    if LLM_MODE != "off" and ZEN_API_KEY:
        research = threading.Thread(
            target=research_loop, args=(notifier,), daemon=True)
        research.start()
    elif LLM_MODE != "off" and not ZEN_API_KEY:
        log.warning("VAISRAVANA_LLM=%s but ZEN_API_KEY unset — research disabled", LLM_MODE)

    last_status = 0.0
    # v0.0.10: the unique decision timeframes actually used by active strategies, so we
    # fetch each only once per pair per cycle (scalp=1m, day=15m, swing=1h default).
    decision_tfs = sorted({p.decision_tf for p in ACTIVE_PROFILES}, key=_tf_minutes)

    # v0.0.16 /owner: `/clean` slash command — wipe DB + clear ALL cooldown/loss/kill state
    # and start the trading loop fresh (blank win rate, no open positions). Defined as a
    # closure so it captures every live state holder. Owner-only (chat-gated in the listener).
    control = {"stop": False}

    # v0.0.19: post-SL cooldown tracker {(pair, side): ticks_remaining}
    cooldowns: dict[tuple[str, str], int] = {}
    # v0.0.19: pair ATR tracker for volatility-adaptive SL
    pair_atr: dict[str, float] = {}

    # v0.0.19: pair-level weights — reduce sizing on consistently losing pairs
    # (calibrated from live data: SOL/WLD/BONK/ETH/TAAO/BTC all <25% WR)
    PAIR_WEIGHTS.clear()
    _weak = os.getenv("VAISRAVANA_WEAK_PAIRS", "SOLUSDT,WLDUSDT,1000BONKUSDT,ETHUSDT")
    for _p in PAIRS:
        if _p in _weak.split(","):
            PAIR_WEIGHTS[_p] = 0.5
    _below = os.getenv("VAISRAVANA_BELOW_AVG_PAIRS", "TAOUSDT,BTCUSDT,PUMPUSDT")
    for _p in PAIRS:
        if _p in _below.split(","):
            PAIR_WEIGHTS[_p] = PAIR_WEIGHTS.get(_p, 0.6)

    def clean_state() -> int:
        deleted = db.wipe_db(conn)
        # clear in-memory state so the next loop iteration is a true fresh start
        open_trades.clear()
        monitor.positions.clear()
        if hasattr(exchange, "_prices"):
            exchange._prices.clear()
        kill._cooldowns.clear()
        kill._streaks.clear()
        kill.reset()
        realized_loss_today["usd"] = 0.0
        realized_loss_today["day"] = time.strftime("%Y-%m-%d")
        reset = getattr(decider, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                pass
        # clear the caretaker cron deploy-cooldown so it may re-tune immediately
        try:
            CRON_STATE_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            stats = db_stats(conn, DB_PATH)
            notifier.send_message(
                f"🧼 <b>Vessavaṇa — DB dibersihkan & restart fresh</b>\n"
                f"Baris dihapus: <code>{deleted}</code>\n"
                f"Win rate: <code>reset (0 trade)</code>\n"
                f"Cooldown/kill-switch/loss di-clear.\n"
                f"Mulai fresh — posisi terbuka: <code>0</code>.")
        except Exception as e:
            log.debug("clean confirmation card failed: %s", e)
        log.info("owner /clean: wiped %d rows; all cooldown/loss/kill state cleared", deleted)
        # v0.0.19: also clear cooldowns + pair_atr
        cooldowns.clear()
        pair_atr.clear()
        return deleted

    def stop_bot() -> None:
        control["stop"] = True
        try:
            notifier.send_message("🛑 <b>Vessavaṇa dihentikan</b> (owner /stop).\n"
                                   "Loop akan berhenti di akhir siklus ini. Kirim /clean atau "
                                   "restart machine untuk memulai lagi.")

        except Exception as e:
            log.debug("stop card failed: %s", e)
        log.info("owner /stop requested")

    def health_report() -> None:
        try:
            summary = db.trade_summary(conn, recent_n=10)
            stats = db_stats(conn, DB_PATH) if "db_stats" in globals() else None
            notifier.notify_health(vmod.read_version(), summary, stats,
                                    control_state="STOPPED" if control["stop"] else "RUNNING")
        except Exception as e:
            log.exception("health report failed: %s", e)

    def _dispatch(text: str, _raw: str) -> None:
        cmd = text.split()[0].split("@")[0].lower()
        args = text.split()[1:] if len(text.split()) > 1 else []
        if cmd == "/clean":
            clean_state()
        elif cmd == "/stop":
            stop_bot()
        elif cmd == "/status":
            health_report()
        elif cmd == "/health":
            # legacy alias; the other bot (xvalarion) owns /health now.
            health_report()
        elif cmd == "/positions":
            _send_positions()
        elif cmd == "/pairs":
            _send_pairs()
        elif cmd == "/config":
            _send_config()
        elif cmd == "/exclude":
            _toggle_pair(args[0].upper(), exclude=True) if args else \
                notifier.send_message("Usage: /exclude BTCUSDT")
        elif cmd == "/include":
            _toggle_pair(args[0].upper(), exclude=False) if args else \
                notifier.send_message("Usage: /include BTCUSDT")
        elif cmd == "/reload":
            nonlocal surface
            try:
                # v0.0.33: `surface` module never existed — reload via load_surface()
                surface = load_surface()
                notifier.send_message("✅ Config reloaded from disk")
            except Exception as e:
                notifier.send_message(f"❌ Reload failed: {e}")
        elif cmd == "/decisions":
            try:
                n = int(args[0]) if args and args[0].isdigit() else 25
            except ValueError:
                n = 25
            _send_decisions(n)
        elif cmd in ("/wave", "/surf"):
            # wave engine moved to hernanda-git/vaisravana-wave (@wave_vaisravana_bot)
            notifier.send_message(
                "Wave engine sekarang bot terpisah: gunakan @wave_vaisravana_bot."
            )
        # unknown commands are ignored

    def _send_decisions(limit: int = 25) -> None:
        """Owner /decisions: pull recent GATED/WATCH/SKIP rows from decisions_log (DB-only audit)."""
        try:
            rows = conn.execute(
                "SELECT pair, tf, side, decision, total_score, reason "
                "FROM decisions_log "
                "WHERE decision IN ('GATED','WATCH','SKIP') "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except Exception as e:
            notifier.send_message(f"❌ /decisions query failed: {e}")
            return
        if not rows:
            notifier.send_message("📭 No decisions logged in the last 7d.")
            return
        tf_profile = {"1m": "scalping", "15m": "day", "1h": "swing"}
        lines = [f"👁 <b>Decisions</b> (last {len(rows)} from DB)"]
        for r in rows[:25]:
            p = r["pair"]; tf = r["tf"]; side = r["side"] or "—"
            dec = r["decision"]; score = r["total_score"]; reason = r["reason"]
            strat = tf_profile.get(tf, tf)
            why = f" — {reason}" if reason else ""
            lines.append(f"• <code>{p} {tf}</code> {side} [{strat}] {dec} {score}{why}")
        notifier.send_message("\n".join(lines))

    def _send_positions() -> None:
        """Send list of open positions."""
        rows = conn.execute(
            "SELECT pair, tf, side, entry_price, sl_price, tp_price, ts_opened "
            "FROM trade_logs WHERE ts_closed IS NULL"
        ).fetchall()
        if not rows:
            notifier.send_message("📭 No open positions.")
            return
        lines = ["<b>📊 Open Positions</b>"]
        for r in rows:
            side_icon = "🟢" if r["side"] == "BUY" else "🔴"
            hold = (datetime.now(timezone.utc) - datetime.fromisoformat(r["ts_opened"])).total_seconds() / 60
            lines.append(
                f"{side_icon} {r['pair']} | {r['side']} | {r['tf']}\n"
                f"   Entry: {r['entry_price']:.2f} | SL: {r['sl_price']:.2f} | TP: {r['tp_price']:.2f}\n"
                f"   Hold: {hold:.0f}m"
            )
        notifier.send_message("\n".join(lines[:10]))  # max 10 positions per msg

    def _send_pairs() -> None:
        """Send active pairs with weights."""
        lines = ["<b>📋 Active Pairs</b>"]
        for p in PAIRS:
            w = PAIR_WEIGHTS.get(p, 1.0)
            buy_wr = conn.execute(
                "SELECT ROUND(100.0*SUM(win)/COUNT(*),1) FROM trade_logs "
                "WHERE pair=? AND side='BUY' AND ts_closed IS NOT NULL"
            ).fetchone()[0] or 0
            sell_wr = conn.execute(
                "SELECT ROUND(100.0*SUM(win)/COUNT(*),1) FROM trade_logs "
                "WHERE pair=? AND side='SELL' AND ts_closed IS NOT NULL"
            ).fetchone()[0] or 0
            icon = "✅" if w >= 1.0 else "⚠️" if w >= 0.6 else "🔻"
            lines.append(f"{icon} {p} w={w:.2f}  🟢{buy_wr}%  🔴{sell_wr}%")
        notifier.send_message("\n".join(lines))

    def _send_config() -> None:
        """Send current surface parameters."""
        from config import Weights
        w = surface.weights
        lines = [
            "<b>⚙️ Config</b>",
            f"Entry threshold: {surface.entry_threshold}",
            f"Watch threshold: {surface.watch_threshold}",
            f"Weights: T={w.trend} M={w.momentum} V={w.volume} S={w.structure} "
            f"L={w.liquidity} A={w.atr} F={w.funding_oi}",
            f"Daily loss limit: {surface.daily_loss_limit_pct}%",
            f"Max live pairs: {surface.global_max_live_pairs}",
            f"Mode: {mode.upper()} | Pairs: {len(PAIRS)}",
        ]
        notifier.send_message("\n".join(lines))

    def _toggle_pair(pair: str, exclude: bool) -> None:
        """Exclude or include a trading pair."""
        if pair not in PAIRS:
            notifier.send_message(f"❌ Unknown pair: {pair}")
            return
        action = "excluded from" if exclude else "included in"
        PAIR_WEIGHTS[pair] = 0.0 if exclude else 1.0
        notifier.send_message(f"✅ {pair} {action} trading. Weight: {PAIR_WEIGHTS[pair]:.1f}")

    # v0.0.22: add necessary imports for command handlers
    from datetime import datetime, timezone

    while True:
        try:
            # owner /stop: graceful halt at the end of the current cycle
            if control["stop"]:
                log.info("owner /stop: loop exiting")
                notifier.send_message("✅ Vessavaṇa berhenti. (process exit)")
                break
            today = time.strftime("%Y-%m-%d")
            if realized_loss_today["day"] != today:
                realized_loss_today = {"usd": 0.0, "day": today}
                kill.reset()  # fresh day -> clear any tripped kill-switch
                # v0.0.10: prune the spammy decisions_log (>1 day old) at the daily roll
                try:
                    deleted = db.purge_old_decisions(conn)
                    if deleted:
                        notifier.send_message(
                            f"🧹 **Vessavaṇa — DB prune**\n"
                            f"decisions_log >1d dihapus: <code>{deleted}</code> baris")
                except Exception as e:  # never let pruning break the loop
                    log.debug("decisions_log purge failed: %s", e)
            daily_loss_pct = (realized_loss_today["usd"] / equity * 100.0) if equity else 0.0
            # v0.0.34: LIVE paper equity drives sizing. The first run sized
            # against the static env equity ($1000) while the paper account
            # held $10 — producing $956-notional ETH entries. Refresh from the
            # DB each cycle; fall back to the env seed only if the read fails.
            try:
                _ps = paper_stats(conn, start_balance=START_BALANCE, fee_rate=FEE_RATE)
                equity = max(float(_ps["balance"]), 0.0)
            except Exception as _e:
                log.debug("live equity refresh failed: %s", _e)
            # mark feed health from the latest candle we just fetched
            for pair in PAIRS:
                for tf in decision_tfs + TFS:
                    feed.mark(pair, tf, int(time.time() * 1000))
            feed_frozen = bool(feed.frozen_list(PAIRS, decision_tfs + TFS))
            cycle_decisions: list = []  # v0.0.16: batch WATCH/SUPPRESS cards into 1/cycle
            for pair in PAIRS:
                # v0.0.10: fetch all decision TFs + structural contexts ONCE per pair,
                # cache them, and hand the cache to _decide_tick so each strategy reads
                # its own decision_tf without re-fetching.
                klines_cache: dict[str, list] = {}
                need = list(decision_tfs) + list(TFS)
                for tf in need:
                    try:
                        cs = fetch_klines(pair, tf, FETCH_LIMIT)
                    except Exception:
                        cs = []
                    klines_cache[tf] = cs
                _decide_tick(pair, conn, surface, lc, tel, kill, decider,
                             notifier, open_trades, registry=registry,
                             daily_loss_pct=daily_loss_pct, feed_frozen=feed_frozen,
                             equity=equity, loss_book=realized_loss_today,
                             monitor=monitor, exchange=exchange, guard=guard,
                             klines_cache=klines_cache, decision_sink=cycle_decisions,
                             cooldowns=cooldowns, pair_atr=pair_atr, excluder=excluder,
                             side_balancer=side_balancer, rr_blocked_pairs=rr_blocked_pairs)
                # push the latest price into the sim exchange so the monitor's
                # mark-price SL/TP/orphan/maxhold logic is real (doc 30 §3, doc 32 L4)
                _last_decs = klines_cache.get(DECISION_TF) or []
                if _last_decs:
                    exchange.set_price(pair, _last_decs[-1].c)
                # v0.0.19: track per-pair ATR for volatility-adaptive SL
                _tf1 = klines_cache.get(DECISION_TF)
                if _tf1 and len(_tf1) >= 14:
                    tr = [max(c.h - c.l, abs(c.h - c.c), abs(c.l - c.c)) for c in _tf1[-14:]]
                    pair_atr[pair] = sum(tr) / len(tr) / (_tf1[-1].c or 1) * 100.0
            # drive the position monitor every cycle (real SL/maxhold/orphan handling)
            for ev in monitor.tick():
                t = open_trades.pop((ev.symbol, ev.tf, ev.side), None)
                if t is None:
                    continue
                # v0.0.34: maker on open (post-only entry), taker on close.
                notional = (t.entry_price or 0.0) * (t.size or 0.0)
                fee_usd = (FEE_RATE_MAKER * (t.entry_price or 0.0)
                           + FEE_RATE * ev.price) * (t.size or 0.0)
                _exc = EXCURSIONS.pop(t.correlation_id, None)
                res = lc.close(t, exit_price=ev.price, close_reason=ev.reason,
                               fees_usd=fee_usd,
                               mfe_r=(_exc[0] if _exc else None),
                               mae_r=(_exc[1] if _exc else None))
                kill.record_close(ev.symbol, ev.tf, ev.side, win=bool(res["win"]))
                _record_loss_streak(bool(res["win"]))
                if realized_loss_today is not None and res["pnl_usd"] < 0:
                    realized_loss_today["usd"] += -res["pnl_usd"]
                tel.exec_event(t.correlation_id, ev.symbol, DECISION_TF, "CLOSE",
                               side=ev.side, price=ev.price, status=ev.reason)
                _net = res["pnl_usd"] - fee_usd
                _get_mark = (lambda p: exchange.mark_price(p)) if exchange else None
                _stats = paper_equity(conn, open_trades, _get_mark)
                notifier.notify_close(ev.symbol, DECISION_TF, ev.side, ev.price,
                                      ev.reason, res["r_multiple"], bool(res["win"]),
                                      fee_usd=fee_usd, net_usd=_net, stats=_stats)
                # v0.0.19: post-SL cooldown — skip next N entries on (pair, side) after SL
                if ev.reason == "SL":
                    cd_key = (ev.symbol, ev.side)
                    cooldowns[cd_key] = SL_COOLDOWN_TICKS
                    log.debug("SL cooldown %s: %d ticks", cd_key, SL_COOLDOWN_TICKS)
            # v0.0.19: trailing stop — if a trade reaches +0.5R, move SL to break-even
            for (sym, tf_, side_), trade in list(open_trades.items()):
                price = getattr(exchange, '_prices', {}).get(sym)
                if price is None:
                    continue
                unrealized_r = (price - trade.entry_price) / abs(trade.entry_price - trade.sl_price) \
                    if trade.side == "BUY" else (trade.entry_price - price) / abs(trade.entry_price - trade.sl_price)
                # v0.0.34: excursion tracking — persist real MFE/MAE at close
                # (instrumentation fix: both columns were NULL all of run 1).
                _exc = EXCURSIONS.get(trade.correlation_id)
                if _exc is not None:
                    _exc[0] = max(_exc[0], unrealized_r)
                    _exc[1] = min(_exc[1], unrealized_r)
                old_sl = trade.sl_price
                if trade.side == "BUY" and unrealized_r >= BE_TRAIL_ARM_R and old_sl < trade.entry_price:
                    new_sl = trade.entry_price * 0.9999  # very slight buffer
                    if monitor is not None:
                        for pos in monitor.positions.values():
                            if pos.correlation_id == trade.correlation_id:
                                pos.sl.stop_price = new_sl
                                break
                    trade.sl_price = new_sl
                    log.debug("trailing SL %s %s moved to BE (R=%.2f)", sym, side_, unrealized_r)
                elif trade.side == "SELL" and unrealized_r >= BE_TRAIL_ARM_R and old_sl > trade.entry_price:
                    new_sl = trade.entry_price * 1.0001
                    if monitor is not None:
                        for pos in monitor.positions.values():
                            if pos.correlation_id == trade.correlation_id:
                                pos.sl.stop_price = new_sl
                                break
                    trade.sl_price = new_sl
                    log.debug("trailing SL %s %s moved to BE (R=%.2f)", sym, side_, unrealized_r)
            # v0.0.19: decrement cooldowns each cycle
            expired = [k for k, v in cooldowns.items() if v <= 1]
            for k in expired:
                del cooldowns[k]
            for k in list(cooldowns.keys()):
                if k not in expired:
                    cooldowns[k] -= 1
            # v0.0.29: decision audit is DB-only — the per-cycle 👁 card is disabled to stop
            # spam. Pull the recent GATED/near-threshold rows on demand with /decisions.
            # `cycle_decisions` is still collected as the decision_sink audit trail (not sent).
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
                loss_book=None, monitor=None, exchange=None, guard=None,
                klines_cache=None, decision_sink=None, cooldowns=None, pair_atr=None,
                excluder=None, side_balancer=None, rr_blocked_pairs=None):
    """Phase 12 — time-sensitive decision tick.

    v0.0.19: +cooldowns (post-SL cooldown dict), +pair_atr (volatility-adaptive SL).

    `decision_sink` (optional list): when provided, WATCH/near-threshold decisions are
    appended for a single batched per-cycle card instead of one Telegram message per
    pair×strategy per tick (prevents the WATCH spam).
    """
    cooldowns = cooldowns or {}
    pair_atr = pair_atr or {}
    cache = klines_cache or {}
    # v0.0.23 T2: skip excluded pairs entirely (no kline fetch, no decision).
    if excluder is not None and excluder.is_excluded(pair):
        log.debug("pair %s excluded by rolling WR < floor; skipping tick", pair)
        return
    # v0.0.24 P0-30: skip pairs Blocked by the boot R:R-floor self-check (no NEW
    # entries until the open sub-2:1 position is repaired). Open positions stay.
    if rr_blocked_pairs and pair in rr_blocked_pairs:
        log.debug("pair %s R:R-floor blocked (open sub-2:1); skipping new entries", pair)
        return
    for profile in ACTIVE_PROFILES:
        dtf = profile.decision_tf
        dec = cache.get(dtf)
        if dec is None or len(dec) < 60:
            continue
        contexts = {tf: cache[tf] for tf in TFS
                    if tf in cache and tf != dtf and len(cache[tf]) >= 50}
        i = len(dec) - 1

        # ── v0.0.22: compute ADX once ────────────────────────
        adx_tf = max(contexts.keys(), key=_tf_minutes) if contexts else dtf
        adx_candles = cache.get(adx_tf) or dec
        adx_v = compute_adx(adx_candles, period=14)
        adx_ok, adx_reason = adx_allowed(adx_v, threshold=ADX_MIN)

        # ── state + context ───────────────────────────────────
        ema_fast, ema_slow = PROFILE_EMA.get(profile.name, (20, 50))
        state = build_state_mtf(pair, dec, i, contexts, ema_fast=ema_fast, ema_slow=ema_slow)
        try:
            ctx = build_context_for(pair, dec, i, contexts)
            state.btc_bias = ctx.btc_bias
            state.btc_ret = ctx.btc_ret
            state.risk_regime = ctx.risk_regime
            state.alt_rs_btc = ctx.alt_rs_btc
            state.alt_breadth = ctx.alt_breadth
            state.ltf_bias = ctx.ltf_bias
            state.mtf_bias = ctx.mtf_bias
            state.htf_bias2 = ctx.htf_bias
            state.mtf_confluence = ctx.mtf_confluence
            state.pullback_to_anchor = ctx.pullback_to_anchor
        except Exception as exc:
            log.debug("context build failed for %s/%s: %s", pair, dtf, exc)

        # ── v0.0.22: adaptive weights ────────────────────────
        from engines import adaptive_weights

        if surface is not None:
            aw = adaptive_weights(adx_v, state.regime)
            surface.weights.trend = aw["trend"]
            surface.weights.momentum = aw["momentum"]
            surface.weights.volume = aw["volume"]
            surface.weights.structure = aw["structure"]
            surface.weights.liquidity = aw["liquidity"]
            surface.weights.atr = aw["atr"]
            surface.weights.funding_oi = aw["funding_oi"]

        se = evaluate_strategy(profile, state, entry_price=dec[i].c,
                               atr=(dec[i].c * state.atr_pct),
                               surface=surface)
        t = open_trades.get((pair, dtf, "BUY")) or open_trades.get((pair, dtf, "SELL"))
        if t is not None:
            bar = dec[i]
            hit_tp = (t.side == "BUY" and bar.h >= t.tp_price) or \
                     (t.side == "SELL" and bar.l <= t.tp_price)
            hit_sl = (t.side == "BUY" and bar.l <= t.sl_price) or \
                     (t.side == "SELL" and bar.h >= t.sl_price)
            if hit_tp:
                _close(pair, dtf, t.side, t.tp_price, "TP", conn, lc, tel, kill,
                       notifier, open_trades, loss_book=loss_book, excluder=excluder,
                       exchange=exchange)
            elif hit_sl:
                _close(pair, dtf, t.side, t.sl_price, "SL", conn, lc, tel, kill,
                       notifier, open_trades, loss_book=loss_book, excluder=excluder,
                       exchange=exchange)
            # v0.0.35: signal-flip exit — engine now signals a full ENTRY on the
            # OPPOSITE side while we hold. Exit at market instead of riding to
            # SL (run-1 losers averaged -1R by waiting for the stop). Pattern
            # validated in ajidwip/ai-trading-sequence-5m ("AI_REVERSE" exits).
            elif (SIGNAL_FLIP_EXIT and se.decision == "ENTRY"
                  and se.side != t.side):
                log.info("signal-flip exit %s %s: engine flipped to %s ENTRY "
                         "(score %.2f)", pair, t.side, se.side, se.chosen_score)
                _close(pair, dtf, t.side, bar.c, "FLIP", conn, lc, tel, kill,
                       notifier, open_trades, loss_book=loss_book, excluder=excluder,
                       exchange=exchange)
            continue  # this strategy already has a position; move to the next profile

        # kill-switch gate (real daily-loss + feed-health, doc 30 §7) — checked once per tick
        if profile is ACTIVE_PROFILES[0]:
            tripped, kreason = kill.check_global(daily_loss_pct=daily_loss_pct,
                                                 adl_rank=1, feed_frozen=feed_frozen)
            if tripped:
                tel.health("kill_switch", "FAIL", detail=kreason)
                # v0.0.25: de-dupe — alert ONCE per trip (then at most every 30m
                # while still tripped). Prevents the kill-switch spamming the
                # channel every tick. The halt itself still applies every tick.
                if kill.alert_due():
                    notifier.notify_kill_switch(kreason)
                return

        # decide under THIS strategy's profile (own entry bar + SL/TP mults)
        se = evaluate_strategy(profile, state, entry_price=dec[i].c,
                               atr=(dec[i].c * state.atr_pct), surface=surface)

        # ── v0.0.19: post-SL cooldown ──────────────────────────
        cd_key = (pair, se.side)
        if cooldowns.get(cd_key, 0) > 0:
            _persist_decisions_log(conn, pair, dtf, state, se, "SKIP",
                                   reason=f"post-SL cooldown {cooldowns[cd_key]} tick(s)")
            continue

        if se.decision == "ENTRY" and not adx_ok:
            if decision_sink is not None:
                decision_sink.append((pair, dtf, profile.name, se.side,
                                      round(se.chosen_score, 3), "GATED"))
            else:
                notifier.notify_decision(pair, dtf, "SKIP", se.chosen_score,
                                         se.side, adx_reason)
            _persist_decisions_log(conn, pair, dtf, state, se, "GATED", reason=adx_reason)
            continue

        # ── v0.0.19: per-side entry threshold adjustment ────────
        # BUY needs higher threshold in non-bull regime; SELL needs higher in bull regime.
        bull = (getattr(state, "htf_bias", "neutral") == "bullish"
                or getattr(state, "btc_bias", "neutral") == "bullish"
                or getattr(state, "risk_regime", "neutral") == "bullish")
        # v0.0.19: per-side entry threshold adjustment — BUY needs higher
        # threshold in non-bull regime; SELL needs higher in bull regime.
        # v0.0.23 T3: also nudge SELL down when structurally suppressed
        # (< 25% share) so we don't fight the profitable short side.
        effective_threshold = profile.entry_threshold
        if se.side == "BUY" and not bull:
            effective_threshold = min(profile.entry_threshold + SIDE_THRESHOLD_ADJ, 0.92)
        elif se.side == "SELL" and bull:
            effective_threshold = min(profile.entry_threshold + SIDE_THRESHOLD_ADJ, 0.92)
        elif se.side == "SELL" and side_balancer is not None:
            effective_threshold = side_balancer.sell_threshold(
                profile.entry_threshold, profile.watch_threshold)

        # Re-check effective threshold if the base score was ENTRY
        if se.decision == "ENTRY" and se.chosen_score < effective_threshold:
            if decision_sink is not None and se.chosen_score >= profile.entry_threshold - 0.06:
                decision_sink.append(
                    (pair, dtf, profile.name, se.side, round(se.chosen_score, 3),
                     round(effective_threshold, 3)))
            elif decision_sink is None:
                # downgrade to WATCH only if score still above watch bar
                lowered_profile = profile.entry_threshold - 0.06
                tag = "WATCH" if se.chosen_score >= lowered_profile else "SKIP"
                notifier.notify_decision(pair, dtf, tag, se.chosen_score,
                                         se.side, f"side-threshold {effective_threshold}")
            _persist_decisions_log(conn, pair, dtf, state, se, "GATED",
                                   reason=f"per-side threshold {effective_threshold}")
            continue

        if se.decision != "ENTRY":
            if se.decision == "WATCH":
                # v0.0.16: batch WATCHs into ONE per-cycle card (no spam). Only keep
                # near-threshold rows (within 0.06 of the bar) — they're the informative ones.
                if decision_sink is not None and se.chosen_score >= profile.entry_threshold - 0.06:
                    decision_sink.append(
                        (pair, dtf, profile.name, se.side, round(se.chosen_score, 3),
                         round(profile.entry_threshold, 3)))
                elif decision_sink is None:
                    notifier.notify_decision(pair, dtf, "WATCH", se.chosen_score,
                                             se.side, f"{profile.name} below threshold")
            # v0.0.17: persist every evaluated decision (WATCH or SKIP) to decisions_log
            _persist_decisions_log(conn, pair, dtf, state, se, se.decision)
            continue

        # v0.0.18: directional + expectancy entry gate (the core WR fix). Replaces the
        # weaker v0.0.16 side-bleed gate with a full regime + pullback filter.
        sc, sexp = lc.side_expectancy(se.side)
        allowed, reason = entry_allowed(state, se.side, sc, sexp)
        if not allowed:
            if decision_sink is not None:
                decision_sink.append((pair, dtf, profile.name, se.side,
                                      round(se.chosen_score, 3), "GATED"))
            else:
                notifier.notify_decision(pair, dtf, "SKIP", se.chosen_score,
                                         se.side, reason)
            # v0.0.17: persist the GATED decision so the audit trail is complete
            _persist_decisions_log(conn, pair, dtf, state, se, "GATED", reason=reason)
            continue

        # v0.0.17: persist ENTRY decision to decisions_log
        _persist_decisions_log(conn, pair, dtf, state, se, "ENTRY")

        corr_id = f"{pair}-{dtf}-{int(time.time()*1000)}-{se.side}"
        entry = se.entry_price
        sl, tp = se.sl_price, se.tp_price
        # v0.0.19: volatility-adaptive SL — scale SL wider for high-vol pairs
        vol_scale = volatility_scale(pair, state.atr_pct, pair_atr)
        if vol_scale != 1.0:
            if se.side == "BUY":
                sl = entry - abs(entry - sl) * vol_scale
            else:
                sl = entry + abs(entry - sl) * vol_scale
        # --- hard live boundary: in LIVE mode this raises unless human-approved ---
        if guard is not None:
            guard.assert_entry_allowed(pair, dtf, se.side)
        # P2-35: vol-targeted leverage. Cap base leverage by regime + bar volatility
        # so a 1-SL move costs a similar fraction of equity in any vol regime (fixes
        # F5: thin margin + fixed 2x = tail wipeout). Falls back to base when ATR
        # unknown.
        from sizing import regime_leverage, sl_risk_pct
        _atr_pct = pair_atr.get(pair, 0.0)
        lev_used = regime_leverage(surface.max_leverage, atr_pct=_atr_pct,
                                   regime=getattr(state, "regime", "range"))
        # real risk-based sizing (doc 30 §3): 0.25% equity at the SL distance
        info = (registry or SymbolRegistry()).get(pair)
        sl_distance = abs(entry - sl)
        if info is None or sl_distance <= 0 or entry <= 0:
            log.info("sizing skip %s: no symbol info or degenerate SL", pair)
            continue
        qty = size_position(equity=equity,
                            risk_per_trade_pct=surface.risk_per_trade_pct,
                            entry=entry, sl_price=sl, leverage=lev_used,
                            info=info, max_position_notional_pct=surface.max_position_notional_pct)
        if qty <= 0:
            # size_position returning 0 means the pair CANNOT satisfy
            # minNotional within the margin cap on this equity. The old
            # fallback (qty=1.0) opened $64k BTC notional on a $10 account
            # and one SL hit cost -$13.36 (>100% of equity). SKIP instead.
            log.info("sizing skip %s: cannot satisfy minNotional within "
                     "margin cap at equity %.2f — trade skipped", pair, equity)
            continue
        # guard: if the chosen leverage would risk > MAX_SL_RISK_PCT of equity on a
        # 1-SL hit, do not size up beyond that (defense-in-depth for F5).
        _notional = qty * entry * lev_used
        _risk = sl_risk_pct(equity, _notional, sl_distance / entry * 100.0, lev_used)
        if _risk > 5.0:
            # scale qty down to the 5% risk cap
            qty = qty * (5.0 / _risk)
            log.warning("sizing capped: SL risk %.2f%% > 5%% (lev %dx, pair %s)",
                        _risk, lev_used, pair)
        # v0.0.19: pair-level weight for sizing (reduce on consistently losing pairs)
        pair_w = PAIR_WEIGHTS.get(pair, 1.0)
        if pair_w != 1.0:
            qty *= pair_w
            log.debug("pair weight %s=%.2f qty=%.4f", pair, pair_w, qty)
        # v0.0.33: portfolio-level risk cap (goals.md: capital preservation).
        # Refuse NEW entries once we hit the global position count or total margin
        # exposure ceiling — 19 concurrent positions on a $10 account would allow
        # ~95% account risk if all SL at once. Cap both count and margin-used.
        _open_n = len(open_trades)
        if _open_n >= MAX_OPEN_POSITIONS:
            log.info("portfolio cap: %d positions >= MAX_OPEN_POSITIONS %d — skip %s",
                     _open_n, MAX_OPEN_POSITIONS, pair)
            continue
        _used_margin = sum(
            (t.entry_price or 0.0) * (t.size or 0.0) / max(getattr(t, "leverage", 1) or 1, 1)
            for t in open_trades.values())
        _new_margin = (entry * qty) / max(lev_used, 1)
        if (_used_margin + _new_margin) > MAX_TOTAL_MARGIN_PCT / 100.0 * equity:
            log.info("portfolio cap: margin %.2f + %.2f > %.1f%% of equity %.2f — skip %s",
                     _used_margin, _new_margin, MAX_TOTAL_MARGIN_PCT, equity, pair)
            continue
        # ── v0.0.34 survival gates: session/throttle/cooldown/big-candle vetoes,
        # then notional rescale vs LIVE equity, then fee-aware EV checks. ──
        qty, veto = survival_gates(pair, entry, sl, tp, qty, equity,
                                   dec[i] if dec else None,
                                   pair_atr.get(pair, 0.0),
                                   side=se.side)
        if veto:
            # v0.0.34b: dedup — log + persist each (pair, veto-class) at most
            # once per hour instead of every tick (was ~100 rows/10min of
            # identical "session filter" GATED rows).
            if _veto_should_note(pair, veto):
                log.info("survival gate veto %s: %s", pair, veto)
                _persist_decisions_log(conn, pair, dtf, state, se, "GATED", reason=veto)
            continue
        # ── v0.0.34 spread filter on REAL book data (was hardcoded 1.0) ──
        _spread = fetch_spread_bps(pair)
        if _spread is not None and _spread > 5.0:
            log.info("spread gate %s: %.2f bps > 5 — skip", pair, _spread)
            _persist_decisions_log(conn, pair, dtf, state, se, "GATED",
                                   reason=f"spread {_spread:.2f}bps > 5")
            continue
        # ── v0.0.35 research wave-1: order-flow vetoes on serious candidates ──
        # CVD z-score (free, from klines taker-buy volume): don't sell into
        # aggressive buying, don't buy into aggressive selling.
        _cvd_z = compute_cvd_z(dec, lookback=15)
        if _cvd_z is not None and (
                (se.side == "SELL" and _cvd_z > CVD_VETO_Z) or
                (se.side == "BUY" and _cvd_z < -CVD_VETO_Z)):
            if _veto_should_note(pair, f"cvd veto {se.side}"):
                log.info("cvd veto %s %s: cvd_z %+.2f", pair, se.side, _cvd_z)
                _persist_decisions_log(conn, pair, dtf, state, se, "GATED",
                                       reason=f"cvd veto: z {_cvd_z:+.2f} against {se.side}")
            continue
        # OI-delta flush detector (1 REST call, weight 1, only on candidates):
        # don't sell a long-liquidation flush bottom / buy a squeeze top.
        _price_falling = len(dec) >= 4 and dec[i].c < dec[i - 3].c
        _oi_veto = oi_flush_veto(pair, _price_falling, se.side)
        if _oi_veto:
            if _veto_should_note(pair, "OI flush veto"):
                log.info("%s: %s", pair, _oi_veto)
                _persist_decisions_log(conn, pair, dtf, state, se, "GATED",
                                       reason=_oi_veto)
            continue
        trade = lc.open(correlation_id=corr_id, pair=pair, tf=dtf,
                        side=se.side, entry_price=entry, size=qty,
                        leverage=lev_used, sl_price=sl, tp_price=tp,
                        decision_id=corr_id,
                        spread_bps=(_spread if _spread is not None else state.spread_bps),
                        regime=state.regime, scores=se.sub_scores.as_dict())
        open_trades[(pair, dtf, se.side)] = trade
        # v0.0.34: risk-layer bookkeeping + excursion tracker seed
        RISK_STATE["entries_hour"] += 1
        RISK_STATE["pair_last_entry"][pair] = time.time()
        EXCURSIONS[corr_id] = [0.0, 0.0]
        sl_state = place_stop_loss(exchange, pair, se.side, qty, sl) if exchange else None
        if monitor is not None:
            monitor.track(Position(
                correlation_id=corr_id, symbol=pair, tf=dtf,
                side=se.side, qty=qty, entry_price=entry,
                sl=sl_state or __import__("execution").StopLossState(
                    "CONDITIONAL", sl, "SELL" if se.side == "BUY" else "BUY"),
                tp_price=tp, opened_ts=time.time(),
                sl_on_exchange=False,
            ))
        tel.exec_event(corr_id, pair, dtf, "FILL", order_type="LIMIT",
                       side=se.side, price=entry, qty=qty, status="FILLED")
        # v0.0.34: post-only LIMIT entry → maker fee on open (taker only on close)
        _fee_open = FEE_RATE_MAKER * entry * qty
        _mark = cache.get(dtf, [None])[-1].c if cache.get(dtf) else entry
        _stats = paper_equity(conn, open_trades,
                               lambda p: (_mark if p == pair else entry))
        notifier.notify_fill(pair, dtf, se.side, entry, sl, tp, lev_used,
                             conf=getattr(se, "confidence_pct", 0.0),
                             fee_usd=_fee_open, size=qty, stats=_stats)
        # v0.0.23 T3: record the entry side for SELL-share balancing.
        if side_balancer is not None:
            side_balancer.record(se.side)


def _close(pair, tf, side, exit_price, reason, conn, lc, tel, kill, notifier,
           open_trades, loss_book=None, excluder=None, exchange=None):
    t = open_trades.pop((pair, tf, side), None)
    if t is None:
        return
    # v0.0.34: maker on open, taker on close + record excursion data (mfe/mae)
    _fee = FEE_RATE_MAKER * t.entry_price * t.size + FEE_RATE * exit_price * t.size
    _exc = EXCURSIONS.pop(t.correlation_id, None)
    res = lc.close(t, exit_price=exit_price, close_reason=reason,
                   fees_usd=_fee,
                   mfe_r=(_exc[0] if _exc else None),
                   mae_r=(_exc[1] if _exc else None))
    kill.record_close(pair, tf, side, win=bool(res["win"]))
    _record_loss_streak(bool(res["win"]))
    # v0.0.23 T2 / v0.0.24 P0-31: feed the close into the pair excluder.
    # Pass `conn` so the excluder uses NET expectancy$ (after fees) — the real
    # economic signal — instead of the raw W/L fallback.
    if excluder is not None:
        changed, action, note = excluder.record_close(pair, bool(res["win"]), conn=conn)
        if changed and action == "EXCLUDE":
            notifier.send_message(
                f"⛔️ **Pair excluded** `{pair}`\n_{note}_\n"
                f"Net expectancy negatif setelah fee — di-skip dari entri baru."
            )
        elif changed and action == "INCLUDE":
            notifier.send_message(
                f"✅ **Pair re-included** `{pair}`\n_{note}_"
            )
    # accumulate realized loss for the daily-loss kill-switch (doc 30 §7)
    if loss_book is not None and res["pnl_usd"] < 0:
        loss_book["usd"] += -res["pnl_usd"]
    tel.exec_event(t.correlation_id, pair, tf, "CLOSE", side=side,
                   price=exit_price, status=reason)
    _fee_total = _fee
    _net = res["pnl_usd"] - _fee_total
    _get_mark = (lambda p: exchange.mark_price(p)) if exchange else None
    _stats = paper_equity(conn, open_trades, _get_mark)
    notifier.notify_close(pair, tf, side, exit_price, reason, res["r_multiple"],
                          bool(res["win"]), fee_usd=_fee_total, net_usd=_net,
                          stats=_stats)
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
    # portfolio-wide win rate + DB growth awareness (doc 43)
    stats = db_stats(conn, DB_PATH)
    o = stats["overall"]
    overall = (f"<b>WR total</b>  : <code>{o['win_rate_pct']:.1f}%</code> "
               f"({o['n_wins']}W / {o['n_losses']}L · {o['n_closed']} closed)")
    dbline = (f"<b>DB</b>        : <code>{stats['size_human']}</code> · "
              f"<code>{stats['total_rows']}</code> row "
              f"(trades <code>{stats['counts'].get('trade_logs', 0)}</code>, "
              f"decisions <code>{stats['counts'].get('decisions_log', 0)}</code>)")
    notifier.notify_status_30m(lines, overall=overall, dbline=dbline)
    # standalone DB card with the full per-table breakdown + on-disk size
    notifier.notify_db_stats(vmod.read_version(), stats)


if __name__ == "__main__":
    run()
