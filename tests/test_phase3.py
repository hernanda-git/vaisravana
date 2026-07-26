"""Tests for Phase 3: two-layer gate + decision orchestrator + decisions_log."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from db import init_db  # noqa: E402
from decision import DecisionOrchestrator  # noqa: E402
from engines import MarketState  # noqa: E402
from gate import TwoLayerGate  # noqa: E402


def _bull() -> MarketState:
    return MarketState(
        symbol="BTCUSDT", tf="5m", regime="trending_bull", htf_bias="bullish",
        body_ratio=0.95, vol_z=3.0, delta_z=3.0, bos=True, hh=True, hl=True,
        choch=True, liq_sweep=True, eq_low=True, fvg=True, atr_pct=0.01,
        spread_bps=1.0, funding_ok=True, adl_rank=1,
    )


def _chop() -> MarketState:
    return MarketState(symbol="DOGEUSDT", tf="5m", regime="range", htf_bias="neutral")


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


# --- Gate unit behaviour (doc 30 §3, doc 32 L1/L5) ---

def test_gate_b_rejects_reversed_sl_long():
    g = TwoLayerGate()
    ok, reasons = g.gate_b(side="BUY", sl_price=105.0, entry_price=100.0, leverage=2)
    assert not ok and any("SL_DIRECTION" in r for r in reasons)


def test_gate_b_rejects_reversed_sl_short():
    g = TwoLayerGate()
    ok, reasons = g.gate_b(side="SELL", sl_price=95.0, entry_price=100.0, leverage=2)
    assert not ok and any("SL_DIRECTION" in r for r in reasons)


def test_gate_b_caps_leverage_at_2():
    g = TwoLayerGate()
    ok, reasons = g.gate_b(side="BUY", sl_price=95.0, entry_price=100.0, leverage=5)
    assert not ok and any("LEVERAGE" in r for r in reasons)


def test_gate_a_blocks_duplicate_correlation_id():
    g = TwoLayerGate()
    r1 = g.evaluate("c-1", "BTCUSDT", 1.0, True, "BUY", 95.0, 100.0, 2)
    assert r1.passed
    r2 = g.evaluate("c-1", "ETHUSDT", 1.0, True, "BUY", 95.0, 100.0, 2)
    assert not r2.passed and any("IDEMPOTENT" in x for x in r2.reasons)


def test_gate_a_daily_loss_halts_entry():
    g = TwoLayerGate(daily_loss_limit_pct=0.5)
    ok, reasons = g.gate_a("c-2", "BTCUSDT", 1.0, True, intraday_loss_pct=0.6)
    assert not ok and any("DAILY_LOSS" in r for r in reasons)


# --- Orchestrator: engines → dual score → gates → decisions_log ---

def test_entry_is_persisted_with_gate_flags(conn):
    orch = DecisionOrchestrator(conn)
    rec = orch.process(_bull(), sl_price=99.0, entry_price=100.0, leverage=2)
    assert rec.decision == "ENTRY" and rec.side == "BUY" and rec.actionable
    row = conn.execute("SELECT * FROM decisions_log WHERE id=?", (rec.id,)).fetchone()
    assert row["decision"] == "ENTRY"
    assert row["gate_a_pass"] == 1 and row["gate_b_pass"] == 1
    assert row["confidence_pct"] == rec.confidence_pct >= 90.0
    assert row["config_ver"] == "surface-v1"


def test_skip_is_persisted_too(conn):
    """SKIP must be recorded — evaluation needs false-negatives (doc 23)."""
    orch = DecisionOrchestrator(conn)
    rec = orch.process(_chop())
    assert rec.decision == "SKIP" and not rec.actionable
    row = conn.execute("SELECT * FROM decisions_log WHERE id=?", (rec.id,)).fetchone()
    assert row["decision"] == "SKIP"
    assert row["gate_a_pass"] is None and row["gate_b_pass"] is None


def test_entry_without_sl_is_vetoed(conn):
    """No SL provided on ENTRY → Gate B veto → persisted as SKIP with reason."""
    orch = DecisionOrchestrator(conn)
    rec = orch.process(_bull())  # no sl_price/entry_price
    assert rec.decision == "SKIP" and not rec.actionable
    row = conn.execute("SELECT reason FROM decisions_log WHERE id=?", (rec.id,)).fetchone()
    assert "MISSING" in row["reason"]


def test_gate_veto_recorded_reversed_sl(conn):
    orch = DecisionOrchestrator(conn)
    rec = orch.process(_bull(), sl_price=101.0, entry_price=100.0, leverage=2)
    assert rec.decision == "SKIP"
    row = conn.execute("SELECT * FROM decisions_log WHERE id=?", (rec.id,)).fetchone()
    assert row["gate_b_pass"] == 0 and "SL_DIRECTION" in row["reason"]


def test_clamp_beats_score_leverage(conn):
    """Even a >0.90 score cannot push leverage past the hard cap (doc 25)."""
    orch = DecisionOrchestrator(conn)
    rec = orch.process(_bull(), sl_price=99.0, entry_price=100.0, leverage=10)
    assert rec.decision == "SKIP" and not rec.actionable
    assert any("LEVERAGE" in r for r in rec.gate.reasons)
