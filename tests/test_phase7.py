"""Tests for Phase 7: Sentinel — bounded diffs, guardrails, shadow-gated promotion,
results_log documentation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from config import default_surface  # noqa: E402
from db import init_db  # noqa: E402
from evaluation import EvalReport  # noqa: E402
from sentinel import (  # noqa: E402
    Proposal,
    Sentinel,
    SentinelViolation,
    ShadowComparison,
    apply_proposal,
)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _report(wr=90.0, exp=0.5, pf=2.0, dd=1.0, sharpe=1.0, n=200) -> EvalReport:
    return EvalReport("BTCUSDT", "5m", "BUY", n, wr, exp, pf, dd, sharpe,
                      passes={"win_rate": wr >= 85})


# --- guardrails (doc 21 / doc 24) ---

def test_valid_small_weight_shift_applies_and_renormalizes():
    s = default_surface()
    out = apply_proposal(s, Proposal({"weights.trend": 0.33}))  # +10% of 0.30
    w = out.weights.as_dict()
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w["trend"] > s.weights.trend


def test_weight_delta_over_10pct_refused():
    s = default_surface()
    with pytest.raises(SentinelViolation, match="10"):
        apply_proposal(s, Proposal({"weights.trend": 0.36}))    # +20%


def test_non_surface_param_refused():
    s = default_surface()
    with pytest.raises(SentinelViolation, match="not on the parameter surface"):
        apply_proposal(s, Proposal({"gate_b.max_leverage_bypass": 1.0}))


def test_more_than_4_changes_refused():
    s = default_surface()
    changes = {"weights.trend": 0.31, "weights.momentum": 0.21,
               "weights.volume": 0.155, "weights.structure": 0.155,
               "tp_atr_mult": 1.1}
    with pytest.raises(SentinelViolation, match="max 4"):
        apply_proposal(s, Proposal(changes))


def test_out_of_bound_value_refused():
    s = default_surface()
    with pytest.raises(SentinelViolation, match="bounds"):
        apply_proposal(s, Proposal({"max_leverage": 10}))       # doc 21 cap = 3


# --- promotion logic (doc 24 fase 3-4, doc 23 composite) ---

def test_promotes_when_shadow_better_and_health_up(conn):
    sen = Sentinel(conn, default_surface())
    cmp = ShadowComparison(baseline=_report(exp=0.3, dd=2.0, pf=1.5),
                           shadow=_report(exp=0.5, dd=1.0, pf=2.2))
    promoted, surface = sen.cycle(
        Proposal({"weights.trend": 0.32}, rationale="WHY: range WR low"),
        comparison_factory=lambda cand: cmp, pair="BTCUSDT", tf="5m",
    )
    assert promoted and sen.config_ver == 2
    assert surface.weights.trend != default_surface().weights.trend


def test_rolls_back_when_shadow_worse(conn):
    sen = Sentinel(conn, default_surface())
    base_surface = sen.surface
    cmp = ShadowComparison(baseline=_report(exp=0.5, dd=1.0),
                           shadow=_report(exp=0.3, dd=2.0))
    promoted, surface = sen.cycle(
        Proposal({"weights.trend": 0.32}), comparison_factory=lambda cand: cmp,
    )
    assert not promoted and sen.config_ver == 1 and surface is base_surface


def test_wr_up_but_health_down_not_promoted(conn):
    """Anti reward-hacking: WR alone can't buy a promotion (doc 23)."""
    sen = Sentinel(conn, default_surface())
    cmp = ShadowComparison(
        baseline=_report(wr=86.0, exp=0.5, pf=2.0, dd=1.0),
        shadow=_report(wr=92.0, exp=0.5, pf=0.9, dd=1.0),   # WR up, PF collapsed
    )
    promoted, _ = sen.cycle(Proposal({"weights.trend": 0.31}),
                            comparison_factory=lambda cand: cmp)
    assert not promoted


def test_every_cycle_documented_in_results_log(conn):
    sen = Sentinel(conn, default_surface())
    cmp = ShadowComparison(baseline=_report(exp=0.3, dd=2.0, pf=1.5),
                           shadow=_report(exp=0.5, dd=1.0, pf=2.2))
    sen.cycle(Proposal({"weights.trend": 0.32}, rationale="5W1H...", hypothesis="H1..."),
              comparison_factory=lambda cand: cmp, pair="BTCUSDT", tf="5m",
              cycle_id="2026-07-26T12:00")
    row = conn.execute("SELECT * FROM results_log").fetchone()
    assert row["kind"] == "IMPROVEMENT" and row["cycle"] == "2026-07-26T12:00"
    assert row["reasoning_5w1h"] == "5W1H..." and row["approved_by"] == "sentinel"
    assert row["config_ver_from"] == "1" and row["config_ver_to"] == "2"


def test_refused_diff_also_documented(conn):
    sen = Sentinel(conn, default_surface())
    with pytest.raises(SentinelViolation):
        sen.cycle(Proposal({"engine.regime_logic": 1.0}),
                  comparison_factory=lambda cand: None)
    row = conn.execute("SELECT * FROM results_log").fetchone()
    assert row["kind"] == "CORRECTION" and "REFUSED" in row["correction"]


def test_chronicle_markdown(conn):
    sen = Sentinel(conn, default_surface())
    cmp = ShadowComparison(baseline=_report(exp=0.3, dd=2.0, pf=1.5),
                           shadow=_report(exp=0.5, dd=1.0, pf=2.2))
    sen.cycle(Proposal({"weights.trend": 0.32}), comparison_factory=lambda cand: cmp,
              cycle_id="cyc-1")
    md = sen.chronicle_entry("cyc-1")
    assert md.startswith("# Chronicle") and "IMPROVEMENT" in md
