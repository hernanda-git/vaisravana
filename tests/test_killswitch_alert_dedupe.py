"""Tests: kill-switch alert de-duplication (v0.0.25).

Fixes the spammy.txt issue — the kill-switch is checked every tick, so a tripped
switch must alert ONCE per trip (then at most every interval) instead of spamming
the Telegram channel every loop.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from safety import KillSwitch


def test_alert_fires_once_per_trip():
    clock = [1000.0]
    k = KillSwitch(clock=lambda: clock[0], _alert_interval_s=30 * 60)

    # trip
    k.check_global(daily_loss_pct=1.0)
    assert k.tripped is True
    # first alert due immediately
    assert k.alert_due() is True
    # subsequent calls within the interval: NOT due (no spam)
    assert k.alert_due() is False
    assert k.alert_due() is False

    # advance past the interval -> re-alert allowed (still tripped)
    clock[0] += 31 * 60
    assert k.alert_due() is True
    assert k.alert_due() is False


def test_alert_not_due_when_not_tripped():
    k = KillSwitch(_alert_interval_s=30 * 60)
    assert k.tripped is False
    assert k.alert_due() is False


def test_fresh_trip_resets_alert_timer():
    clock = [0.0]
    k = KillSwitch(clock=lambda: clock[0], _alert_interval_s=30 * 60)
    k.check_global(daily_loss_pct=1.0)
    assert k.alert_due() is True
    assert k.alert_due() is False
    # reset + new trip -> first alert fires again (timer cleared on fresh trip)
    k.reset()
    assert k.alert_due() is False
    k.check_global(daily_loss_pct=2.0)
    assert k.alert_due() is True
