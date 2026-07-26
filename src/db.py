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


def _fmt_bytes(n: int) -> str:
    """Human-readable byte size (B / KB / MB / GB)."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def db_stats(conn: sqlite3.Connection, db_path: str | Path | None = None) -> dict:
    """Return operational DB stats so the owner can watch size + activity.

    - counts:      row count per telemetry table (doc 30 §4 order)
    - total_rows:  sum of all table rows
    - size_bytes:  on-disk footprint of the main DB file + WAL + SHM sidecars
    - size_human:  pretty-printed size (e.g. "1.4 MB")
    - overall:     {n_closed, n_wins, n_losses, win_rate_pct} across ALL trade_logs
                   (a single portfolio-wide win rate, not per pair/tf/side)

    db_path is optional: when omitted, the size is read from the connection's
    'main' database file via PRAGMA (page_count * page_size), which also counts
    freelist pages, so it matches the true allocated footprint.
    """
    counts: dict[str, int] = {}
    for t in TABLES:
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error:
            counts[t] = 0
    total_rows = sum(counts.values())

    # overall (portfolio-wide) win rate across every closed trade
    n_closed = n_wins = 0
    try:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(win), 0) FROM trade_logs "
            "WHERE ts_fully_closed IS NOT NULL OR close_reason IS NOT NULL"
        ).fetchone()
        n_closed, n_wins = int(row[0]), int(row[1])
    except sqlite3.Error:
        pass
    n_losses = max(0, n_closed - n_wins)
    win_rate_pct = (100.0 * n_wins / n_closed) if n_closed else 0.0

    # on-disk size: prefer real files (main + -wal + -shm); fall back to PRAGMA
    size_bytes = 0
    if db_path is not None and str(db_path) not in (":memory:", ""):
        p = Path(db_path)
        for suffix in ("", "-wal", "-shm"):
            fp = Path(str(p) + suffix)
            try:
                if fp.exists():
                    size_bytes += fp.stat().st_size
            except OSError:
                pass
    if size_bytes == 0:
        try:
            pc = conn.execute("PRAGMA page_count").fetchone()[0]
            ps = conn.execute("PRAGMA page_size").fetchone()[0]
            size_bytes = int(pc) * int(ps)
        except sqlite3.Error:
            size_bytes = 0

    return {
        "counts": counts,
        "total_rows": total_rows,
        "size_bytes": size_bytes,
        "size_human": _fmt_bytes(size_bytes),
        "overall": {
            "n_closed": n_closed,
            "n_wins": n_wins,
            "n_losses": n_losses,
            "win_rate_pct": round(win_rate_pct, 1),
        },
    }


# Table that receives one row per (pair, strategy) per decision tick — by far the
# highest-write table in the system (≈15 pairs × 3 strategies × 60s ≈ 65k rows/day).
# Trade/execution logs are kept indefinitely (they drive evaluation + promotion), but
# the decision audit trail is only useful for recent diagnostics, so it is pruned.
DECISIONS_LOG_RETENTION_DAYS = 1


def purge_old_decisions(
    conn: sqlite3.Connection,
    retention_days: int = DECISIONS_LOG_RETENTION_DAYS,
    now: str | None = None,
) -> int:
    """Delete `decisions_log` rows older than `retention_days` (default 1) by UTC `ts`.

    `ts` is ISO-8601 UTC TEXT (e.g. '2026-07-26T16:44:01+00:00'). The stored value carries a
    '+00:00' offset, so the column is wrapped in datetime(ts) for a correct comparison against
    datetime('now'/'-N days') — a raw `ts <` compare fails because of the suffix.
    Returns rows deleted. Idempotent and safe: a missing table or empty result is a no-op.
    """
    cutoff = now or datetime.now(timezone.utc).isoformat()
    try:
        cur = conn.execute(
            "DELETE FROM decisions_log WHERE datetime(ts) < datetime(?, '-%d days')"
            % retention_days,
            (cutoff,),
        )
        deleted = cur.rowcount
        conn.commit()
        # reclaim the freed pages so the file actually shrinks (doc 30: DB growth awareness)
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError:
            pass  # VACUUM can fail under concurrent WAL writers; non-fatal
        return deleted
    except sqlite3.Error:
        return 0


def wipe_db(conn: sqlite3.Connection) -> int:
    """Delete EVERY row from all telemetry tables (decisions_log, trade_logs, results_log,
    exec_events, system_health) — a fresh start. Keeps the schema (idempotent, safe to
    re-run). Used by the `/clean` Telegram command. Returns total rows deleted.

    NOTE: this is NOT called automatically — only on explicit owner `/clean`. Trade and
    execution logs are intentionally destroyed; the next loop iteration reloads zero open
    positions and starts with a blank win rate.
    """
    total = 0
    try:
        for t in TABLES:
            try:
                cur = conn.execute(f"DELETE FROM {t}")
                total += cur.rowcount
            except sqlite3.Error:
                pass
        conn.commit()
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError:
            pass
    except sqlite3.Error:
        return total
    return total
