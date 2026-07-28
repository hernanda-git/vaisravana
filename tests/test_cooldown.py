"""iter-7: wall-clock cooldown semantics (manager.py)."""
import sys, time
sys.path.insert(0, "src")
from wave.manager import WaveManager, COOLDOWN_S


def test_active_cooldown_blocks_only_its_key():
    m = WaveManager()
    m.cooldowns[("BTCUSDT", "BUY")] = time.time() + COOLDOWN_S
    assert m.in_cooldown("BTCUSDT", "BUY")
    assert not m.in_cooldown("BTCUSDT", "SELL")
    assert not m.in_cooldown("ETHUSDT", "BUY")


def test_expired_cooldown_is_inactive_and_purged():
    m = WaveManager()
    m.cooldowns[("ETHUSDT", "SELL")] = time.time() - 1
    m.cooldowns[("BTCUSDT", "BUY")] = time.time() + COOLDOWN_S
    assert not m.in_cooldown("ETHUSDT", "SELL")
    m.tick_cooldowns()
    assert ("ETHUSDT", "SELL") not in m.cooldowns
    assert ("BTCUSDT", "BUY") in m.cooldowns


def test_repeated_ticks_do_not_erode_wallclock_cooldown():
    # the iter-7 bug: per-pair tick fanout decayed tick-counters ~20x too fast
    m = WaveManager()
    m.cooldowns[("INJUSDT", "BUY")] = time.time() + COOLDOWN_S
    for _ in range(10_000):
        m.tick_cooldowns()
    assert m.in_cooldown("INJUSDT", "BUY")
