"""Tests for Phase 6: evaluation engine — rolling metrics per (pair,tf,side),
composite health, attribution (false positive/negative)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from db import init_db  # noqa: E402
from evaluation import (  # noqa: E402
    EvalTargets,
    evaluate,
    false_negatives,
    false_positives,
    regime_attribution,
)
from lifecycle import TradeLifecycle  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _run_seq(lc, outcomes, side="BUY", pair="BTCUSDT", tf="5m", regime="trending_bull",
             decision_ids=None):
    """outcomes: list of 'W'/'L'. TP=+1.05R, SL=-1R with entry100/sl99(or101)/tp101.05."""
    for i, o in enumerate(outcomes):
        t = lc.open(f"c{i}", pair, tf, side, entry_price=100.0, size=1.0, leverage=2.0,
                    sl_price=99.0 if side == "BUY" else 101.0,
                    tp_price=101.05 if side == "BUY" else 98.95,
                    regime=regime,
                    decision_id=(decision_ids[i] if decision_ids else ""))
        if o == "W":
            exit_p = 101.05 if side == "BUY" else 98.95
            lc.close(t, exit_price=exit_p, close_reason="TP")
        else:
            exit_p = 99.0 if side == "BUY" else 101.0
            lc.close(t, exit_price=exit_p, close_reason="SL")


def test_known_sequence_yields_expected_wr_and_expectancy(conn):
    """18W/2L: WR=90%, expectancy = (18*1.05 - 2*1.0)/20 = +0.845R."""
    lc = TradeLifecycle(conn)
    _run_seq(lc, ["W"] * 18 + ["L"] * 2)
    rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    assert rep.n_trades == 20
    assert rep.win_rate_pct == pytest.approx(90.0)
    assert rep.expectancy_r == pytest.approx(0.845, abs=0.01)
    assert rep.passes["win_rate"] and rep.passes["expectancy"]
    assert rep.profit_factor > 1.2 and rep.passes["profit_factor"]


def test_sides_evaluated_independently(conn):
    """LONG 100% / SHORT 0% must NOT merge (doc 30 §5)."""
    lc = TradeLifecycle(conn)
    _run_seq(lc, ["W"] * 5, side="BUY")
    _run_seq(lc, ["L"] * 5, side="SELL")
    long_rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    short_rep = evaluate(conn, "BTCUSDT", "5m", "SELL")
    assert long_rep.win_rate_pct == 100.0
    assert short_rep.win_rate_pct == 0.0


def test_below_gate_fails_headline(conn):
    lc = TradeLifecycle(conn)
    _run_seq(lc, ["W"] * 8 + ["L"] * 2)   # 80% < 85%
    rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    assert not rep.passes["win_rate"] and not rep.all_pass


def test_composite_health_monotonic(conn):
    """Better book → higher health score (anti reward-hack composite, doc 23)."""
    lc = TradeLifecycle(conn)
    _run_seq(lc, ["W"] * 18 + ["L"] * 2)
    good = evaluate(conn, "BTCUSDT", "5m", "BUY").health()
    _run_seq(lc, ["L"] * 20, pair="ETHUSDT")
    bad = evaluate(conn, "ETHUSDT", "5m", "BUY").health()
    assert good > bad


def test_regime_attribution(conn):
    lc = TradeLifecycle(conn)
    _run_seq(lc, ["W"] * 4, regime="trending_bull")
    _run_seq(lc, ["L"] * 4, regime="range")
    attr = regime_attribution(conn, "BTCUSDT", "5m", "BUY")
    assert attr["trending_bull"] > 0 > attr["range"]


def test_false_positive_counting(conn):
    """ENTRY decisions that closed at SL are false positives (doc 23)."""
    lc = TradeLifecycle(conn)
    # register 3 ENTRY decisions
    for i in range(3):
        conn.execute(
            "INSERT INTO decisions_log (id, pair, tf, decision) VALUES (?,?,?,?)",
            (f"d{i}", "BTCUSDT", "5m", "ENTRY"),
        )
    conn.commit()
    _run_seq(lc, ["W", "L", "L"], decision_ids=["d0", "d1", "d2"])
    assert false_positives(conn, "BTCUSDT", "5m", "BUY") == 2


def test_false_negative_counting(conn):
    """SKIPs that shadow says would have profited (doc 23)."""
    for i in range(4):
        conn.execute(
            "INSERT INTO decisions_log (id, pair, tf, decision) VALUES (?,?,?,?)",
            (f"s{i}", "BTCUSDT", "5m", "SKIP"),
        )
    conn.commit()
    shadow = {"s0": 1.0, "s1": -0.5, "s2": 0.3, "s3": 0.0}
    assert false_negatives(conn, "BTCUSDT", "5m", shadow) == 2


def test_eval_report_markdown(conn):
    lc = TradeLifecycle(conn)
    _run_seq(lc, ["W"] * 18 + ["L"] * 2)
    md = evaluate(conn, "BTCUSDT", "5m", "BUY").to_markdown()
    assert "Win Rate" in md and "BTCUSDT 5m BUY" in md and "✅" in md
