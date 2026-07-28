"""Phase 11 — LLM research layer tests (MOCK client, no live network calls).

Verifies the hallucination-proof contract:
  - disabled -> no proposal
  - >4 changes -> refused (guardrail)
  - weight delta >10% -> refused
  - malformed JSON -> safe no-op (no raise)
  - confidence < 0.5 -> discarded
  - out-of-surface key -> refused
  - unknown narrative tag -> coerced to neutral
  - shadow comparison promotions only when shadow >= baseline + health up
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import default_surface
from sentinel import Sentinel, Proposal, ShadowComparison
from evaluation import EvalReport
from llm_research import LLMResearcher, NarrativeResearcher
from context import NarrativeTags


class FakeClient:
    """Returns a canned JSON body regardless of input (no network)."""

    def __init__(self, body: str = "", raise_on_call: bool = False,
                 api_key: str = "test-key"):
        self.body = body
        self.raise_on_call = raise_on_call
        self.api_key = api_key

    def post_json(self, url, payload, headers):
        if self.raise_on_call:
            raise RuntimeError("network down")
        return {"choices": [{"message": {"content": self.body}}]}


def _good_proposal_body(changes: dict, conf: float = 0.9) -> str:
    return (
        '{"changes": ' + __import__("json").dumps(changes)
        + ', "hypothesis": "H1", "rationale": "test", "confidence": ' + str(conf) + '}'
    )


def test_disabled_no_proposal():
    r = LLMResearcher(FakeClient(), enabled=False).propose(
        default_surface(), [], [])
    assert r.proposal is None and r.error == "disabled"


def test_guardrail_max_4_changes():
    # 5 weight changes must be refused -> proposal None, error mentions guardrail
    body = _good_proposal_body({
        "weights.trend": 0.31, "weights.momentum": 0.21, "weights.volume": 0.16,
        "weights.structure": 0.16, "weights.liquidity": 0.11,
    })
    r = LLMResearcher(FakeClient(body), enabled=True).propose(
        default_surface(), [], [])
    assert r.proposal is None
    assert "cycle" in (r.error or "") or "guardrail" in (r.error or "").lower()


def test_guardrail_weight_delta_over_10pct():
    # trend default 0.30 -> 0.40 is +33% > 10% -> refused
    body = _good_proposal_body({"weights.trend": 0.40})
    r = LLMResearcher(FakeClient(body), enabled=True).propose(
        default_surface(), [], [])
    assert r.proposal is None
    assert "guardrail" in (r.error or "").lower() or "10%" in (r.error or "")


def test_malformed_json_safe_noop():
    r = LLMResearcher(FakeClient("{not json"), enabled=True).propose(
        default_surface(), [], [])
    assert r.proposal is None
    assert "bad JSON" in (r.error or "")


def test_low_confidence_discarded():
    body = _good_proposal_body({"weights.trend": 0.31}, conf=0.3)
    r = LLMResearcher(FakeClient(body), enabled=True).propose(
        default_surface(), [], [])
    assert r.proposal is None
    assert "confidence" in (r.error or "").lower()


def test_out_of_surface_key_refused():
    # 'engine.logic' is not on the surface -> SentinelViolation -> refused
    body = _good_proposal_body({"engine.logic": 0.5})
    r = LLMResearcher(FakeClient(body), enabled=True).propose(
        default_surface(), [], [])
    assert r.proposal is None
    assert "parameter surface" in (r.error or "") or "guardrail" in (r.error or "").lower()


def test_valid_small_change_produces_proposal():
    # trend 0.30 -> 0.31 (+3.3%, within 10%) is accepted and shaped into a Proposal
    body = _good_proposal_body({"weights.trend": 0.31})
    r = LLMResearcher(FakeClient(body), enabled=True).propose(
        default_surface(), [], [])
    assert r.proposal is not None
    assert r.proposal.changes["weights.trend"] == 0.31
    assert r.used is True


def test_network_error_degrades_to_noop():
    r = LLMResearcher(FakeClient(raise_on_call=True), enabled=True).propose(
        default_surface(), [], [])
    assert r.proposal is None
    assert r.error  # some error recorded, never raised into caller


def test_unknown_narrative_tag_coerced_to_neutral():
    # LLM returns a garbage regime -> coerce to neutral (safe)
    t = NarrativeTags.coerce(regime="moonshot", stress="extreme")
    assert t.regime == "neutral" and t.liquidity_stress == "normal"
    assert t.is_neutral()


def test_narrative_disabled_returns_neutral():
    t = NarrativeResearcher(FakeClient(), enabled=False).tags("BTCUSDT")
    assert t.is_neutral()


# --- shadow comparison promotion contract (mirrors sentinel.ShadowComparison) ---

def _report(wr, exp, dd):
    return EvalReport(pair="BTCUSDT", tf="5m", side="BUY", n_trades=50,
                      win_rate_pct=wr, expectancy_r=exp, profit_factor=1.0,
                      max_dd_pct=dd, sharpe=0.0, passes={"wr_gate": True})


def test_promote_only_when_shadow_better_and_health_up():
    base = _report(wr=60.0, exp=0.10, dd=2.0)
    shadow_better = _report(wr=65.0, exp=0.15, dd=1.8)
    cmp = ShadowComparison(base, shadow_better)
    assert cmp.promotable is True

    shadow_worse = _report(wr=55.0, exp=0.05, dd=2.5)
    cmp2 = ShadowComparison(base, shadow_worse)
    assert cmp2.promotable is False


def test_sentinel_cycle_promotes_valid_diff(tmp_path):
    import sqlite3
    from db import init_db
    conn = init_db(tmp_path / "t.db")
    s = Sentinel(conn, default_surface())
    # candidate: nudge trend within 10%
    prop = Proposal(changes={"weights.trend": 0.31},
                    rationale="test", hypothesis="H1")
    # comparison_factory returns a promotable comparison
    def factory(cand):
        return ShadowComparison(_report(60, 0.10, 2.0), _report(65, 0.15, 1.8))
    promoted, surf = s.cycle(prop, factory, cycle_id="test")
    assert promoted is True
    # renormalization shifts slightly, but trend must have moved up toward 0.31
    assert surf.weights.trend > 0.30
