"""Project Vaiśravaṇa — telemetry store schema (doc 30 §4).

Implements the mandatory logging schema from docs/30-concrete-spec.md §4:
  - trade_logs      (record every win/loss on unreal, full lifecycle)
  - decisions_log   (internal decision + confidence_pct; replaces external signal)
  - results_log     (historical meta-loop trail: evaluation/reasoning/.../review)
  - exec_events     (order lifecycle; correlation_id traceable)
  - system_health   (periodic/subsystem health)

Column NAMES and semantics follow doc 30 §4 verbatim. Storage TYPES are mapped to
SQLite-compatible ones (doc wrote `TIMESTAMPTZ` conceptually; SQLite stores ISO-8601
strings as TEXT). No external dependency (stdlib sqlite3).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# SQL mirrors docs/30-concrete-spec.md §4. Timestamp columns use TEXT (ISO-8601)
# because SQLite has no TIMESTAMPTZ type.
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trade_logs (
  trade_id        TEXT PRIMARY KEY,
  correlation_id  TEXT,
  pair            TEXT, tf TEXT,
  side            TEXT,
  ts_opened       TEXT,
  ts_filled       TEXT,
  ts_tp_hit       TEXT,
  ts_partial_close TEXT,
  ts_fully_closed TEXT,
  ts_closed       TEXT,
  win             INTEGER,
  loss            INTEGER,
  win_pct         REAL,
  loss_pct        REAL,
  pnl_usd         REAL, pnl_pct REAL, r_multiple REAL,
  entry_price     REAL, exit_price REAL,
  size            REAL, leverage REAL,
  sl_price        REAL, tp_price REAL,
  close_reason    TEXT,
  hold_min        REAL, mfe_r REAL, mae_r REAL,
  spread_bps      REAL, fill_type TEXT, regime TEXT,
  decision_id     TEXT,
  scores_json     TEXT, config_ver TEXT, notes TEXT
);

CREATE TABLE IF NOT EXISTS decisions_log (
  id             TEXT PRIMARY KEY,
  correlation_id TEXT,
  ts             TEXT,
  pair           TEXT, tf TEXT,
  regime         TEXT,
  scores_json    TEXT,
  total_score    REAL,
  confidence_pct REAL,
  decision       TEXT,
  gate_a_pass    INTEGER, gate_b_pass INTEGER,
  reason         TEXT, config_ver TEXT
);

CREATE TABLE IF NOT EXISTS results_log (
  id              INTEGER PRIMARY KEY,
  ts              TEXT,
  cycle           TEXT,
  pair            TEXT, tf TEXT,
  kind            TEXT,
  content_json    TEXT,
  eval_summary    TEXT,
  reasoning_5w1h  TEXT,
  thinking        TEXT,
  correction      TEXT,
  improvement     TEXT,
  review          TEXT,
  config_ver_from TEXT, config_ver_to TEXT,
  approved_by     TEXT
);

CREATE TABLE IF NOT EXISTS exec_events (
  id             INTEGER PRIMARY KEY,
  correlation_id TEXT,
  ts             TEXT,
  pair           TEXT, tf TEXT,
  event          TEXT,
  order_type     TEXT, side TEXT,
  price          REAL, qty REAL,
  status         TEXT,
  error_cat      TEXT,
  latency_ms     INTEGER, config_ver TEXT
);

CREATE TABLE IF NOT EXISTS system_health (
  id             INTEGER PRIMARY KEY,
  ts             TEXT,
  correlation_id TEXT,
  "check"        TEXT,
  status         TEXT,
  detail         TEXT
);
"""

# Canonical table order (doc 30 §4).
TABLES = ("trade_logs", "decisions_log", "results_log", "exec_events", "system_health")


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a sqlite connection with row access by name + FK off (sqlite default)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path = "vaisravana.db") -> sqlite3.Connection:
    """Create all telemetry tables if absent. Returns an open connection.

    Idempotent: re-running does not drop or alter existing tables.
    """
    conn = get_connection(db_path)
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def all_tables_present(conn: sqlite3.Connection) -> bool:
    return all(table_exists(conn, t) for t in TABLES)
