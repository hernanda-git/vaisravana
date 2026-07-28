"""Tests for Phase 30: R:R floor lock (v0.0.24 P0-30).

Makes a sub-2:1 live OPEN trade structurally detectable, not shippable
undetected. Mirrors the 2026-07-27 BTCUSDT 1m 1.50:1 transient case.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import sqlite3

import pytest

from db import init_db
from rr_scan import trade_rr, scan_open_rr, assert_rr_floor, FLOOR


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "rr.db")


def _open(conn, pair="BTCUSDT", tf="1m", side="BUY",
          entry=65389.2, sl=65360.82, tp=65433.79):
    # tp chosen so (tp-entry)/(entry-sl) = RR
    conn.execute(
        "INSERT INTO trade_logs (trade_id, pair, tf, side, entry_price, "
        "sl_price, tp_price, ts_closed) VALUES (?,?,?,?,?,?,?,?)",
        (f"t-{pair}-{tf}", pair, tf, side, entry, sl, tp, None),
    )
    conn.commit()


def test_trade_rr_buy_positive():
    assert trade_rr("BUY", 100.0, 99.0, 102.0) == pytest.approx(2.0)


def test_trade_rr_sell_positive():
    assert trade_rr("SELL", 100.0, 101.0, 98.0) == pytest.approx(2.0)


def test_trade_rr_zero_risk_returns_zero():
    # missing/invalid SL (risk <= 0) => 0.0, never a false pass
    assert trade_rr("BUY", 100.0, 100.0, 102.0) == 0.0


def test_scan_finds_sub_2_1_open_trade(conn):
    # BTC 1m 1.50:1 (the observed transient)
    _open(conn, entry=65389.2, sl=65360.8214, tp=65389.2 + (65389.2 - 65360.8214) * 1.5)
    bad = scan_open_rr(conn, FLOOR)
    assert len(bad) == 1
    assert bad[0]["pair"] == "BTCUSDT"
    assert bad[0]["rr"] == pytest.approx(1.5, abs=0.001)


def test_scan_clean_when_all_above_floor(conn):
    _open(conn, tf="1h", entry=100.0, sl=99.0, tp=102.0)
    _open(conn, pair="ETHUSDT", entry=100.0, sl=99.0, tp=102.0)
    assert scan_open_rr(conn, FLOOR) == []


def test_assert_rr_floor_raises_on_violation(conn):
    _open(conn, entry=65389.2, sl=65360.8214,
          tp=65389.2 + (65389.2 - 65360.8214) * 1.5)
    with pytest.raises(AssertionError):
        assert_rr_floor(conn, FLOOR)


def test_assert_rr_floor_passes_when_clean(conn):
    _open(conn, tf="1h", entry=100.0, sl=99.0, tp=102.0)
    assert assert_rr_floor(conn, FLOOR) is None  # no raise
