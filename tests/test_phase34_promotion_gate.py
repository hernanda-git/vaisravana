"""Tests for Phase 34: statistical promotion gate (v0.0.24 P1-34).

Closes F4: the Sentinel must not promote on a raw expectancy compare with no
sample floor / no significance test. The gate requires both samples >= min_trades
and the candidate's NET expectancy$ CI lower bound strictly above baseline AND $0.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest

from promotion_gate import evaluate_gate, _wilson_ci


def test_wilson_ci_basic():
    lo, hi = _wilson_ci(45, 50)  # 90% success, n=50
    assert lo < 0.90 < hi
    assert lo > 0.78


def test_small_sample_rejected():
    g = evaluate_gate(baseline_net=0.001, baseline_n=10, candidate_net=0.05,
                      candidate_n=12, min_trades=50)
    assert not g.promotable
    assert "min_trades" in g.reason


def test_candidate_not_meaningful_edge_rejected():
    # large sample but net edge tiny (< min_net_edge) -> not economically meaningful
    g = evaluate_gate(baseline_net=0.0, baseline_n=200, candidate_net=0.0005,
                      candidate_n=200, min_net_edge=0.001)
    assert not g.promotable
    assert "not > min edge" in g.reason


def test_candidate_clearly_better_promoted():
    # baseline modest positive; candidate clearly positive with large sample
    g = evaluate_gate(baseline_net=0.002, baseline_n=200, candidate_net=0.02,
                      candidate_n=200, min_net_edge=0.001)
    assert g.promotable
    assert g.candidate_ci[0] > 0.002  # above baseline
    assert g.candidate_ci[0] > 0.001


def test_candidate_tied_or_worse_rejected():
    # candidate edge smaller than baseline spread -> CI lower bound below baseline
    g = evaluate_gate(baseline_net=0.02, baseline_n=200, candidate_net=0.021,
                      candidate_n=60)
    assert not g.promotable
    assert "not clearly better" in g.reason
