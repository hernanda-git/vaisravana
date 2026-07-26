"""Project Vaiśravaṇa — decision orchestrator (doc 30 §3-§4).

Pipeline per candle close per (pair, tf):
    MarketState → engines → dual score (BUY/SELL) → Gate A (cheap pre-check)
    → Gate B (hard clamp) → persist to `decisions_log`.

EVERY evaluated candidate is written to `decisions_log` — ENTRY, WATCH, and SKIP —
so the Evaluation Engine can later count false-negatives (SKIP that should have won).
`confidence_pct = chosen_score × 100` (doc 30 §4).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from config import ParameterSurface, default_surface
from engines import MarketState
from gate import GateResult, TwoLayerGate
from scoring import Decision, decide

CONFIG_VER = "surface-v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DecisionRecord:
    """Full outcome of one decision cycle — what got persisted."""

    id: str
    correlation_id: str
    pair: str
    tf: str
    decision: str          # ENTRY / WATCH / SKIP
    side: str | None       # BUY / SELL / None
    confidence_pct: float
    gate: GateResult | None   # None when no ENTRY was attempted (WATCH/SKIP)
    scoring: Decision

    @property
    def actionable(self) -> bool:
        """True only when scoring said ENTRY *and* both gates passed."""
        return self.decision == "ENTRY" and self.gate is not None and self.gate.passed


class DecisionOrchestrator:
    """Engines → dual score → two-layer gate → decisions_log (doc 30 §3, §4)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        surface: ParameterSurface | None = None,
        gate: TwoLayerGate | None = None,
    ) -> None:
        self.conn = conn
        self.surface = surface or default_surface()
        self.gate = gate or TwoLayerGate(
            cooldown_s=self.surface.cooldown_after_loss * 60,
            max_leverage=self.surface.max_leverage,
            daily_loss_limit_pct=self.surface.daily_loss_limit_pct,
        )

    def process(
        self,
        state: MarketState,
        *,
        liquidity_ok: bool = True,
        intraday_loss_pct: float = 0.0,
        sl_price: float | None = None,
        entry_price: float | None = None,
        leverage: int | None = None,
        correlation_id: str | None = None,
    ) -> DecisionRecord:
        """Run one full decision cycle and persist the outcome.

        sl_price/entry_price are required only when scoring yields ENTRY
        (Gate B must check SL side). If absent on ENTRY, Gate B fails —
        we never let an un-stopped order through (doc 25 §2).
        """
        corr = correlation_id or str(uuid.uuid4())
        dec_id = str(uuid.uuid4())
        scoring = decide(state, self.surface)

        gate_result: GateResult | None = None
        final_decision = scoring.decision

        if scoring.decision == "ENTRY":
            if sl_price is None or entry_price is None:
                gate_result = GateResult(
                    False, False, False, ["MISSING: sl_price/entry_price for ENTRY"]
                )
            else:
                gate_result = self.gate.evaluate(
                    correlation_id=corr,
                    pair=state.symbol,
                    spread_bps=state.spread_bps,
                    liquidity_ok=liquidity_ok,
                    side=scoring.side,
                    sl_price=sl_price,
                    entry_price=entry_price,
                    leverage=leverage if leverage is not None else self.surface.max_leverage,
                    intraday_loss_pct=intraday_loss_pct,
                )
            if not gate_result.passed:
                final_decision = "SKIP"   # gate veto → recorded as SKIP with reasons

        record = DecisionRecord(
            id=dec_id,
            correlation_id=corr,
            pair=state.symbol,
            tf=state.tf,
            decision=final_decision,
            side=scoring.side if final_decision == "ENTRY" else scoring.side,
            confidence_pct=scoring.confidence_pct,
            gate=gate_result,
            scoring=scoring,
        )
        self._persist(record, state)
        return record

    def _persist(self, r: DecisionRecord, state: MarketState) -> None:
        reasons = "; ".join(r.gate.reasons) if r.gate else ""
        self.conn.execute(
            """
            INSERT INTO decisions_log
              (id, correlation_id, ts, pair, tf, regime, scores_json, total_score,
               confidence_pct, decision, gate_a_pass, gate_b_pass, reason, config_ver)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.id,
                r.correlation_id,
                _now_iso(),
                r.pair,
                r.tf,
                state.regime,
                json.dumps(
                    {
                        "sub": r.scoring.sub_scores.as_dict(),
                        "long": r.scoring.long_score,
                        "short": r.scoring.short_score,
                        "side": r.side,
                    }
                ),
                r.scoring.chosen_score,
                r.confidence_pct,
                r.decision,
                int(r.gate.gate_a) if r.gate else None,
                int(r.gate.gate_b) if r.gate else None,
                reasons,
                CONFIG_VER,
            ),
        )
        self.conn.commit()
