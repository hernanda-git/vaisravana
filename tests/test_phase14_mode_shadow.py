"""Phase 14 — tests for the hard mode boundary, PositionMonitor+PaperExchange,
and the honest shadow replay (doc 40 §2/§6, doc 41).

Run: pytest tests/test_phase14_mode_shadow.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest

from mode import ModeGuard, PaperSimExchange, ModeBoundaryError
from monitor import PositionMonitor, Position, CloseEvent
from execution import StopLossState, place_stop_loss, size_position
from marketdata import Candle
import backtest
from config import default_surface
import shadow


# --------------------------------------------------------------------------- #
# 1. HARD MODE BOUNDARY (doc 40 §6 / doc 30 §7)                               #
# --------------------------------------------------------------------------- #

def test_paper_mode_refuses_live_adapter():
    g = ModeGuard(mode="paper")
    with pytest.raises(ModeBoundaryError):
        g.exchange_for(object())  # must not pass a live exchange in paper


def test_paper_mode_gives_sim_exchange():
    g = ModeGuard(mode="paper")
    ex = g.exchange_for(None)
    assert isinstance(ex, PaperSimExchange)


def test_paper_entry_always_allowed_no_approval_needed():
    g = ModeGuard(mode="paper")
    g.assert_entry_allowed("BTCUSDT", "5m", "BUY")  # no raise


def test_live_mode_requires_approval_and_adapter():
    g = ModeGuard(mode="live", approved={("BTCUSDT", "5m", "BUY")})
    with pytest.raises(ModeBoundaryError):
        g.assert_entry_allowed("BTCUSDT", "5m", "SELL")  # not approved
    with pytest.raises(ModeBoundaryError):
        g.exchange_for(None)  # no adapter supplied


def test_live_entry_allowed_when_approved():
    g = ModeGuard(mode="live", approved={("BTCUSDT", "5m", "BUY")})
    g.assert_entry_allowed("BTCUSDT", "5m", "BUY")  # ok

    # GuardedExchange blocks an unapproved symbol at the wire
    real = PaperSimExchange()
    guarded = g.exchange_for(real)
    with pytest.raises(ModeBoundaryError):
        guarded.place_order(__import__("execution").OrderDraft(
            symbol="ETHUSDT", side="BUY", qty=1, price=1, order_type="MARKET"))


def test_invalid_mode_rejected():
    with pytest.raises(ModeBoundaryError):
        ModeGuard(mode="production")


# --------------------------------------------------------------------------- #
# 2. PositionMonitor + PaperSimExchange — real per-tick stop protection        #
# --------------------------------------------------------------------------- #

def _monitor_with_position(entry=100.0, sl=99.0, tp=102.0, side="BUY", qty=1.0):
    ex = PaperSimExchange()
    mon = PositionMonitor(ex, clock=lambda: 0.0)
    pos = Position(
        correlation_id="c1", symbol="BTCUSDT", tf="5m", side=side,
        qty=qty, entry_price=entry,
        sl=StopLossState("CONDITIONAL", sl, "SELL" if side == "BUY" else "BUY"),
        tp_price=tp, opened_ts=0.0,
        sl_on_exchange=False, tp_on_exchange=False,  # paper: monitor polls mark
    )
    mon.track(pos)
    return mon, ex


def test_stop_loss_fires_on_mark_price():
    mon, ex = _monitor_with_position(entry=100, sl=99, tp=102, side="BUY")
    ex.set_price("BTCUSDT", 98.5)
    events = mon.tick()
    assert len(events) == 1
    ev = events[0]
    assert ev.reason == "SL"
    assert ev.symbol == "BTCUSDT"
    assert ev.tf == "5m"
    assert ev.side == "BUY"


def test_close_event_carries_tf_and_side():
    """CloseEvent must carry tf+side for the main loop to key into open_trades."""
    # SELL: SL above entry (price goes up → loss), TP below entry (price goes down → profit)
    mon, ex = _monitor_with_position(entry=200, sl=201, tp=198, side="SELL")
    ex.set_price("BTCUSDT", 197.0)  # TP hit for SELL (mark <= tp)
    events = mon.tick()
    assert len(events) == 1
    ev = events[0]
    assert ev.reason == "TP"
    assert ev.tf == "5m"
    assert ev.side == "SELL"
    assert ev.symbol == "BTCUSDT"
    assert ev.price == 197.0
    # also verify SELL-side SL breach
    mon2, ex2 = _monitor_with_position(entry=100, sl=101, tp=98, side="SELL")
    ex2.set_price("BTCUSDT", 101.5)  # SL for SELL = mark >= stop_price
    events2 = mon2.tick()
    assert len(events2) == 1
    ev2 = events2[0]
    assert ev2.reason == "SL"
    assert ev2.tf == "5m"
    assert ev2.side == "SELL"


def test_take_profit_fires_on_mark_price():
    mon, ex = _monitor_with_position(entry=100, sl=99, tp=102, side="BUY")
    ex.set_price("BTCUSDT", 102.5)
    events = mon.tick()
    assert events and events[0].reason == "TP"


def test_maxhold_fires_after_budget():
    mon, ex = _monitor_with_position(entry=100, sl=99, tp=102, side="BUY")
    ex.set_price("BTCUSDT", 100.2)  # never hits SL/TP
    # force open_ts far in the past beyond the 5m max-hold budget (300s)
    mon.positions["c1"].opened_ts = -10_000_000
    events = mon.tick()
    assert events and events[0].reason == "MAXHOLD"


def test_position_removed_after_close():
    mon, ex = _monitor_with_position(entry=100, sl=99, tp=102, side="BUY")
    ex.set_price("BTCUSDT", 98.5)
    mon.tick()
    assert all(p.closed for p in mon.positions.values())  # marked closed
    assert mon.close_events[-1].reason == "SL"


def test_place_stop_loss_returns_on_exchange_state():
    ex = PaperSimExchange()
    st = place_stop_loss(ex, "BTCUSDT", "BUY", 1.0, 99.0)
    assert st is not None
    assert st.stop_price == 99.0


# --------------------------------------------------------------------------- #
# 3. HONEST SHADOW REPLAY — can beat baseline (doc 40 §2.3)                    #
# --------------------------------------------------------------------------- #

def _synth_candles(n=200, start=100.0, seed=3):
    import math
    out = []
    p = start
    for i in range(n):
        p = p * (1 + 0.002 * math.sin(i / 9.0 + seed))
        o = p
        c = p * (1 + 0.001 * math.sin(i / 4.0))
        h = max(o, c) * (1 + 0.0015)
        l = min(o, c) * (1 - 0.0015)
        out.append(Candle(o=round(o, 4), h=round(h, 4), l=round(l, 4),
                          c=round(c, 4), v=10.0, ts=i * 60_000))
    return out


def test_shadow_replay_runs_and_returns_comparison():
    candles = _synth_candles(220)
    # factory must carry its candle series for the harness to replay
    def factory(c, i):
        return _simple_state(c, i)
    factory._candles = candles  # type: ignore[attr-defined]
    factories = {("BTCUSDT", "5m"): factory}

    base = default_surface()
    cand = default_surface()
    # candidate widens TP a touch — a genuine change the replay can detect
    cand.tp_atr_mult = base.tp_atr_mult + 0.2

    comp = shadow.shadow_compare(base, cand, factories, max_hold_bars=30)
    assert comp.baseline is not None
    assert comp.shadow is not None
    # at minimum both reports are well-formed
    assert hasattr(comp.baseline, "expectancy_r")
    assert hasattr(comp.shadow, "expectancy_r")


def _simple_state(candles, i):
    """Minimal MarketState so the orchestrator can decide — keeps the test offline."""
    from engines import MarketState
    c = candles[i]
    atr = (max(c.h - c.l for c in candles[max(0, i - 14):i + 1]) or 1.0)
    return MarketState(
        symbol="BTCUSDT", tf="5m", regime="RANGE", htf_bias="NEUTRAL",
        last_close=c.c, body_ratio=0.5, vol_z=0.0, delta_z=0.0,
        atr=atr, atr_pct=atr / c.c, spread_bps=1.0, adl_rank=1, mtf_aligned=True,
        hh=c.h, hl=c.l, lh=c.h, ll=c.l, bos=False, choch=False,
        liq_sweep=False, eq_low=c.l, eq_high=c.h, fvg=False,
    )


def test_backtest_harness_multi_bar_hold_default():
    """MAX_HOLD_BARS changed from 1 (gamble) to 60 (honest) — verify default."""
    assert backtest.MAX_HOLD_BARS == 60
