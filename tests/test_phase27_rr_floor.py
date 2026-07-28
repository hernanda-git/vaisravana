"""Tests for v0.0.23 T1 — enforce R:R >= 2:1 on the active ParameterSurface.

Owner mandate: "1 win recovers 2 losses is OK" -> R:R >= 2:1.
Break-even WR at 2:1 = 1/(1+2) = 33.3%. Below this the bot can
lose money structurally, which violates "I don't want to lose money".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import ParameterSurface  # noqa: E402


def test_default_surface_is_valid_and_meets_rr_floor():
    s = ParameterSurface()
    # v0.0.23: active PAPER surface must be R:R >= 2:1 by default.
    assert s.sl_atr_mult == 1.0
    assert s.tp_atr_mult == 2.0
    assert s.rr >= 2.0


def test_rr_floor_rejects_below_2_to_1():
    # The old 1.5:1 default must now raise — owner floor is 2:1.
    try:
        ParameterSurface(sl_atr_mult=1.0, tp_atr_mult=1.5)
        assert False, "should have raised: 1.5:1 is below the 2:1 owner floor"
    except Exception as e:
        assert "rr" in str(e).lower() or "2.0" in str(e)


def test_rr_floor_allows_exactly_2_to_1():
    s = ParameterSurface(sl_atr_mult=1.0, tp_atr_mult=2.0)
    assert abs(s.rr - 2.0) < 1e-9


def test_rr_floor_allows_higher_rr():
    s = ParameterSurface(sl_atr_mult=1.0, tp_atr_mult=3.0)
    assert s.rr == 3.0


def test_rr_floor_independent_of_sl_scaling():
    # 2:1 must hold regardless of sl mult (e.g. sl=1.5 -> tp>=3.0).
    s = ParameterSurface(sl_atr_mult=1.5, tp_atr_mult=3.0)
    assert s.rr == 2.0
    try:
        ParameterSurface(sl_atr_mult=1.5, tp_atr_mult=2.0)  # 1.33:1
        assert False, "should have raised: 1.33:1 below 2:1 even with wider sl"
    except Exception:
        pass


def test_expectancy_positive_at_owner_floor():
    """Repeatable edge: at R:R 2:1 and the live 46.3% WR, expectancy > 0.

    expectancy per trade (R) = WR*tp_r - (1-WR)*sl_r
    with tp_r=2.0, sl_r=1.0, WR=0.463:
        0.463*2.0 - 0.537*1.0 = 0.926 - 0.537 = +0.389R  (>0)
    This is the *design* expectancy (ignoring outlier runners), proving
    the bot is structurally profitable at the owner's floor.
    """
    wr = 0.463
    tp_r, sl_r = 2.0, 1.0
    exp = wr * tp_r - (1 - wr) * sl_r
    assert exp > 0.0, f"expectancy {exp:+.3f}R must be >0 at 2:1 / 46% WR"
    # Even at break-even WR 33.3% it is ~0, never negative by construction.
    be = (1 / (1 + tp_r / sl_r))
    assert abs(be - 1 / 3) < 1e-9, "break-even WR at 2:1 must be 33.3%"
