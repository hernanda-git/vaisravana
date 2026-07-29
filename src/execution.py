"""Project Vaiśravaṇa — execution layer (doc 30 §3, doc 32 L2/L3/L7).

Everything here is PAPER-safe: the exchange is injected via the `Exchange` protocol.
No live network calls exist in this module. Deterministic — no LLM/reasoning in the
repair path (doc 32 L3).

Components:
  - round_price / round_qty / size_position  — filter-aware rounding (doc 30 §3)
  - validate_order                            — precision/minQty/minNotional checks
  - repair_order                              — re-derive qty/price from filters (1x)
  - OrderManager                              — LIMIT@mid maker, 2s unfilled → cancel,
                                                validate→repair→resubmit-once→VALIDATION_SKIP
  - place_stop_loss                           — conditional STOP (reduceOnly) primary,
                                                mark-price polling fallback on -4120
  - classify_error                            — doc 32 L7 error categorization
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from symbols import SymbolInfo, SymbolRegistry

# --- error categorization (doc 32 L7) ---

AUTH, RATE_LIMIT, SERVER, NETWORK, ORDER_REJECT = (
    "AUTH", "RATE_LIMIT", "SERVER", "NETWORK", "ORDER_REJECT",
)


def classify_error(code: int | None, network: bool = False) -> tuple[str, bool]:
    """Return (category, retryable). doc 32 L7: never retry auth; backoff on 429."""
    if network:
        return NETWORK, True          # treated as PENDING, not FAILED
    if code in (401, 403):
        return AUTH, False
    if code == 429:
        return RATE_LIMIT, True
    if code is not None and 500 <= code < 600:
        return SERVER, True
    return ORDER_REJECT, False        # e.g. -4130/-4131/-4120 → repair path, not blind retry


# --- filter-aware rounding (doc 30 §3, doc 32 L2) ---

def round_price(price: float, info: SymbolInfo) -> float:
    """Round price DOWN to the symbol's tickSize grid."""
    if info.tick_size <= 0:
        return price
    return math.floor(price / info.tick_size + 1e-12) * info.tick_size


def round_qty(qty: float, info: SymbolInfo) -> float:
    """Round qty DOWN to stepSize grid (integer lots when step_size=1)."""
    if info.step_size <= 0:
        return qty
    return math.floor(qty / info.step_size + 1e-12) * info.step_size


def size_position(
    equity: float,
    risk_per_trade_pct: float,
    entry: float,
    sl_price: float,
    leverage: int,
    info: SymbolInfo,
    free_margin: float | None = None,
    max_position_notional_pct: float = 50.0,
) -> float:
    """Risk-based sizing (doc 30 §3):

        risk_usd    = equity × risk_per_trade
        size        = risk_usd / |entry − sl|
        notional    = size × entry × leverage ≤ 50% free margin

    Then round to stepSize and LOOP UP until qty×price ≥ minNotional (doc 30 §3).
    Returns 0.0 when the pair cannot satisfy constraints (skip the trade).
    """
    sl_distance = abs(entry - sl_price)
    if sl_distance <= 0 or entry <= 0:
        return 0.0
    risk_usd = equity * (risk_per_trade_pct / 100.0)
    qty = round_qty(risk_usd / sl_distance, info)

    # bump up in stepSize increments until minNotional satisfied
    step = info.step_size or 1.0
    while qty * entry < info.min_notional:
        qty += step
        if qty * entry > equity * 10:   # sanity: never runaway
            return 0.0

    # margin cap: margin used (= notional / leverage) ≤ max_position_notional_pct
    # of free margin (doc 30 §3). NOTE: leverage DIVIDES here — a 3x position
    # holds notional/3 as margin. The old code multiplied (qty*entry*leverage),
    # which on a $10 account capped effective notional at $1.67 < minNotional $5,
    # making EVERY pair unsizeable (and triggering the qty=1.0 fallback blowup).
    margin_base = free_margin if free_margin is not None else equity
    max_margin = margin_base * (max_position_notional_pct / 100.0)
    lev = max(leverage, 1)
    while qty > 0 and (qty * entry) / lev > max_margin:
        qty -= step
    qty = max(qty, 0.0)
    if qty * entry < info.min_notional:
        return 0.0   # can't satisfy both minNotional and margin cap → skip
    return round(qty, 10)


# --- validation + repair (doc 30 §3, doc 32 L3) ---

@dataclass
class OrderDraft:
    symbol: str
    side: str            # BUY / SELL
    price: float
    qty: float
    order_type: str = "LIMIT"
    reduce_only: bool = False
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])


def validate_order(draft: OrderDraft, registry: SymbolRegistry) -> tuple[bool, str]:
    info = registry.get(draft.symbol)
    if info is None:
        return False, "UNKNOWN_SYMBOL"
    if draft.price <= 0:
        return False, "PRICE_LE_ZERO"
    if draft.qty <= 0:
        return False, "QTY_LE_ZERO"
    # grid alignment
    if info.tick_size > 0 and abs(draft.price / info.tick_size - round(draft.price / info.tick_size)) > 1e-6:
        return False, "PRICE_OFF_TICK"
    if info.step_size > 0 and abs(draft.qty / info.step_size - round(draft.qty / info.step_size)) > 1e-6:
        return False, "QTY_OFF_STEP"
    if info.min_qty and draft.qty < info.min_qty:
        return False, "BELOW_MIN_QTY"
    if draft.qty * draft.price < info.min_notional:
        return False, "BELOW_MIN_NOTIONAL"
    return True, "OK"


def repair_order(draft: OrderDraft, registry: SymbolRegistry) -> OrderDraft:
    """Deterministically re-derive qty/price from exchange filters (doc 32 L3).

    One repair attempt only — caller resubmits once, else VALIDATION_SKIP.
    """
    info = registry.get(draft.symbol)
    if info is None:
        return draft
    price = round_price(draft.price, info)
    qty = round_qty(draft.qty, info)
    step = info.step_size or 1.0
    while price > 0 and qty * price < info.min_notional:
        qty += step
    return OrderDraft(
        symbol=draft.symbol, side=draft.side, price=price, qty=qty,
        order_type=draft.order_type, reduce_only=draft.reduce_only,
        correlation_id=draft.correlation_id,
    )


# --- exchange protocol (mock in tests; python-binance adapter later) ---

@dataclass
class OrderResult:
    status: str            # FILLED / NEW / CANCELED / REJECTED / FAILED / PENDING
    order_id: str = ""
    filled_qty: float = 0.0
    avg_price: float = 0.0
    error_code: int | None = None
    error_msg: str = ""


class Exchange(Protocol):
    def place_order(self, draft: OrderDraft) -> OrderResult: ...
    def cancel_order(self, symbol: str, order_id: str) -> OrderResult: ...
    def order_status(self, symbol: str, order_id: str) -> OrderResult: ...
    def place_conditional_stop(self, draft: OrderDraft, stop_price: float) -> OrderResult: ...
    def mark_price(self, symbol: str) -> float: ...


# --- order manager (doc 30 §3) ---

VALIDATION_SKIP = "VALIDATION_SKIP"


@dataclass
class ExecOutcome:
    status: str                    # FILLED / CANCELED_UNFILLED / VALIDATION_SKIP / FAILED
    result: OrderResult | None
    repaired: bool = False
    events: list[str] = field(default_factory=list)


class OrderManager:
    """LIMIT (maker) near mid; unfilled in `fill_timeout_s` → cancel, no chase.

    Reject path: validate → repair → revalidate → resubmit ONCE → else VALIDATION_SKIP.
    (doc 30 §3, doc 32 L3 — deterministic, no reasoning involved.)
    """

    def __init__(
        self,
        exchange: Exchange,
        registry: SymbolRegistry,
        fill_timeout_s: float = 2.0,
    ) -> None:
        self.exchange = exchange
        self.registry = registry
        self.fill_timeout_s = fill_timeout_s

    def submit(self, draft: OrderDraft) -> ExecOutcome:
        events: list[str] = []

        ok, reason = validate_order(draft, self.registry)
        repaired = False
        if not ok:
            events.append(f"VALIDATE_FAIL:{reason}")
            draft = repair_order(draft, self.registry)
            repaired = True
            ok, reason = validate_order(draft, self.registry)
            if not ok:
                events.append(f"REVALIDATE_FAIL:{reason}")
                return ExecOutcome(VALIDATION_SKIP, None, repaired, events)
            events.append("REPAIRED")

        result = self.exchange.place_order(draft)
        events.append(f"ORDER_SENT:{result.status}")

        if result.status == "REJECTED":
            cat, _retryable = classify_error(result.error_code)
            events.append(f"REJECT:{cat}")
            if repaired:
                # resubmit-once rule: one repair per order, no second attempt
                return ExecOutcome(VALIDATION_SKIP, result, repaired, events)
            # one deterministic repair + single resubmit
            draft = repair_order(draft, self.registry)
            ok, reason = validate_order(draft, self.registry)
            if not ok:
                events.append(f"REVALIDATE_FAIL:{reason}")
                return ExecOutcome(VALIDATION_SKIP, result, True, events)
            result = self.exchange.place_order(draft)
            events.append(f"RESUBMIT:{result.status}")
            if result.status == "REJECTED":
                return ExecOutcome(VALIDATION_SKIP, result, True, events)
            repaired = True

        if result.status == "FILLED":
            return ExecOutcome("FILLED", result, repaired, events)

        # NEW → wait up to fill_timeout, then cancel (no chase)
        status = self.exchange.order_status(draft.symbol, result.order_id)
        if status.status == "FILLED":
            events.append("FILLED_WITHIN_TIMEOUT")
            return ExecOutcome("FILLED", status, repaired, events)
        self.exchange.cancel_order(draft.symbol, result.order_id)
        events.append("CANCELED_UNFILLED_NO_CHASE")
        return ExecOutcome("CANCELED_UNFILLED", status, repaired, events)


# --- SL placement: dual mechanism (doc 30 §3, doc 32 L2) ---

@dataclass
class StopLossState:
    mode: str                # CONDITIONAL / MARK_PRICE_POLL
    stop_price: float
    side: str                # side of the CLOSING order (opposite of position)
    order_id: str = ""


def place_stop_loss(
    exchange: Exchange,
    symbol: str,
    position_side: str,      # BUY (long) / SELL (short)
    qty: float,
    stop_price: float,
) -> StopLossState:
    """Conditional STOP (reduceOnly) primary; on -4120 fall back to mark-price polling.

    NEVER a naive LIMIT order on the book (doc 32 L2 — that's how the listener bot
    got instant unintended fills).
    """
    close_side = "SELL" if position_side == "BUY" else "BUY"
    draft = OrderDraft(
        symbol=symbol, side=close_side, price=stop_price, qty=qty,
        order_type="STOP_MARKET", reduce_only=True,
    )
    res = exchange.place_conditional_stop(draft, stop_price)
    if res.status in ("NEW", "FILLED"):
        return StopLossState("CONDITIONAL", stop_price, close_side, res.order_id)
    if res.error_code == -4120:
        # contract rejects conditional orders → position monitor polls mark price
        return StopLossState("MARK_PRICE_POLL", stop_price, close_side)
    raise RuntimeError(f"SL placement failed: {res.error_code} {res.error_msg}")
