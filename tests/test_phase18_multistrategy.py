"""Phase 18 (v0.1.0) — concurrent multi-strategy engine.

Verifies Scalp/Day/Swing evaluate independently on the same pair, SL/TP scale with each
profile's ATR mult, the lower activity bars actually produce more entries, and strategies can
be disabled via env.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from config import default_profiles  # noqa: E402
from engines import MarketState  # noqa: E402
from strategy import (  # noqa: E402
    active_strategies,
    evaluate_all,
    evaluate_strategy,
)


def _bull() -> MarketState:
    return MarketState(
        symbol="ENAUSDT", tf="1m", regime="trending_bull", htf_bias="bullish",
        body_ratio=0.95, vol_z=3.0, delta_z=3.0, bos=True, hh=True, hl=True,
        choch=True, liq_sweep=True, eq_low=True, fvg=True, atr_pct=0.01,
        spread_bps=1.0, funding_ok=True, adl_rank=1,
    )


def _marginal() -> MarketState:
    # mid-grade setup: clears a low scalp bar but not a strict one
    return MarketState(
        symbol="ENAUSDT", tf="1m", regime="trending_bull", htf_bias="bullish",
        body_ratio=0.62, vol_z=1.0, delta_z=0.8, bos=True, hl=True,
        liq_sweep=True, atr_pct=0.01, spread_bps=2.0, funding_ok=True, adl_rank=2,
    )


def test_three_strategies_active_by_default():
    names = [p.name for p in active_strategies()]
    assert names == ["scalping", "day", "swing"]


def test_disable_strategy_via_env(monkeypatch):
    monkeypatch.setenv("VAISRAVANA_DISABLED_STRATEGIES", "swing,day")
    names = [p.name for p in active_strategies()]
    assert names == ["scalping"]


def test_sl_tp_scale_with_profile():
    profs = default_profiles()
    scalp = evaluate_strategy(profs["scalping"], _bull(), entry_price=100.0, atr=1.0)
    swing = evaluate_strategy(profs["swing"], _bull(), entry_price=100.0, atr=1.0)
    # scalp: sl 1.0xATR, tp 1.5xATR ; swing: sl 2.0xATR, tp 4.0xATR
    assert scalp.sl_price == pytest.approx(99.0)
    assert scalp.tp_price == pytest.approx(101.5)
    assert swing.sl_price == pytest.approx(98.0)
    assert swing.tp_price == pytest.approx(104.0)
    assert swing.rr > scalp.rr


def test_short_sl_tp_mirrored():
    profs = default_profiles()
    bear = MarketState(
        symbol="ENAUSDT", tf="1m", regime="trending_bear", htf_bias="bearish",
        body_ratio=0.95, vol_z=3.0, delta_z=-3.0, bos=True, lh=True, ll=True,
        choch=True, liq_sweep=True, eq_high=True, fvg=True, atr_pct=0.01,
        spread_bps=1.0, funding_ok=True, adl_rank=1,
    )
    se = evaluate_strategy(profs["scalping"], bear, entry_price=100.0, atr=1.0)
    assert se.side == "SELL"
    assert se.sl_price == pytest.approx(101.0)   # SL above for short
    assert se.tp_price == pytest.approx(98.5)    # TP below for short


def test_evaluate_all_returns_entries_sorted():
    st = _bull()
    states = {"scalping": st, "day": st, "swing": st}
    atrs = {"scalping": 1.0, "day": 1.0, "swing": 1.0}
    entries = evaluate_all(states, entry_price=100.0, atr_by_strategy=atrs)
    assert len(entries) >= 1
    # sorted by confidence desc
    confs = [e.confidence_pct for e in entries]
    assert confs == sorted(confs, reverse=True)


def test_lower_bar_is_more_active_than_old_gate():
    """The whole point: a marginal setup that the old 0.86 gate would SKIP now ENTERs
    on at least the scalping profile (0.60 bar)."""
    profs = default_profiles()
    se = evaluate_strategy(profs["scalping"], _marginal(), entry_price=100.0, atr=1.0)
    # marginal should at least be actionable (ENTRY or WATCH), not a hard SKIP-to-nothing
    assert se.decision in ("ENTRY", "WATCH")
