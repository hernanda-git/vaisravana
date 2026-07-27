"""Project Vaiśravaṇa — human-gated live cutover gate (P2-37).

The self-improving loop (P2-36) can promote surfaces autonomously in PAPER, but
a promoted surface must NEVER reach LIVE capital without explicit human approval.
This module enforces that gate:

  - `request_deploy(surface_ver)` marks a promoted surface as PENDING human approval.
  - `approve(who)` records the approver + timestamp; only then is `can_deploy()` True.
  - `reject(who, note)` clears the pending request (stays in PAPER).
  - `can_deploy()` is the single source of truth the deploy path must consult.

Backed by the existing `results_log` table (approved_by column already exists) so
the approval is auditable. No network / no Telegram here — the deploy script
(decision) checks `can_deploy()` and refuses otherwise.

This is HUMAN-IN-THE-LOOP by design: the bot may optimize, but it may not put
real money at risk on its own.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


_PENDING_KEY = "live_cutover_pending"


@dataclass
class CutoverState:
    pending_ver: int | None
    approved: bool
    approved_by: str | None
    approved_at: str | None
    requested_at: str | None


class CutoverGate:
    """Human-gated live cutover. State lives in results_log as a tiny KV row."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS cutover_gate (
                 key TEXT PRIMARY KEY,
                 pending_ver INTEGER,
                 approved INTEGER DEFAULT 0,
                 approved_by TEXT,
                 approved_at TEXT,
                 requested_at TEXT
            )"""
        )
        self.conn.commit()

    def request_deploy(self, surface_ver: int, requested_at: str | None = None) -> None:
        """Mark surface `surface_ver` as PENDING human approval."""
        from sentinel import _now_iso
        self.conn.execute(
            """INSERT INTO cutover_gate (key, pending_ver, approved, approved_by,
                                         approved_at, requested_at)
               VALUES (?,?,0,NULL,NULL,?)
               ON CONFLICT(key) DO UPDATE SET
                 pending_ver=excluded.pending_ver, approved=0,
                 approved_by=NULL, approved_at=NULL, requested_at=excluded.requested_at""",
            (_PENDING_KEY, surface_ver, requested_at or _now_iso()),
        )
        self.conn.commit()

    def approve(self, who: str, approved_at: str | None = None) -> None:
        """Human approval. Without this, can_deploy() is False."""
        from sentinel import _now_iso
        self.conn.execute(
            """UPDATE cutover_gate SET approved=1, approved_by=?, approved_at=?
               WHERE key=?""",
            (who, approved_at or _now_iso(), _PENDING_KEY),
        )
        self.conn.commit()

    def reject(self, who: str, note: str = "") -> None:
        """Reject the pending cutover — surface stays PAPER-only."""
        self.conn.execute(
            """UPDATE cutover_gate SET approved=0, pending_ver=NULL,
               approved_by=?, approved_at=NULL WHERE key=?""",
            (f"{who}: {note}", _PENDING_KEY),
        )
        self.conn.commit()

    def state(self) -> CutoverState:
        row = self.conn.execute(
            "SELECT pending_ver, approved, approved_by, approved_at, requested_at "
            "FROM cutover_gate WHERE key=?", (_PENDING_KEY,)
        ).fetchone()
        if not row:
            return CutoverState(None, False, None, None, None)
        return CutoverState(
            pending_ver=row["pending_ver"],
            approved=bool(row["approved"]),
            approved_by=row["approved_by"],
            approved_at=row["approved_at"],
            requested_at=row["requested_at"],
        )

    def can_deploy(self) -> bool:
        """Single source of truth for the deploy path. False unless a human approved."""
        return self.state().approved

    def reset(self) -> None:
        self.conn.execute("DELETE FROM cutover_gate WHERE key=?", (_PENDING_KEY,))
        self.conn.commit()
