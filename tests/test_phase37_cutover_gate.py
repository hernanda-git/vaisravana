"""Tests for Phase 37: human-gated live cutover gate (v0.0.24 P2-37).

The bot may promote autonomously in PAPER, but NO surface may reach LIVE capital
without explicit human approval. can_deploy() is the single source of truth.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from cutover_gate import CutoverGate


def _gate():
    import db as _db
    return CutoverGate(_db.init_db(":memory:"))


def test_no_deploy_without_approval():
    g = _gate()
    assert g.can_deploy() is False
    g.request_deploy(7)
    assert g.can_deploy() is False  # pending, not approved


def test_approve_enables_deploy():
    g = _gate()
    g.request_deploy(7)
    g.approve(who="hernanda")
    assert g.can_deploy() is True
    st = g.state()
    assert st.approved_by == "hernanda"
    assert st.pending_ver == 7


def test_reject_clears_pending():
    g = _gate()
    g.request_deploy(7)
    g.reject(who="hernanda", note="not yet")
    assert g.can_deploy() is False
    assert g.state().pending_ver is None


def test_reset_closes_gate():
    g = _gate()
    g.request_deploy(7)
    g.approve(who="hernanda")
    assert g.can_deploy() is True
    g.reset()
    assert g.can_deploy() is False
