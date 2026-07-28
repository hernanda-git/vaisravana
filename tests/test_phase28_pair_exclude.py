"""Tests for v0.0.23 T2 — PairExcluder (doc 45 §3).

All pure: uses a temp JSON path, no DB / Telegram / clock.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pair_excluder import PairExcluder  # noqa: E402


def _tmp_path():
    return Path(tempfile.mkdtemp()) / "excl.json"


def _feed(exc: PairExcluder, pair: str, results: list[bool]):
    last = (False, "", "")
    for r in results:
        last = exc.record_close(pair, r)
    return last


def test_exclude_below_40pct_after_10_trades():
    exc = PairExcluder(_tmp_path())
    # 3 wins / 7 losses = 30% WR over 10 trades -> exclude
    res = [True] * 3 + [False] * 7
    changed, action, note = _feed(exc, "PEPE", res)
    assert changed and action == "EXCLUDE"
    assert exc.is_excluded("PEPE")
    assert "30.0%" in note


def test_no_exclude_before_min_trades():
    exc = PairExcluder(_tmp_path())
    # 9 trades at 20% WR -> not enough sample, must NOT exclude
    res = [True] * 2 + [False] * 7
    changed, action, _ = _feed(exc, "X", res)
    assert not changed and action == ""
    assert not exc.is_excluded("X")


def test_40pct_is_boundary_not_excluded():
    exc = PairExcluder(_tmp_path())
    # 4 wins / 6 losses = exactly 40% -> NOT below 40 -> no exclude
    res = [True] * 4 + [False] * 6
    changed, action, _ = _feed(exc, "Y", res)
    assert not changed and action == ""
    assert not exc.is_excluded("Y")


def test_reinclude_after_recovery_to_50pct():
    exc = PairExcluder(_tmp_path())
    # first 10 trades: 3W/7L -> exclude
    _feed(exc, "PEPE", [True] * 3 + [False] * 7)
    assert exc.is_excluded("PEPE")
    # continue from persisted state: add wins until WR clears 50% -> re-include
    exc2 = PairExcluder(exc.path)
    saw_include = False
    # 7 wins bring it to 10W/7L = 58.8% -> INCLUDE
    for _ in range(7):
        changed, action, _ = exc2.record_close("PEPE", True)
        if action == "INCLUDE":
            saw_include = True
            break
    assert saw_include, "pair should re-include once WR >= 50%"
    assert not exc2.is_excluded("PEPE")
    # a few more losses (50%) must NOT immediately re-exclude
    for _ in range(3):
        exc2.record_close("PEPE", False)
    assert not exc2.is_excluded("PEPE")


def test_persistence_roundtrip():
    p = _tmp_path()
    exc = PairExcluder(p)
    _feed(exc, "WLD", [True] * 3 + [False] * 7)  # exclude
    # new instance reads the same file
    exc2 = PairExcluder(p)
    assert exc2.is_excluded("WLD")
    assert "WLD" in exc2.excluded_pairs


def test_independent_pairs():
    exc = PairExcluder(_tmp_path())
    _feed(exc, "PEPE", [True] * 3 + [False] * 7)   # exclude
    _feed(exc, "BTC", [True] * 9 + [False] * 1)    # 90% WR -> keep
    assert exc.is_excluded("PEPE")
    assert not exc.is_excluded("BTC")
    assert exc.excluded_pairs == ["PEPE"]
