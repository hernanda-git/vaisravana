import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from alpha_signals import cvd_divergence, regime_tp_multiplier


def test_cvd_positive_divergence_is_buy_candidate():
    d = cvd_divergence([-0.001, -0.001], 1.5)
    assert d.side == "BUY"
    assert d.strength > 0


def test_cvd_negative_divergence_is_sell_candidate():
    d = cvd_divergence([0.001, 0.001], -1.5)
    assert d.side == "SELL"


def test_no_divergence_without_confirmation():
    assert cvd_divergence([-0.001, -0.001], 0.2).side is None


def test_regime_tp_is_bounded():
    base = 2.0
    for regime in ("trending_bull", "trending_bear", "breakout", "high_vol", "range"):
        value = regime_tp_multiplier(regime, 0.01, base=base)
        assert 1.5 <= value <= 2.7
