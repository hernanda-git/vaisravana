"""Project Vaiśravaṇa — Sentinel: bounded self-improvement loop (doc 20, 21, 24, 29).

5-phase cycle (doc 24): EVALUATE → REASON/CORRECT → SHADOW TEST → PROMOTE/ROLLBACK
→ DOCUMENT (results_log + chronicle.md).

HARD GUARDRAILS (doc 20 principles, doc 21, doc 24 "Aturan aman koreksi"):
  - Only the ParameterSurface may be touched. Engine logic, execution code and
    telemetry schema are structurally out of reach (this module only ever emits a
    new ParameterSurface — it cannot patch code).
  - Per-weight change ≤ ±10% of current value per cycle.
  - Bounds from doc 21 enforced by pydantic (out-of-bound → rejected).
  - Σ weights renormalized to 1.0 after edits.
  - ≤ 4 parameter changes per cycle.
  - Promote ONLY if shadow ≥ baseline (expectancy ≥, DD ≤) AND composite health ↑;
    else rollback (doc 24 fase 3-4, doc 23 composite).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config import ParameterSurface
from evaluation import EvalReport

MAX_CHANGES_PER_CYCLE = 4          # doc 24
MAX_WEIGHT_DELTA_PCT = 10.0        # doc 24 / doc 20 principle 3

_WEIGHT_KEYS = {"trend", "momentum", "volume", "structure", "liquidity", "atr", "funding_oi"}
_SURFACE_KEYS = {
    "entry_threshold", "watch_threshold", "sl_atr_mult", "tp_atr_mult",
    "max_leverage", "cooldown_after_loss", "daily_loss_limit_pct",
    "risk_per_trade_pct", "max_position_notional_pct", "winrate_gate_pct",
    "min_trades_for_promote", "global_max_live_pairs",
}


class SentinelViolation(ValueError):
    """A proposed diff broke a guardrail. The diff is refused, never 'fixed up'."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Proposal:
    """A bounded diff: {param_path: new_value}. Weight paths are 'weights.<k>'."""

    changes: dict[str, float]
    rationale: str = ""
    hypothesis: str = ""       # H1/H2/H3 text from reasoning (doc 29)


def apply_proposal(surface: ParameterSurface, prop: Proposal) -> ParameterSurface:
    """Validate guardrails and return a NEW surface. Raises SentinelViolation."""
    if len(prop.changes) > MAX_CHANGES_PER_CYCLE:
        raise SentinelViolation(
            f"{len(prop.changes)} changes > max {MAX_CHANGES_PER_CYCLE}/cycle (doc 24)"
        )

    data = surface.as_dict()
    weights = dict(data["weights"])

    for path, value in prop.changes.items():
        if path.startswith("weights."):
            key = path.split(".", 1)[1]
            if key not in _WEIGHT_KEYS:
                raise SentinelViolation(f"unknown weight '{key}'")
            cur = weights[key]
            if cur > 0 and abs(value - cur) / cur * 100.0 > MAX_WEIGHT_DELTA_PCT + 1e-9:
                raise SentinelViolation(
                    f"weights.{key}: Δ {abs(value-cur)/cur*100:.1f}% > ±{MAX_WEIGHT_DELTA_PCT}% (doc 24)"
                )
            weights[key] = value
        elif path in _SURFACE_KEYS:
            data[path] = value
        else:
            # ANY non-surface target (engine logic, gate, schema...) is refused.
            raise SentinelViolation(f"'{path}' is not on the parameter surface (doc 21)")

    # renormalize Σ weights = 1.0 (doc 24 example: "=> Σ weights = 1.00 ✓")
    total = sum(weights.values())
    if total <= 0:
        raise SentinelViolation("weights sum ≤ 0")
    weights = {k: v / total for k, v in weights.items()}
    data["weights"] = weights

    # pydantic enforces doc 21 bounds — out-of-bound raises ValidationError
    try:
        return ParameterSurface(**data)
    except Exception as e:
        raise SentinelViolation(f"bounds violation (doc 21): {e}") from e


# --- shadow comparison + promotion (doc 24 fase 3-4) ---

@dataclass
class ShadowComparison:
    baseline: EvalReport
    shadow: EvalReport

    @property
    def shadow_not_worse(self) -> bool:
        """doc 24 fase 3: expectancy ≥ baseline AND DD ≤ baseline."""
        return (self.shadow.expectancy_r >= self.baseline.expectancy_r
                and self.shadow.max_dd_pct <= self.baseline.max_dd_pct)

    @property
    def health_improved(self) -> bool:
        """doc 23: only promote when COMPOSITE health rises, not just WR."""
        return self.shadow.health() > self.baseline.health()

    @property
    def promotable(self) -> bool:
        return self.shadow_not_worse and self.health_improved


@dataclass
class Sentinel:
    conn: sqlite3.Connection
    surface: ParameterSurface
    config_ver: int = 1
    history: list[tuple[int, ParameterSurface]] = field(default_factory=list)

    def cycle(
        self,
        prop: Proposal,
        comparison_factory,
        pair: str = "",
        tf: str = "",
        cycle_id: str | None = None,
    ) -> tuple[bool, ParameterSurface]:
        """One full 5-phase cycle.

        `comparison_factory(candidate_surface) -> ShadowComparison` runs the shadow
        test (injected: real impl replays the shadow trader; tests use fixtures).
        Returns (promoted, active_surface).
        """
        cycle_id = cycle_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")

        # Phase 2 — bounded correction (may raise SentinelViolation)
        try:
            candidate = apply_proposal(self.surface, prop)
        except SentinelViolation as e:
            self._document(cycle_id, pair, tf, kind="CORRECTION",
                           content={"proposal": prop.changes, "refused": str(e)},
                           correction=f"REFUSED: {e}", improvement="",
                           review="guardrail violation — diff discarded")
            raise

        # Phase 3 — shadow test
        cmp = comparison_factory(candidate)

        # Phase 4 — promote or rollback
        if cmp.promotable:
            self.history.append((self.config_ver, self.surface))
            self.config_ver += 1
            self.surface = candidate
            promoted = True
            review = (f"PROMOTED v{self.config_ver}: shadow exp "
                      f"{cmp.shadow.expectancy_r:+.3f}R ≥ baseline "
                      f"{cmp.baseline.expectancy_r:+.3f}R, health ↑")
        else:
            promoted = False
            review = ("ROLLBACK: shadow not better "
                      f"(exp {cmp.shadow.expectancy_r:+.3f}R vs {cmp.baseline.expectancy_r:+.3f}R, "
                      f"DD {cmp.shadow.max_dd_pct:.2f}% vs {cmp.baseline.max_dd_pct:.2f}%, "
                      f"health {cmp.shadow.health():.3f} vs {cmp.baseline.health():.3f})")

        # Phase 5 — document (results_log, doc 26)
        self._document(
            cycle_id, pair, tf, kind="IMPROVEMENT" if promoted else "REVIEW",
            content={"proposal": prop.changes, "promoted": promoted},
            eval_summary=(f"baseline WR {cmp.baseline.win_rate_pct:.1f}% "
                          f"exp {cmp.baseline.expectancy_r:+.3f}R DD {cmp.baseline.max_dd_pct:.2f}% | "
                          f"shadow WR {cmp.shadow.win_rate_pct:.1f}% "
                          f"exp {cmp.shadow.expectancy_r:+.3f}R DD {cmp.shadow.max_dd_pct:.2f}%"),
            reasoning_5w1h=prop.rationale,
            thinking=prop.hypothesis,
            correction=json.dumps(prop.changes),
            improvement=f"config v{self.config_ver}" if promoted else "",
            review=review,
            ver_from=self.config_ver - 1 if promoted else self.config_ver,
            ver_to=self.config_ver,
        )
        return promoted, self.surface

    def _document(self, cycle_id, pair, tf, kind, content, correction, improvement,
                  review, eval_summary="", reasoning_5w1h="", thinking="",
                  ver_from=None, ver_to=None) -> None:
        self.conn.execute(
            """INSERT INTO results_log
               (ts, cycle, pair, tf, kind, content_json, eval_summary, reasoning_5w1h,
                thinking, correction, improvement, review, config_ver_from, config_ver_to,
                approved_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now_iso(), cycle_id, pair, tf, kind, json.dumps(content), eval_summary,
             reasoning_5w1h, thinking, correction, improvement, review,
             str(ver_from) if ver_from is not None else None,
             str(ver_to) if ver_to is not None else None,
             "sentinel"),
        )
        self.conn.commit()

    def chronicle_entry(self, cycle_id: str) -> str:
        """Markdown chronicle block (doc 26) from the latest results_log rows."""
        rows = self.conn.execute(
            "SELECT * FROM results_log WHERE cycle=? ORDER BY id", (cycle_id,)
        ).fetchall()
        out = [f"# Chronicle — cycle {cycle_id}", ""]
        for r in rows:
            out += [f"## {r['kind']} ({r['pair']} {r['tf']})".rstrip(),
                    f"- eval: {r['eval_summary'] or '—'}",
                    f"- correction: {r['correction'] or '—'}",
                    f"- review: {r['review'] or '—'}", ""]
        return "\n".join(out)
