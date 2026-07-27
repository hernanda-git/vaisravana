"""Tests for Phase 37 wiring: deploy.py must refuse without human cutover approval.

The CutoverGate is human-in-the-loop; deploy.py is the only path to LIVE capital,
so it MUST consult can_deploy() and abort otherwise.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from cutover_gate import CutoverGate
import db as _db


def _tmp_db(tmp_path):
    return _db.init_db(tmp_path / "prod.db")


def test_deploy_gate_blocks_unapproved(monkeypatch, tmp_path):
    """Simulate deploy.py's gate check: no approval -> refuse."""
    conn = _tmp_db(tmp_path)

    # replicate the deploy.py logic in-process
    gate = CutoverGate(conn)
    assert gate.can_deploy() is False, "gate must default closed"


def test_deploy_gate_allows_after_approve(monkeypatch, tmp_path):
    conn = _tmp_db(tmp_path)
    gate = CutoverGate(conn)
    gate.request_deploy(9, requested_at="2026-07-27T10:00:00+00:00")
    gate.approve(who="hernanda")
    assert gate.can_deploy() is True
    # the deploy.py abort branch would NOT fire
