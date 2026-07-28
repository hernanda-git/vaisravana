"""Tests for the telemetry store schema (doc 30 §4)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from db import TABLES, all_tables_present, init_db, table_exists  # noqa: E402


def test_init_db_creates_all_tables(tmp_path):
    db = tmp_path / "test.db"
    conn = init_db(db)
    try:
        assert all_tables_present(conn), "not all tables present"
        for t in TABLES:
            assert table_exists(conn, t), f"missing {t}"
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_path):
    conn = init_db("foo.db")
    conn.close()
    # second call must not error / drop data
    conn2 = init_db("foo.db")
    try:
        assert all_tables_present(conn2)
    finally:
        conn2.close()
    Path("foo.db").unlink(missing_ok=True)


def test_trade_logs_insert_roundtrip(tmp_path):
    conn = init_db("bar.db")
    try:
        conn.execute(
            "INSERT INTO trade_logs (trade_id, correlation_id, pair, tf, side, win, loss) "
            "VALUES (?,?,?,?,?,?,?)",
            ("T-1", "C-1", "BTCUSDT", "5m", "BUY", 1, 0),
        )
        conn.commit()
        row = conn.execute(
            "SELECT trade_id, side, win, loss FROM trade_logs WHERE trade_id=?", ("T-1",)
        ).fetchone()
        assert row is not None
        assert row["side"] == "BUY" and row["win"] == 1 and row["loss"] == 0
    finally:
        conn.close()
    Path("bar.db").unlink(missing_ok=True)


def test_decisions_log_has_confidence(tmp_path):
    conn = init_db("baz.db")
    try:
        conn.execute(
            "INSERT INTO decisions_log (id, correlation_id, pair, tf, total_score, "
            "confidence_pct, decision, gate_a_pass, gate_b_pass) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("D-1", "C-1", "BTCUSDT", "5m", 0.91, 91.0, "ENTRY", 1, 1),
        )
        conn.commit()
        row = conn.execute(
            "SELECT confidence_pct, decision FROM decisions_log WHERE id=?", ("D-1",)
        ).fetchone()
        assert row["confidence_pct"] == 91.0
        assert row["decision"] == "ENTRY"
    finally:
        conn.close()
    Path("baz.db").unlink(missing_ok=True)
