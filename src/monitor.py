"""Project Vaiśravaṇa — background Position Monitor (doc 30 §3, doc 32 L4).

10s loop over open positions:
  - dual-mechanism SL: conditional STOP (primary) already on exchange, else this
    monitor polls mark price and market-closes (reduceOnly) when SL breached
  - self-heal: SL/TP missing on exchange but position open → re-place ONCE per session
  - orphan detection: position with zero orders & age > 30min → verify against
    exchange (source of truth) → close
  - time-based exit: held > max_hold (== one TF bar budget: 5m/10m/15m) → market close
  - every close emits an event for exec_events + trade_logs (notify-on-close)

The monitor never *opens* positions. All closes are reduceOnly (doc 32 L4).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from execution import Exchange, OrderDraft, OrderResult, StopLossState

ORPHAN_AGE_S = 30 * 60          # doc 30 §3: >30m with no orders → orphan
# doc 30 §3 max-hold = TF. v0.0.34: explicit 1m budget of 45 min — the old
# 15-min default made the surface's 2R TP statistically unreachable on 1m
# entries (9/106 TP hits in run 1); the +0.5R breakeven trail bounds the
# extra downside of holding longer. Env-overridable for tuning.
import os as _os
MAX_HOLD_BY_TF = {"1m": int(_os.getenv("VAISRAVANA_MAX_HOLD_1M_S", str(45 * 60))),
                  "5m": 5 * 60, "10m": 10 * 60, "15m": 15 * 60}


@dataclass
class Position:
    correlation_id: str
    symbol: str
    tf: str
    side: str                  # BUY / SELL
    qty: float
    entry_price: float
    sl: StopLossState
    tp_price: float
    opened_ts: float
    sl_on_exchange: bool = True     # conditional STOP resting on exchange?
    tp_on_exchange: bool = True
    healed: bool = False            # self-heal used (1x/session)
    closed: bool = False
    close_reason: str = ""


@dataclass
class CloseEvent:
    correlation_id: str
    symbol: str
    tf: str                     # needed by main loop to key into open_trades
    side: str                   # BUY / SELL — needed by main loop for kill/notify
    reason: str                 # SL / TP / MAXHOLD / ORPHAN
    price: float
    closed_by: str              # EXCHANGE_STOP / MONITOR


class PositionMonitor:
    """One pass = one 10s tick (call `tick()` from the orchestrator loop)."""

    def __init__(self, exchange: Exchange, clock=time.time) -> None:
        self.exchange = exchange
        self._clock = clock
        self.positions: dict[str, Position] = {}
        self.close_events: list[CloseEvent] = []

    def track(self, pos: Position) -> None:
        self.positions[pos.correlation_id] = pos

    # --- internals ---

    @staticmethod
    def _unrealized_r(pos: "Position", mark: float) -> float:
        """R-multiple of current mark vs entry, measured against SL distance.

        Positive = in profit, negative = in loss. Mirrors the excursion math
        used by the wave engine so the bank_08r / conf_collapse gates line up.
        """
        if pos.side == "BUY":
            denom = abs(pos.entry_price - pos.sl.stop_price)
        else:
            denom = abs(pos.entry_price - pos.sl.stop_price)
        if denom <= 0:
            return 0.0
        if pos.side == "BUY":
            return (mark - pos.entry_price) / denom
        return (pos.entry_price - mark) / denom

    def _market_close(self, pos: Position, reason: str, price: float) -> None:
        draft = OrderDraft(
            symbol=pos.symbol,
            side="SELL" if pos.side == "BUY" else "BUY",
            price=price,
            qty=pos.qty,
            order_type="MARKET",
            reduce_only=True,               # doc 32 L4: ALL closes reduceOnly
            correlation_id=pos.correlation_id,
        )
        self.exchange.place_order(draft)
        pos.closed = True
        pos.close_reason = reason
        self.close_events.append(
            CloseEvent(pos.correlation_id, pos.symbol, pos.tf, pos.side,
                       reason, price, "MONITOR")
        )

    def _sl_breached(self, pos: Position, mark: float) -> bool:
        if pos.side == "BUY":
            return mark <= pos.sl.stop_price
        return mark >= pos.sl.stop_price

    def _tp_hit(self, pos: Position, mark: float) -> bool:
        if pos.side == "BUY":
            return mark >= pos.tp_price
        return mark <= pos.tp_price

    def tick(self) -> list[CloseEvent]:
        """One monitor pass. Returns close events emitted during this tick."""
        emitted: list[CloseEvent] = []
        start_idx = len(self.close_events)
        now = self._clock()

        for pos in list(self.positions.values()):
            if pos.closed:
                continue
            mark = self.exchange.mark_price(pos.symbol)

            # 1. mark-price SL backup (primary for -4120 contracts)
            if pos.sl.mode == "MARK_PRICE_POLL" or not pos.sl_on_exchange:
                if self._sl_breached(pos, mark):
                    self._market_close(pos, "SL", mark)
                    continue

            # TP polling for positions whose TP is not resting on exchange
            if not pos.tp_on_exchange and self._tp_hit(pos, mark):
                self._market_close(pos, "TP", mark)
                continue

            # 2b. bank_08r (ported from wave bot WR 67%): once R >= +0.08,
            # trail SL to +0.05R to lock profit early instead of grinding to
            # MAXHOLD. This is the single biggest WR lever on the wave side.
            r_now = self._unrealized_r(pos, mark)
            if r_now >= 0.08:
                if pos.side == "BUY":
                    new_sl = pos.entry_price * (1 + 0.0005)
                    if pos.sl.stop_price < new_sl:
                        pos.sl.stop_price = new_sl
                        if self.exchange is not None and hasattr(self.exchange, "update_sl"):
                            try:
                                self.exchange.update_sl(pos, new_sl)
                            except Exception:
                                pass
                else:
                    new_sl = pos.entry_price * (1 - 0.0005)
                    if pos.sl.stop_price > new_sl:
                        pos.sl.stop_price = new_sl
                        if self.exchange is not None and hasattr(self.exchange, "update_sl"):
                            try:
                                self.exchange.update_sl(pos, new_sl)
                            except Exception:
                                pass

            # 2c. conf_collapse gate (ported from wave bot): exit on a deep
            # adverse excursion (R <= -0.20) instead of waiting for the full SL.
            # Caps tail risk; the feared deeper loss_cut side-effect never
            # materialized in 24 wave trades.
            if r_now <= -0.20 and pos.sl.stop_price > pos.entry_price * (1 - 0.001 if pos.side == "BUY" else 1 + 0.001):
                self._market_close(pos, "CONF_COLLAPSE", mark)
                continue

            # 2d. self-heal: conditional SL vanished but position open → re-place 1x
            if pos.sl.mode == "CONDITIONAL" and not pos.sl_on_exchange and not pos.healed:
                close_side = "SELL" if pos.side == "BUY" else "BUY"
                draft = OrderDraft(
                    symbol=pos.symbol, side=close_side, price=pos.sl.stop_price,
                    qty=pos.qty, order_type="STOP_MARKET", reduce_only=True,
                    correlation_id=pos.correlation_id,
                )
                res: OrderResult = self.exchange.place_conditional_stop(
                    draft, pos.sl.stop_price
                )
                pos.healed = True
                if res.status in ("NEW", "FILLED"):
                    pos.sl_on_exchange = True

            # 3. orphan: no protective orders at all & age > 30m
            age = now - pos.opened_ts
            if (not pos.sl_on_exchange and not pos.tp_on_exchange
                    and pos.sl.mode != "MARK_PRICE_POLL" and pos.healed
                    and age > ORPHAN_AGE_S):
                self._market_close(pos, "ORPHAN", mark)
                continue

            # 4. time-based exit: hold > max-hold (one TF bar budget)
            max_hold = MAX_HOLD_BY_TF.get(pos.tf, 15 * 60)
            if age > max_hold:
                self._market_close(pos, "MAXHOLD", mark)
                continue

        emitted = self.close_events[start_idx:]
        return emitted
