"""Tests for Phase 35: regime-conditioned sizing / vol targeting (v0.0.24 P2-35).

Fixes F5: thin 11% net margin + fixed 2x leverage = tail wipeout risk. Sizing
must be vol-targeted: high ATR% or high_vol regime => LESS leverage.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sizing import regime_leverage, vol_target_notional, sl_risk_pct


def test_low_vol_full_leverage():
    # calm market -> full base leverage allowed
    assert regime_leverage(2, atr_pct=0.3, regime="range") == 2


def test_high_vol_scales_down():
    # ATR% 4x the ref -> leverage halved
    assert regime_leverage(2, atr_pct=4.0, regime="range") == 1


def test_high_vol_regime_caps_hard():
    # breakout/high_vol regime caps at 50% of base regardless
    assert regime_leverage(4, atr_pct=0.5, regime="high_vol") == 2
    assert regime_leverage(4, atr_pct=0.5, regime="breakout") == 2


def test_never_exceeds_base_or_below_min():
    assert regime_leverage(2, atr_pct=0.1, regime="range") <= 2
    assert regime_leverage(5, atr_pct=100.0, regime="range") >= 1


def test_vol_target_notional_bounded():
    # risk 1% of 1000 equity, SL 2% away, 2x lev -> notional = 1000 (1% risk)
    n = vol_target_notional(equity=1000.0, risk_pct=1.0, sl_distance_pct=2.0, leverage=2)
    assert n == pytest.approx(1000.0, rel=1e-6)
    # sl_risk_pct reverses it: a 1-SL move costs 1% of equity
    assert sl_risk_pct(equity=1000.0, notional=n, sl_distance_pct=2.0, leverage=2) == pytest.approx(1.0)
