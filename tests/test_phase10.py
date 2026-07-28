"""Tests for Phase 10: monitoring dashboard + human alert stream."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from dashboard import alerts, render, snapshot  # noqa: E402
from db import init_db  # noqa: E402
from lifecycle import TradeLifecycle  # noqa: E402
from telemetry import Telemetry  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _trade(lc, i, side="BUY", win=True, close=True):
    t = lc.open(f"c{i}", "BTCUSDT", "5m", side, entry_price=100.0, size=1.0,
                leverage=2.0, sl_price=99.0 if side == "BUY" else 101.0,
                tp_price=101.05 if side == "BUY" else 98.95)
    if close:
        if win:
            lc.close(t, exit_price=101.05 if side == "BUY" else 98.95, close_reason="TP")
        else:
            lc.close(t, exit_price=99.0 if side == "BUY" else 101.0, close_reason="SL")
    return t


def test_snapshot_per_key_and_open_positions(conn):
    lc = TradeLifecycle(conn)
    for i in range(3):
        _trade(lc, i, win=True)
    _trade(lc, 3, side="SELL", win=False)
    _trade(lc, 4, close=False)                      # still open
    snap = snapshot(conn)
    assert snap.total_closed == 4 and snap.total_open == 1
    buy = next(k for k in snap.keys if k.side == "BUY")
    sell = next(k for k in snap.keys if k.side == "SELL")
    assert buy.win_rate_pct == 100.0 and buy.open_position
    assert sell.win_rate_pct == 0.0 and not sell.open_position


def test_render_markdown(conn):
    lc = TradeLifecycle(conn)
    _trade(lc, 0)
    md = render(snapshot(conn))
    assert "Vessavaṇa" in md and "BTCUSDT" in md and "100.0%" in md


def test_alert_stream_promotions_and_incidents(conn):
    conn.execute(
        """INSERT INTO results_log (ts, cycle, pair, tf, kind, review)
           VALUES ('t','c','BTCUSDT','5m','IMPROVEMENT','PROMOTED v2')""")
    conn.execute(
        """INSERT INTO results_log (ts, cycle, pair, tf, kind, review)
           VALUES ('t','c','BTCUSDT','5m','REVIEW','no change')""")   # not alertable
    Telemetry(conn).health("kill_switch", "FAIL", detail="DAILY_DD")
    Telemetry(conn).health("feed", "OK")
    out = alerts(conn)
    kinds = [a.kind for a in out]
    assert kinds.count("IMPROVEMENT") == 1 and kinds.count("FAIL") == 1
    assert "REVIEW" not in kinds and len(out) == 2


def test_alert_cursor_no_duplicates(conn):
    Telemetry(conn).health("feed", "FAIL", detail="frozen")
    first = alerts(conn)
    assert len(first) == 1
    again = alerts(conn, since_health_id=first[0].row_id)
    assert again == []
