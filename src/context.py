"""Project Vaiśravaṇa — narrative context (Phase 11, optional LLM input).

The LLM may summarize macro/news into a LOW-CARDINALITY enum. This is the ONLY
channel by which free-form LLM text may enter the engine layer, and it is
structurally safe: an unknown/garbage tag maps to the neutral default, so a
hallucination can at worst be "neutral" — never poison.

No LLM call happens here. `NarrativeTags` is a plain dataclass; the LLM fills it
in `llm_research.NarrativeResearcher`. With LLM disabled, every field stays at its
neutral default and the bot behaves identically to today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Allowed regimes — the LLM must emit one of these (constrained/enum output).
RegimeTag = Literal[
    "risk_on", "risk_off", "euphoria", "capitulation", "chop", "news_driven", "neutral"
]
# Allowed liquidity-stress levels.
StressTag = Literal["low", "normal", "high"]

_ALLOWED_REGIME = {
    "risk_on", "risk_off", "euphoria", "capitulation", "chop", "news_driven", "neutral",
}
_ALLOWED_STRESS = {"low", "normal", "high"}


@dataclass
class NarrativeTags:
    """Enum-constrained narrative summary for a single pair (or market-wide)."""

    regime: RegimeTag = "neutral"
    liquidity_stress: StressTag = "normal"
    source: str = "default"  # "default" | "llm" | "stale"
    note: str = ""           # optional short human-readable note (never fed to engines)

    @staticmethod
    def neutral() -> "NarrativeTags":
        return NarrativeTags()

    def is_neutral(self) -> bool:
        return self.regime == "neutral" and self.liquidity_stress == "normal"

    @classmethod
    def coerce(cls, regime: str, stress: str, source: str = "llm",
               note: str = "") -> "NarrativeTags":
        """Coerce arbitrary LLM strings to a valid tag. Unknown -> neutral (safe)."""
        r = regime if regime in _ALLOWED_REGIME else "neutral"
        s = stress if stress in _ALLOWED_STRESS else "normal"
        return cls(regime=r, liquidity_stress=s, source=source, note=note)

    def as_dict(self) -> dict:
        return {
            "regime": self.regime,
            "liquidity_stress": self.liquidity_stress,
            "source": self.source,
            "note": self.note,
        }


@dataclass
class NarrativeStore:
    """Per-pair narrative, with a TTL so a stale value gracefully decays to neutral."""

    pairs: dict[str, NarrativeTags] = field(default_factory=dict)
    _ttl_seconds: int = 900  # 15 min
