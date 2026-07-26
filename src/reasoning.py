"""Project Vaiśravaṇa — dynamic reasoning scaffold (5W1H, doc 29).

Builds a structured reasoning record for anomalies/decisions. Does not decide; it
structures the WHY so the Sentinel can explain and audit (doc 29, doc 26).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Reasoning5W1H:
    who: str = ""
    what: str = ""
    when: str = ""
    where: str = ""
    why: str = ""
    how: str = ""
    hypotheses: list[str] = field(default_factory=list)  # H1/H2/H3

    def is_complete(self) -> bool:
        # WHY is the load-bearing field (doc 29): no WHY -> default to safe (pause/reduce)
        return bool(self.why.strip())

    def to_text(self) -> str:
        h = "\n".join(f"  - {h}" for h in self.hypotheses) or "  (none)"
        return (
            f"WHO: {self.who}\nWHAT: {self.what}\nWHEN: {self.when}\n"
            f"WHERE: {self.where}\nWHY: {self.why}\nHOW: {self.how}\n"
            f"HYPOTHESES:\n{h}"
        )

    def to_dict(self) -> dict:
        return {
            "who": self.who, "what": self.what, "when": self.when,
            "where": self.where, "why": self.why, "how": self.how,
            "hypotheses": self.hypotheses,
        }


def build_from_event(event: str, ctx: dict) -> Reasoning5W1H:
    """Convenience: build a partial scaffold from a telemetry event + context dict."""
    return Reasoning5W1H(
        who=ctx.get("actor", "bot"),
        what=event,
        when=ctx.get("when", ""),
        where=ctx.get("where", ""),
        why=ctx.get("why", ""),
        how=ctx.get("how", ""),
        hypotheses=ctx.get("hypotheses", []),
    )
