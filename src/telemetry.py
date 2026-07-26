"""Project Vaiśravaṇa — central telemetry writer (doc 30 §4, doc 22).

RULE (doc 30 §4 footer): the logger FAILS LOUD. A telemetry write error must halt
entries — never swallow it. `TelemetryError` is raised on any DB failure and the
caller (orchestrator) must stop opening new positions until resolved.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


class TelemetryError(RuntimeError):
    """Raised when a telemetry write fails. Callers MUST halt new entries."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Telemetry:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _exec(self, sql: str, params: tuple) -> None:
        try:
            self.conn.execute(sql, params)
            self.conn.commit()
        except sqlite3.Error as e:            # fail loud (doc 30 §4)
            raise TelemetryError(f"telemetry write failed: {e}") from e

    def exec_event(
        self,
        correlation_id: str,
        pair: str,
        tf: str,
        event: str,                 # ORDER_SENT / FILL / REPAIR / VALIDATION_SKIP / CANCEL / SL_PLACED / CLOSE
        order_type: str = "",
        side: str = "",
        price: float | None = None,
        qty: float | None = None,
        status: str = "",
        error_cat: str = "",        # AUTH / RATE_LIMIT / SERVER / NETWORK / ORDER_REJECT (doc 32 L7)
        latency_ms: int | None = None,
        config_ver: str = "surface-v1",
    ) -> None:
        self._exec(
            """INSERT INTO exec_events
               (correlation_id, ts, pair, tf, event, order_type, side, price, qty,
                status, error_cat, latency_ms, config_ver)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (correlation_id, _now_iso(), pair, tf, event, order_type, side,
             price, qty, status, error_cat, latency_ms, config_ver),
        )

    def health(
        self,
        check: str,                 # feed / db / exchange / margin / registry ...
        status: str,                # OK / WARN / FAIL
        detail: str = "",
        correlation_id: str = "",
    ) -> None:
        self._exec(
            'INSERT INTO system_health (ts, correlation_id, "check", status, detail) '
            "VALUES (?,?,?,?,?)",
            (_now_iso(), correlation_id, check, status, detail),
        )
