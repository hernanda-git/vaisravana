"""Tests for Phase 32: side maturity gate (v0.0.24 P0-32).

Fixes F3: SELL only went live ~2026-07-27 04:42 UTC with ~12 trades (<3h).
A side must be MATURE (enough samples + stable Wilson CI) before it drives
exclusion / promotion math or a "SELL broken/works" conclusion.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from side_maturity import SideMaturity, SideSample


def test_immature_with_few_trades():
    m = SideMaturity(min_trades=50)
    for _ in range(12):  # exactly the SELL live sample size
        m.record("SELL", win=True)
    assert not m.is_mature("SELL")
    assert m.maturity_label("SELL").startswith("IMMATURE")


def test_mature_after_enough_trades_and_stable_ci():
    m = SideMaturity(min_trades=50, ci_max_width=0.20)
    # 60 trades, ~55% win -> Wilson CI half-width < 0.20
    for _ in range(33):
        m.record("BUY", win=True)
    for _ in range(27):
        m.record("BUY", win=False)
    assert m.is_mature("BUY")
    assert m.maturity_label("BUY") == "MATURE"


def test_unsampled_label():
    m = SideMaturity()
    assert m.maturity_label("SELL") == "UNSAMPLED"


def test_immature_blocks_promotion_math():
    """Demonstrate the intended use: a consumer skips immature sides."""
    m = SideMaturity(min_trades=50)
    for _ in range(12):
        m.record("SELL", win=True)
    # a promote/exclude decision should refuse to act on IMMATURE SELL
    side = "SELL"
    decision_allowed = m.is_mature(side)
    assert decision_allowed is False
