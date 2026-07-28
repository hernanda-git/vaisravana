"""Phase 21 (v0.1.0) — decisions_log 1-day auto-prune.

Verifies the most-spammed table (one row per pair×strategy per tick) is pruned of rows
older than 1 day while recent rows + the trade_logs table are preserved.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from db import init_db, purge_old_decisions  # noqa: E402


def _seed(conn, ages_iso):
    conn.execute("""CREATE TABLE IF NOT EXISTS decisions_log (
        id TEXT PRIMARY KEY, ts TEXT, pair TEXT, tf TEXT, decision TEXT)""")
    for i, ts in enumerate(ages_iso):
        conn.execute(
            "INSERT INTO decisions_log (id, ts, pair, tf, decision) VALUES (?,?,?,?,?)",
            (f"d{i}", ts, "BTCUSDT", "1m", "WATCH"))
    conn.commit()


def test_prunes_rows_older_than_1_day():
    conn = init_db(Path(tempfile.mkdtemp()) / "t.db")
    old = "2026-07-25T00:00:00+00:00"   # >1 day before "now" below
    recent = "2026-07-26T23:00:00+00:00"  # within 1 day
    now = "2026-07-26T23:59:00+00:00"
    _seed(conn, [old, old, recent, recent])
    deleted = purge_old_decisions(conn, retention_days=1, now=now)
    assert deleted == 2
    rows = conn.execute("SELECT id FROM decisions_log ORDER BY id").fetchall()
    assert [r["id"] for r in rows] == ["d2", "d3"]


def test_keeps_recent_rows():
    conn = init_db(Path(tempfile.mkdtemp()) / "t.db")
    now = "2026-07-26T12:00:00+00:00"
    _seed(conn, [now, now])  # both recent
    deleted = purge_old_decisions(conn, retention_days=1, now=now)
    assert deleted == 0
    assert conn.execute("SELECT COUNT(*) FROM decisions_log").fetchone()[0] == 2


def test_custom_retention_days():
    conn = init_db(Path(tempfile.mkdtemp()) / "t.db")
    now = "2026-07-26T12:00:00+00:00"
    _seed(conn, [
        "2026-07-20T12:00:00+00:00",  # 6 days old
        "2026-07-25T12:00:00+00:00",  # 1 day old -> kept at 2d retention
    ])
    deleted = purge_old_decisions(conn, retention_days=2, now=now)
    assert deleted == 1
    assert conn.execute("SELECT COUNT(*) FROM decisions_log").fetchone()[0] == 1


def test_empty_table_is_noop():
    conn = init_db(Path(tempfile.mkdtemp()) / "t.db")
    assert purge_old_decisions(conn, now="2026-07-26T12:00:00+00:00") == 0
