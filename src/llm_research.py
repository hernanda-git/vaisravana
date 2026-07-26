"""Project Vaiśravaṇa — LLM research layer (Phase 11).

PROPOSE-ONLY, OFFLINE. The LLM is a *researcher*, never the decider:

  - `LLMResearcher.propose(...)` -> a bounded `sentinel.Proposal` for the Sentinel to
    shadow-test + promote/rollback. Output is funneled through the EXISTING
    `apply_proposal` guardrails, so a hallucinated diff is REFUSED, not trusted.
  - `NarrativeResearcher.tags(...)` -> enum-constrained `NarrativeTags` (doc 35, §8B).
    Unknown tag coerces to neutral — structurally safe.

LLM transport mirrors learnernoearner-listener exactly (OpenCode Zen gateway,
deepseek-v4-flash, OpenAI-compatible chat/completions). Auth via `Authorization:
Bearer`, model `deepseek-v4-flash`, `response_format: json_object`, `temperature: 0.1`,
`max_tokens: 4096` (low max_tokens yields empty content on this reasoning model).

Cross-cutting: NO live calls in tests — a `Client` protocol is injected so tests can
use a mock. The real client is `ZenClient`, used only at runtime / in research_loop.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from config import ParameterSurface
from context import NarrativeTags
from evaluation import EvalReport
from sentinel import Proposal, SentinelViolation, apply_proposal

# --- transport config (mirrors listener src/agent/agent.py) ---
ZEN_URL = "https://opencode.ai/zen/go/v1/chat/completions"
ZEN_MODEL = "deepseek-v4-flash"


class LLMError(ValueError):
    """Any LLM-layer failure. Callers treat this as 'no proposal' (safe no-op)."""


class Client(Protocol):
    """Minimal transport the researcher needs. Injected for testability."""

    def post_json(self, url: str, payload: dict, headers: dict) -> dict:
        """POST JSON, return parsed response dict. Raises on transport error."""
        ...


class ZenClient:
    """Real transport to the OpenCode Zen gateway (OpenAI-compatible)."""

    def __init__(self, api_key: str, url: str = ZEN_URL, model: str = ZEN_MODEL,
                 timeout: float = 60.0):
        self.api_key = api_key
        self.url = url
        self.model = model
        self.timeout = timeout

    def post_json(self, url: str, payload: dict, headers: dict) -> dict:
        import httpx  # imported lazily so tests never need httpx/network
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()


@dataclass
class ResearchResult:
    proposal: Proposal | None
    raw_response: str = ""
    error: str = ""
    latency_ms: int = 0
    used: bool = False  # whether this proposal was produced & shaped for Sentinel


# --- prompt builders (deterministic; only feed real DB numbers to the LLM) ---

_PROPOSAL_SYSTEM = (
    "You are a quantitative trading researcher tuning a BOUNDED parameter surface for a "
    "crypto futures paper-trading bot. You propose SMALL adjustments to FIXED parameters to "
    "improve win-rate and expectancy while keeping max drawdown flat. You NEVER change engine "
    "logic. Output STRICT JSON only.\n\n"
    "RULES (hard):\n"
    "1. Change at most 4 parameters per proposal.\n"
    "2. Per-weight change must be <= 10% of the current value (e.g. 0.20 -> [0.18,0.22]).\n"
    "3. Weights must sum to ~1.0 after your edits; you may adjust multiple weights to rebalance.\n"
    "4. Only edit keys listed below. Never invent keys.\n"
    "5. Set confidence in [0,1]. If you are unsure, return confidence < 0.5 and an empty changes.\n"
    "6. Return exactly: {\"changes\": {<param_path>: <new_value>}, \"hypothesis\": str, "
    "\"rationale\": str, \"confidence\": float}.\n\n"
    "Allowed param paths:\n"
    "  weights.trend, weights.momentum, weights.volume, weights.structure, "
    "weights.liquidity, weights.atr, weights.funding_oi\n"
    "  entry_threshold, watch_threshold, sl_atr_mult, tp_atr_mult, max_leverage, "
    "cooldown_after_loss, daily_loss_limit_pct, risk_per_trade_pct, "
    "max_position_notional_pct, winrate_gate_pct, min_trades_for_promote, "
    "global_max_live_pairs\n"
)


def _weights_block(surface: ParameterSurface) -> str:
    w = surface.weights.as_dict()
    return ", ".join(f"{k}={v:.3f}" for k, v in w.items())


def _evals_block(evals: list[EvalReport]) -> str:
    if not evals:
        return "(no trade history yet)"
    lines = []
    for e in evals:
        lines.append(
            f"- {e.pair} {e.tf} {e.side}: WR={e.win_rate_pct:.1f}% "
            f"exp={e.expectancy_r:+.3f}R PF={e.profit_factor:.2f} "
            f"DD={e.max_dd_pct:.2f}% health={e.health():.3f} passes={e.passes}"
        )
    return "\n".join(lines)


def _fp_fn_block(fp_fn: list[dict]) -> str:
    if not fp_fn:
        return "(no false-positive/false-negative cases)"
    out = []
    for c in fp_fn[:10]:  # cap context size
        out.append(
            f"- ENTRY->SL on {c.get('pair')} {c.get('tf')} {c.get('side')}: "
            f"score={c.get('score')} regime={c.get('regime')} "
            f"note={c.get('note','')}"
        )
    return "\n".join(out)


class LLMResearcher:
    """Propose a bounded Sentinel diff from real evaluation data. Propose-only."""

    def __init__(self, client: Client, enabled: bool = False,
                 url: str = ZEN_URL, model: str = ZEN_MODEL):
        self.client = client
        self.enabled = enabled
        self.url = url
        self.model = model

    def propose(
        self,
        surface: ParameterSurface,
        evals: list[EvalReport],
        fp_fn: list[dict],
        min_confidence: float = 0.5,
    ) -> ResearchResult:
        """Build a constrained prompt, call the LLM, parse strict JSON -> Proposal.

        On ANY failure (off, malformed JSON, low confidence, guardrail violation) return a
        ResearchResult with `proposal=None` — a safe no-op that NEVER raises into the caller.
        """
        if not self.enabled:
            return ResearchResult(proposal=None, error="disabled")

        user = (
            "CURRENT WEIGHTS: " + _weights_block(surface) + "\n"
            "CURRENT SCALARS: entry=" + f"{surface.entry_threshold:.3f} "
            f"watch={surface.watch_threshold:.3f} sl_atr={surface.sl_atr_mult} "
            f"tp_atr={surface.tp_atr_mult} lev={surface.max_leverage} "
            f"daily_loss={surface.daily_loss_limit_pct} risk={surface.risk_per_trade_pct} "
            f"wr_gate={surface.winrate_gate_pct} min_trades={surface.min_trades_for_promote}\n\n"
            "PERFORMANCE (per pair/tf/side):\n" + _evals_block(evals) + "\n\n"
            "FALSE-POSITIVE / FALSE-NEGATIVE CASES (ENTRY that hit SL, with context):\n"
            + _fp_fn_block(fp_fn) + "\n\n"
            "Propose <=4 bounded changes to raise win-rate/expectancy without raising DD. "
            "Output STRICT JSON only."
        )
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _PROPOSAL_SYSTEM},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {getattr(self.client, 'api_key', '')}",
        }
        t0 = time.monotonic()
        try:
            data = self.client.post_json(self.url, payload, headers)
            latency = int((time.monotonic() - t0) * 1000)
            text = (data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    or "").strip()
            return self._parse(text, latency, surface)
        except Exception as e:  # noqa: BLE001 — must degrade to no-op
            return ResearchResult(proposal=None, error=f"{type(e).__name__}: {e}",
                                  latency_ms=int((time.monotonic() - t0) * 1000))

    def _parse(self, text: str, latency_ms: int, surface: ParameterSurface) -> ResearchResult:
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            return ResearchResult(proposal=None, raw_response=text,
                                  error=f"bad JSON: {e}", latency_ms=latency_ms)
        changes = obj.get("changes") or {}
        conf = float(obj.get("confidence", 0.0) or 0.0)
        if not isinstance(changes, dict) or not changes:
            return ResearchResult(proposal=None, raw_response=text,
                                  error="empty changes", latency_ms=latency_ms)
        if conf < 0.5:
            return ResearchResult(proposal=None, raw_response=text,
                                  error=f"low confidence {conf}", latency_ms=latency_ms)
        # Build Proposal; pre-validate via the EXISTING Sentinel.apply_proposal so a
        # hallucinated diff (delta >10%, >4 changes, out-of-surface, doc-21 bounds) is
        # REFUSED HERE (audited + safe no-op), never trusted or passed downstream.
        try:
            prop = Proposal(
                changes={str(k): float(v) for k, v in changes.items()},
                rationale=str(obj.get("rationale", ""))[:500],
                hypothesis=str(obj.get("hypothesis", ""))[:500],
            )
            apply_proposal(surface, prop)  # raises SentinelViolation on any guardrail break
            return ResearchResult(proposal=prop, raw_response=text, latency_ms=latency_ms,
                                  used=True)
        except (SentinelViolation, ValueError) as e:
            return ResearchResult(proposal=None, raw_response=text,
                                  error=f"refused by guardrails: {e}", latency_ms=latency_ms)


class NarrativeResearcher:
    """Enum-constrained narrative summary for a pair (doc 35 §8B)."""

    def __init__(self, client: Client, enabled: bool = False,
                 url: str = ZEN_URL, model: str = ZEN_MODEL):
        self.client = client
        self.enabled = enabled
        self.url = url
        self.model = model

    _SYSTEM = (
        "You summarize crypto market narrative into STRICT JSON only: "
        "{\"regime\": one of [risk_on, risk_off, euphoria, capitulation, chop, "
        "news_driven, neutral], \"liquidity_stress\": one of [low, normal, high], "
        "\"note\": short string}. Output exactly that schema, nothing else."
    )

    def tags(self, pair: str, recent_news: str = "") -> NarrativeTags:
        if not self.enabled:
            return NarrativeTags.neutral()
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self._SYSTEM},
                {"role": "user", "content": f"Pair: {pair}\nContext: {recent_news[:500]}"},
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {getattr(self.client, 'api_key', '')}",
        }
        try:
            data = self.client.post_json(self.url, payload, headers)
            text = (data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    or "").strip()
            obj = json.loads(text)
            return NarrativeTags.coerce(
                regime=str(obj.get("regime", "neutral")),
                stress=str(obj.get("liquidity_stress", "normal")),
                source="llm",
                note=str(obj.get("note", ""))[:120],
            )
        except Exception:  # noqa: BLE001 — degrade to neutral (safe)
            return NarrativeTags.neutral()
