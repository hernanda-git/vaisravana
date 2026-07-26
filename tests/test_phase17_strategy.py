"""Phase 17 (v0.1.0) — strategy profiles + expectancy-first surface.

Verifies the Scalping/Day/Swing profiles load with sane, +EV-consistent parameters and that
the lowered active thresholds still enforce the watch<entry invariant and bounds.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from config import (  # noqa: E402
    ParameterSurface,
    StrategyProfile,
    default_profiles,
    default_surface,
)


def test_three_default_profiles_present():
    profs = default_profiles()
    assert set(profs) == {"scalping", "day", "swing"}


def test_profiles_are_positive_expectancy_by_construction():
    """Each profile's R:R must beat the taker break-even at its WR floor.

    BE_WR = (1 + fee_R) / (R:R + 1). With fee_R ~0.2 (scalp) the floor must exceed BE.
    We use a conservative fee_R and assert floor - BE_WR margin > 0.
    """
    profs = default_profiles()
    fee_r = {"scalping": 0.20, "day": 0.083, "swing": 0.042}
    for name, p in profs.items():
        be_wr = (1 + fee_r[name]) / (p.rr + 1) * 100.0
        assert p.winrate_floor_pct > be_wr, (
            f"{name}: floor {p.winrate_floor_pct}% must exceed break-even {be_wr:.1f}%"
        )


def test_scalp_tighter_than_swing():
    profs = default_profiles()
    assert profs["scalping"].sl_atr_mult < profs["swing"].sl_atr_mult
    assert profs["scalping"].max_hold_min < profs["swing"].max_hold_min
    assert profs["scalping"].cooldown_min < profs["swing"].cooldown_min


def test_profile_rr_values():
    profs = default_profiles()
    assert profs["scalping"].rr == pytest.approx(1.5)
    assert profs["day"].rr == pytest.approx(1.6667, abs=1e-3)
    assert profs["swing"].rr == pytest.approx(2.0)


def test_profile_watch_below_entry_enforced():
    with pytest.raises(Exception):
        StrategyProfile(
            name="bad", decision_tf="1m", entry_threshold=0.60, watch_threshold=0.65,
            sl_atr_mult=1.0, tp_atr_mult=1.5, max_hold_min=15,
        )


def test_surface_active_defaults():
    s = default_surface()
    assert s.entry_threshold == 0.60          # active, not the old 0.86 silence bar
    assert s.winrate_floor_pct == 56.0
    assert s.min_expectancy_r == 0.10
    assert s.min_trades_for_promote == 100


def test_surface_entry_floor_allows_active_bar():
    # 0.56 must be a legal entry threshold now (was rejected under the 0.85 floor)
    s = ParameterSurface(entry_threshold=0.56, watch_threshold=0.50)
    assert s.entry_threshold == 0.56
