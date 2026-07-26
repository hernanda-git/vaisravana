"""Tests for Phase 5: trade lifecycle, rolling win/loss metrics, fail-loud telemetry."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from db import init_db  # noqa: E402
from lifecycle import TradeLifecycle  # noqa: E402
from telemetry import Telemetry, TelemetryError  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _open(lc, side="BUY", pair="BTCUSDT", tf="5m", corr="c1"):
    return lc.open(corr, pair, tf, side, entry_price=100.0, size=1.0,
                   leverage=2.0, sl_price=99.0 if side == "BUY" else 101.0,
                   tp_price=101.05 if side == "BUY" else 98.95)


def test_full_lifecycle_writes_all_timestamps(conn):
    lc = TradeLifecycle(conn)
    t = _open(lc)
    lc.mark_tp_hit(t.trade_id)
    lc.mark_partial_close(t.trade_id)
    res = lc.close(t, exit_price=101.05, close_reason="TP")
    row = conn.execute("SELECT * FROM trade_logs WHERE trade_id=?", (t.trade_id,)).fetchone()
    for col in ("ts_opened", "ts_filled", "ts_tp_hit", "ts_partial_close",
                "ts_fully_closed", "ts_closed"):
        assert row[col], f"{col} missing"
    assert row["win"] == 1 and row["loss"] == 0
    assert row["close_reason"] == "TP"
    assert res["r_multiple"] == pytest.approx(1.05, abs=0.01)


def test_loss_is_logged_too(conn):
    """doc 30 §4: SETIAP trade (menang ATAUPUN kalah) wajib masuk."""
    lc = TradeLifecycle(conn)
    t = _open(lc)
    res = lc.close(t, exit_price=99.0, close_reason="SL")
    row = conn.execute("SELECT win, loss, pnl_usd FROM trade_logs WHERE trade_id=?",
                       (t.trade_id,)).fetchone()
    assert row["win"] == 0 and row["loss"] == 1 and row["pnl_usd"] < 0
    assert res["r_multiple"] == pytest.approx(-1.0, abs=0.01)


def test_short_pnl_sign_correct(conn):
    """SHORT profit when price falls — SELL is first-class, not mirrored."""
    lc = TradeLifecycle(conn)
    t = _open(lc, side="SELL")
    res = lc.close(t, exit_price=98.95, close_reason="TP")
    assert res["win"] == 1 and res["pnl_usd"] > 0


def test_rolling_win_pct_per_pair_tf_side(conn):
    """W,W,L sequence → 66.67% on the last row; separate counter per side."""
    lc = TradeLifecycle(conn)
    for exit_price, reason in ((101.0, "TP"), (102.0, "TP"), (99.0, "SL")):
        t = _open(lc)
        res = lc.close(t, exit_price=exit_price, close_reason=reason)
    assert res["win_pct"] == pytest.approx(66.6667, abs=0.01)
    assert res["loss_pct"] == pytest.approx(33.3333, abs=0.01)
    # SHORT counter independent (doc 30 §5: per pair×tf×side)
    t = _open(lc, side="SELL")
    res_s = lc.close(t, exit_price=98.0, close_reason="TP")
    assert res_s["win_pct"] == 100.0


def test_telemetry_exec_event_and_health(conn):
    tel = Telemetry(conn)
    tel.exec_event("c1", "BTCUSDT", "5m", "ORDER_SENT", order_type="LIMIT",
                   side="BUY", price=100.0, qty=1.0, status="NEW")
    tel.health("feed", "FAIL", detail="frozen 3 candles")
    ev = conn.execute("SELECT * FROM exec_events").fetchone()
    assert ev["event"] == "ORDER_SENT" and ev["correlation_id"] == "c1"
    h = conn.execute('SELECT * FROM system_health').fetchone()
    assert h["check"] == "feed" and h["status"] == "FAIL"


def test_telemetry_fails_loud_on_broken_connection(conn):
    """doc 30 §4 footer: logger error must halt entry, not be swallowed."""
    tel = Telemetry(conn)
    conn.close()
    with pytest.raises(TelemetryError):
        tel.exec_event("c1", "BTCUSDT", "5m", "ORDER_SENT")


def test_lifecycle_fails_loud_on_broken_connection(conn):
    lc = TradeLifecycle(conn)
    conn.close()
    with pytest.raises(TelemetryError):
        _open(lc)
