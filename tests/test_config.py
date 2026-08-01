"""Tests for the parameter surface (doc 21)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import ParameterSurface, Weights  # noqa: E402


def test_default_surface_is_valid():
    s = ParameterSurface()
    assert s.entry_threshold == 0.45
    assert s.tp_atr_mult == 2.0  # v0.0.23 T1: R:R 2:1 floor
    assert s.sl_atr_mult == 1.0
    assert s.rr >= 2.0
    assert s.max_leverage == 5
    assert s.daily_loss_limit_pct == 2.0
    assert s.risk_per_trade_pct == 0.25
    assert s.winrate_floor_pct == 45.0
    assert s.min_expectancy_r == 0.02
    assert s.winrate_gate_pct == 85.0          # advisory, kept for backward-compat
    assert s.min_trades_for_promote == 100
    assert s.global_max_live_pairs == 10


def test_weights_sum_to_one():
    w = Weights()
    assert abs(sum(w.as_dict().values()) - 1.0) < 1e-9


def test_entry_threshold_bound_enforced():
    try:
        ParameterSurface(entry_threshold=0.40)  # below 0.50 floor
        assert False, "should have raised"
    except Exception as e:
        assert "entry_threshold" in str(e) or "ge" in str(e)


def test_max_leverage_hard_cap():
    try:
        ParameterSurface(max_leverage=6)  # above 5 ceiling
        assert False, "should have raised"
    except Exception as e:
        assert "max_leverage" in str(e) or "le" in str(e)


def test_watch_below_entry():
    try:
        ParameterSurface(entry_threshold=0.86, watch_threshold=0.90)
        assert False, "should have raised"
    except Exception as e:
        assert "watch_threshold" in str(e)


def test_weights_out_of_bound():
    try:
        Weights(trend=0.99)  # > 0.40 ceiling
        assert False, "should have raised"
    except Exception as e:
        assert "trend" in str(e)


def test_weights_bad_sum_rejected():
    try:
        # trend 0.40 + momentum 0.30 + volume 0.25 + structure 0.25 + rest default
        # exceeds 1.0; pydantic validation must catch.
        Weights(trend=0.40, momentum=0.30, volume=0.25, structure=0.25)
        assert False, "should have raised on Σ != 1.0"
    except Exception as e:
        assert "1.0" in str(e)
