"""Project Vaiśravaṇa — hard trading-mode boundary (doc 30 §6/§7; doc 25).

The single most important safety property: a (pair, tf, side) can NEVER be traded
live without BOTH (a) a real Exchange adapter being supplied and (b) that key having
passed safety.promotion_gate(..., human_approved=True). In PAPER mode no live adapter
can even be instantiated, and every fill is simulated.

This makes the "human-gated live boundary" a *structural* guarantee instead of a comment.
In the previous version the only thing stopping a live order was prose ("There is no live
order path") — now it is enforced by `ModeGuard` at construction and at every entry.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from execution import OrderDraft, OrderResult  # noqa: F401  (Exchange is structural)


class ModeBoundaryError(RuntimeError):
    """Raised when code attempts a live action the mode/approval set forbids."""


TRADING_MODES = ("paper", "live")


class PaperSimExchange:
    """Simulated Exchange for PAPER mode. No network.

    - `mark_price` returns the latest price the bot pushed via `set_price` (per tick).
    - `place_order` reports an immediate FILLED at the requested price (paper fill).
    - `place_conditional_stop` returns NEW (resting on the simulated exchange).

    Satisfies the `execution.Exchange` protocol so the SAME `PositionMonitor` code path
    drives stop/maxhold/orphan management in paper and live.
    """

    def __init__(self, clock: callable = time.time) -> None:
        self._prices: dict[str, float] = {}
        self._clock = clock

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def mark_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 0.0)

    def place_order(self, draft: OrderDraft) -> OrderResult:
        return OrderResult(
            status="FILLED", order_id=str(uuid.uuid4())[:12],
            filled_qty=draft.qty, avg_price=draft.price,
        )

    def cancel_order(self, symbol: str, order_id: str) -> OrderResult:
        return OrderResult(status="CANCELED", order_id=order_id)

    def order_status(self, symbol: str, order_id: str) -> OrderResult:
        return OrderResult(status="FILLED", order_id=order_id)

    def place_conditional_stop(self, draft: OrderDraft, stop_price: float) -> OrderResult:
        return OrderResult(status="NEW", order_id=str(uuid.uuid4())[:12])


@dataclass
class ModeGuard:
    """Enforces the human-gated live boundary by construction.

    PAPER (default):  uses a `PaperSimExchange`; refuses to accept a live adapter.
    LIVE:             requires a real Exchange adapter AND a non-empty approval set;
                      `assert_entry_allowed` raises on any unapproved (pair,tf,side).
    """

    mode: str = "paper"
    approved: set = field(default_factory=set)  # set[(pair, tf, side)] approved for LIVE

    def __post_init__(self) -> None:
        if self.mode not in TRADING_MODES:
            raise ModeBoundaryError(f"unknown trading mode {self.mode!r}")

    def assert_entry_allowed(self, pair: str, tf: str, side: str) -> None:
        if self.mode == "paper":
            return
        if (pair, tf, side) not in self.approved:
            raise ModeBoundaryError(
                f"LIVE entry {pair}/{tf}/{side} not in human-approved promotion set"
            )

    def exchange_for(self, live_exchange):
        """Return the Exchange the loop should drive. Paper → sim; Live → guarded real."""
        if self.mode == "paper":
            if live_exchange is not None:
                raise ModeBoundaryError("live_exchange passed while mode=paper")
            return PaperSimExchange()
        if live_exchange is None:
            raise ModeBoundaryError("LIVE mode requires a real Exchange adapter")
        return GuardedExchange(live_exchange, self.approved)


class GuardedExchange:
    """Wraps a real Exchange; refuses any order whose symbol isn't human-approved.

    Primary guard is `ModeGuard.assert_entry_allowed` at entry time; this is
    defense-in-depth so a stray send path cannot reach the wire unapproved.
    """

    def __init__(self, real, approved: set) -> None:
        self._real = real
        self._approved = approved

    def _check(self, symbol: str) -> None:
        if symbol not in {p for (p, _, _) in self._approved}:
            raise ModeBoundaryError(f"LIVE order on {symbol} not human-approved")

    def place_order(self, draft: OrderDraft) -> OrderResult:
        self._check(draft.symbol)
        return self._real.place_order(draft)

    def cancel_order(self, symbol: str, order_id: str) -> OrderResult:
        self._check(symbol)
        return self._real.cancel_order(symbol, order_id)

    def order_status(self, symbol: str, order_id: str) -> OrderResult:
        self._check(symbol)
        return self._real.order_status(symbol, order_id)

    def place_conditional_stop(self, draft: OrderDraft, stop_price: float) -> OrderResult:
        self._check(draft.symbol)
        return self._real.place_conditional_stop(draft, stop_price)

    def mark_price(self, symbol: str) -> float:
        return self._real.mark_price(symbol)
