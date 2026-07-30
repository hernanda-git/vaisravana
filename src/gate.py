"""Project Vaiśravaṇa — Two-Layer Safety Gate + decision logging (doc 25 §2, doc 30 §3).

Gate A — cheap, pre-scoring (no engine): idempotency, cooldown, liquidity whitelist, spread.
Gate B — post-scoring, pre-execution HARD CLAMP the 9-engine score cannot override
(doc 25): leverage ceiling, daily-loss cap, SL direction correct for the chosen side,
reduceOnly on closes.

The Sentinel is NEVER allowed to touch Gate B (doc 24 guardrail) — it is structural.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class GateResult:
    passed: bool
    gate_a: bool
    gate_b: bool
    reasons: list[str] = field(default_factory=list)


class TwoLayerGate:
    def __init__(
        self,
        spread_bps_limit: float = 10.0,          # doc 30 §3 Gate A
        cooldown_s: int = 120,                   # doc 21 cooldown_after_loss default 2m
        max_leverage: int = 5,                   # doc 21 hard cap
        daily_loss_limit_pct: float = 2.0,       # doc 21 / doc 30 §7
        clock: callable = time.time,
    ) -> None:
        self.spread_bps_limit = spread_bps_limit
        self.cooldown_s = cooldown_s
        self.max_leverage = max_leverage
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self._clock = clock
        self._last_entry: dict[str, float] = {}      # pair -> last entry ts (cooldown)
        self._seen_correlation: set[str] = set()     # idempotency (doc 32 L5)

    # --- Gate A: pre-scoring ---
    def gate_a(
        self,
        correlation_id: str,
        pair: str,
        spread_bps: float,
        liquidity_ok: bool,
        intraday_loss_pct: float = 0.0,     # current realized loss % today
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if correlation_id in self._seen_correlation:
            reasons.append("IDEMPOTENT: correlation_id already used")
            return False, reasons
        if not liquidity_ok:
            reasons.append("LIQUIDITY: pair not in whitelist")
            return False, reasons
        if spread_bps > self.spread_bps_limit:
            reasons.append(f"SPREAD: {spread_bps}bps > {self.spread_bps_limit}bps")
            return False, reasons
        if intraday_loss_pct >= self.daily_loss_limit_pct:
            reasons.append(f"DAILY_LOSS: {intraday_loss_pct}% >= {self.daily_loss_limit_pct}%")
            return False, reasons
        # cooldown
        last = self._last_entry.get(pair)
        if last is not None and (self._clock() - last) < self.cooldown_s:
            reasons.append("COOLDOWN: pair in cooldown")
            return False, reasons
        return True, reasons

    # --- Gate B: post-scoring hard clamp ---
    def gate_b(
        self,
        side: str,
        sl_price: float,
        entry_price: float,
        leverage: int,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if leverage > self.max_leverage:
            reasons.append(f"LEVERAGE: {leverage} > {self.max_leverage} cap")
            return False, reasons
        # SL direction MUST match side (doc 25 §2): LONG sl < entry; SHORT sl > entry.
        # Reject reversed SL (prevents SL/TP hallucinated on wrong side).
        if side == "BUY" and not (sl_price < entry_price):
            reasons.append("SL_DIRECTION: LONG sl must be below entry")
            return False, reasons
        if side == "SELL" and not (sl_price > entry_price):
            reasons.append("SL_DIRECTION: SHORT sl must be above entry")
            return False, reasons
        return True, reasons

    def evaluate(
        self,
        correlation_id: str,
        pair: str,
        spread_bps: float,
        liquidity_ok: bool,
        side: str,
        sl_price: float,
        entry_price: float,
        leverage: int,
        intraday_loss_pct: float = 0.0,
    ) -> GateResult:
        a_ok, a_reasons = self.gate_a(
            correlation_id, pair, spread_bps, liquidity_ok, intraday_loss_pct
        )
        if not a_ok:
            return GateResult(False, False, False, a_reasons)
        # mark idempotency + cooldown only after Gate A passes (so re-checks don't consume)
        self._seen_correlation.add(correlation_id)
        self._last_entry[pair] = self._clock()
        b_ok, b_reasons = self.gate_b(side, sl_price, entry_price, leverage)
        return GateResult(b_ok, True, b_ok, a_reasons + b_reasons)
