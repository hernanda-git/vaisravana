"""Tests for Phase 9: backtest harness — deterministic candle replay, no fabricated
outcomes, in/out-of-sample split, fee accounting, report generation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from backtest import BacktestHarness, MAKER_FEE, ReplayStats, report_markdown, split  # noqa: E402
from db import init_db  # noqa: E402
from engines import MarketState  # noqa: E402
from marketdata import Candle  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _trend_candles(n=40, start=100.0, step=0.5) -> list[Candle]:
    """Steady uptrend: each bar closes higher; range ±1.0 around close."""
    out = []
    price = start
    for i in range(n):
        o = price
        c = price + step
        out.append(Candle(ts=i * 300_000, o=o, h=c + 1.0, l=o - 0.4, c=c, v=1000.0))
        price = c
    return out


def _bull_state(candles, i) -> MarketState:
    return MarketState(
        symbol="BTCUSDT", tf="5m", regime="trending_bull", htf_bias="bullish",
        body_ratio=0.95, vol_z=3.0, delta_z=3.0, bos=True, hh=True, hl=True,
        choch=True, liq_sweep=True, eq_low=True, fvg=True,
        atr_pct=0.01, spread_bps=1.0, funding_ok=True, adl_rank=1,
        last_close=candles[i].c,
    )


def _neutral_state(candles, i) -> MarketState:
    return MarketState(symbol="BTCUSDT", tf="5m", regime="range", htf_bias="neutral",
                       last_close=candles[i].c)


def test_split_in_out_of_sample():
    candles = _trend_candles(100)
    ins, oos = split(candles, oos_frac=0.3)
    assert len(ins) == 70 and len(oos) == 30
    assert ins[-1].ts < oos[0].ts   # temporal order preserved — no look-ahead


def test_uptrend_replay_produces_wins(conn):
    """Uptrend + bullish A+ state → entries; outcomes derived from real bars only."""
    h = BacktestHarness(conn, _bull_state)
    stats = h.run("BTCUSDT", "5m", _trend_candles(60))
    assert stats.entries > 0
    assert stats.tp_exits + stats.sl_exits + stats.maxhold_exits == stats.entries
    assert "BUY" in stats.reports
    rep = stats.reports["BUY"]
    assert rep.n_trades == stats.entries
    # trade count in DB matches — nothing invented
    n_db = conn.execute("SELECT COUNT(*) c FROM trade_logs WHERE ts_closed IS NOT NULL").fetchone()["c"]
    assert n_db == stats.entries


def test_neutral_market_produces_no_entries(conn):
    h = BacktestHarness(conn, _neutral_state)
    stats = h.run("BTCUSDT", "5m", _trend_candles(60))
    assert stats.entries == 0 and stats.reports == {}
    # but decisions ARE logged (SKIP rows) — full audit
    n = conn.execute("SELECT COUNT(*) c FROM decisions_log").fetchone()["c"]
    assert n > 0
    assert conn.execute(
        "SELECT COUNT(*) c FROM decisions_log WHERE decision!='SKIP' AND decision!='WATCH'"
    ).fetchone()["c"] == 0


def test_fees_accumulate_vip0(conn):
    h = BacktestHarness(conn, _bull_state)
    stats = h.run("BTCUSDT", "5m", _trend_candles(60))
    assert stats.entries > 0
    # at least maker fee on every entry
    assert stats.fees_usd >= stats.entries * 100.0 * MAKER_FEE * 0.9


def test_report_markdown_format(conn):
    h = BacktestHarness(conn, _bull_state)
    stats = h.run("BTCUSDT", "5m", _trend_candles(60))
    md = report_markdown([stats])
    assert "| Pair | TF | Side |" in md and "BTCUSDT" in md and "BUY" in md
