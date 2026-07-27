"""Tests for Phase 36: closed self-improving loop — bounded diff + auto-revert
(v0.0.24 P2-36).

The Sentinel can promote autonomously in PAPER, but a degenerate promoted surface
must be auto-reverted before it can ever reach live trading.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from sentinel import Sentinel, Proposal, apply_proposal
from config import default_surface
from evaluation import EvalReport


def _surface():
    return default_surface()


def _fake_cmp_factory(candidate, baseline, shadow):
    def _f(surf):
        from sentinel import ShadowComparison
        return ShadowComparison(baseline=baseline, shadow=shadow)
    return _f


def test_sanity_check_flags_rr_breach():
    s = _surface()
    # model_construct bypasses validators (simulates a surface loaded from JSON /
    # produced by a path that skipped validation) — sanity_check is defense-in-depth.
    bad = s.model_construct(tp_atr_mult=1.0, sl_atr_mult=1.0)  # 1:1 floor breach
    sent = Sentinel(conn=__import__("db", fromlist=["init_db"]).init_db(":memory:"), surface=s)
    assert sent.sanity_check(bad)  # non-empty -> violation


def test_revert_rolls_back_to_previous():
    conn = __import__("db", fromlist=["init_db"]).init_db(":memory:")
    s = _surface()
    sent = Sentinel(conn=conn, surface=s, config_ver=5)
    # simulate a prior promotion recorded in history
    sent.history.append((4, s))
    sent.config_ver = 5
    sent.surface = s.model_copy(update={"entry_threshold": 0.85})
    reverted = sent.revert(reason="test")
    assert sent.config_ver == 4
    assert sent.surface is s  # back to previous
    assert reverted is s


def test_promote_guarded_autoreverts_degenerate():
    conn = __import__("db", fromlist=["init_db"]).init_db(":memory:")
    base = _surface()
    sent = Sentinel(conn=conn, surface=base, config_ver=3)
    # simulate a promoted-but-degenerate surface now ACTIVE (e.g. loaded from a
    # corrupted config that bypassed apply_proposal), with a clean prior in history.
    sent.history.append((2, base))
    sent.surface = base.model_construct(tp_atr_mult=1.0, sl_atr_mult=1.0)  # 1:1 breach
    sent.config_ver = 3
    # sanity_check must flag it; revert must roll back to the clean v2 surface.
    assert sent.sanity_check() != []
    reverted = sent.revert(reason="post-promotion sanity")
    assert sent.config_ver == 2
    assert sent.sanity_check(reverted) == []  # reverted surface is clean
