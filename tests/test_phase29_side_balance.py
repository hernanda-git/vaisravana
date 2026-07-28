"""Tests for v0.0.23 T3 — SideBalancer (doc 45 §2).

Pure: in-memory deque, no DB / Telegram.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from side_balancer import SideBalancer, MIN_SELL_SHARE, SELL_NUDGE  # noqa: E402


def _fill(b: SideBalancer, buys: int, sells: int):
    for _ in range(buys):
        b.record("BUY")
    for _ in range(sells):
        b.record("SELL")


def test_sell_share_zero_when_empty():
    b = SideBalancer()
    assert b.sell_share == 0.0
    assert not b.suppressed  # not enough data


def test_sell_share_10_to_1_suppressed():
    b = SideBalancer(window=40)
    _fill(b, 36, 4)  # 10:1 -> 10% SELL share
    assert abs(b.sell_share - 0.10) < 1e-9
    assert b.suppressed  # below 25% floor


def test_sell_share_healthy_not_suppressed():
    b = SideBalancer(window=40)
    _fill(b, 30, 10)  # 25% SELL -> at floor, not below
    assert abs(b.sell_share - 0.25) < 1e-9
    assert not b.suppressed  # 0.25 is NOT < 0.25


def test_threshold_nudged_when_suppressed():
    b = SideBalancer(window=40)
    _fill(b, 36, 4)  # suppressed
    t = b.sell_threshold(base_entry=0.60, watch_threshold=0.52)
    assert abs(t - 0.57) < 1e-9, t  # 0.60 - 0.03


def test_threshold_untouched_when_healthy():
    b = SideBalancer(window=40)
    _fill(b, 30, 12)  # not suppressed
    t = b.sell_threshold(base_entry=0.60, watch_threshold=0.52)
    assert abs(t - 0.60) < 1e-9


def test_threshold_clamped_at_watch_band():
    # nudge would go below watch -> clamp
    b = SideBalancer(window=40)
    _fill(b, 36, 4)  # suppressed
    t = b.sell_threshold(base_entry=0.54, watch_threshold=0.52)
    assert abs(t - 0.52) < 1e-9, t  # 0.54-0.03=0.51 clamped to 0.52


def test_window_rolls_oldest():
    b = SideBalancer(window=4)
    _fill(b, 4, 0)   # 0% SELL
    assert b.sell_share == 0.0
    _fill(b, 0, 4)   # now 4 sells replace -> 100% SELL
    assert b.sell_share == 1.0
    assert not b.suppressed  # healthy, and window full
