"""Tests for Phase 31: net-expectancy re-base (v0.0.24 P0-31).

Fixes F1: raw R-multiple is distorted by tight-SL pairs (small denominator
inflates R). Ranking + de-bleed must use NET expectancy$ (after fees), not R.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import sqlite3

import pytest

from db import init_db
from evaluation import evaluate, net_pair_ranking, EvalReport
from pair_excluder import PairExcluder


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "net.db")
    seq = {"n": 0}

    def add(pair, side, entry, sl, tp, pnl, fee, win, r_mult):
        seq["n"] += 1
        c.execute(
            "INSERT INTO trade_logs (trade_id, pair, tf, side, entry_price, "
            "sl_price, tp_price, fees_usd, pnl_usd, pnl_pct, r_multiple, win, "
            "ts_closed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"{pair}-{seq['n']}", pair, "1h", side, entry, sl, tp, fee, pnl,
             (pnl / entry * 100.0), r_mult,
             win, "2026-07-27T05:00:00+00:00"),
        )
        c.commit()

    # PEPE: 4W/8L. Winners ran via trailing-to-BE so their R is huge; losers R=-1.
    # Net $ is NEGATIVE (the F1 trap): high avg R but the pair actually loses money.
    for _ in range(4):
        add("1000PEPEUSDT", "BUY", 0.003, 0.00295, 0.0035, +0.00002, 0.00003, 1, +30.0)
    for _ in range(8):
        add("1000PEPEUSDT", "BUY", 0.003, 0.00295, 0.0035, -0.00004, 0.00003, 0, -1.0)
    # APE: 8W/4L, modest R, net$ POSITIVE.
    for _ in range(8):
        add("APEUSDT", "BUY", 0.15, 0.14, 0.17, +0.004, 0.0001, 1, +0.5)
    for _ in range(4):
        add("APEUSDT", "BUY", 0.15, 0.14, 0.17, -0.003, 0.0001, 0, -0.5)
    return c


def test_evaluate_returns_net_expectancy(conn):
    rep = evaluate(conn, "APEUSDT", "1h", "BUY")
    assert isinstance(rep, EvalReport)
    assert rep.net_expectancy_usd > 0.0
    # net pass guardrail present
    assert "net_expectancy" in rep.passes


def test_net_ranking_puts_profitable_pair_above_lossmaking(conn):
    ranking = net_pair_ranking(conn, min_trades=10)
    pairs = [r["pair"] for r in ranking]
    assert "APEUSDT" in pairs and "1000PEPEUSDT" in pairs
    # APE (positive net$) must outrank PEPE (negative net$), regardless of R
    ape = next(r for r in ranking if r["pair"] == "APEUSDT")
    pepe = next(r for r in ranking if r["pair"] == "1000PEPEUSDT")
    assert ape["net_expectancy_usd"] > pepe["net_expectancy_usd"]
    # and PEPE's raw R would have fooled a naive sorter:
    assert ape["avg_r_multiple"] < pepe["avg_r_multiple"]  # proves R is misleading


def test_excluder_drops_negative_net_pair_via_conn(conn, tmp_path):
    ex = PairExcluder(path=tmp_path / "ex.json")
    ex.reset()
    # simulate recording the closes feeding net expectancy through the real DB
    for r in conn.execute(
        "SELECT pair, win FROM trade_logs WHERE ts_closed IS NOT NULL"
    ).fetchall():
        ex.record_close(r["pair"], bool(r["win"]), conn=conn)
    # PEPE net$ negative => excluded; APE positive => kept
    assert ex.is_excluded("1000PEPEUSDT")
    assert not ex.is_excluded("APEUSDT")
