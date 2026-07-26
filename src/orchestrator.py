"""Project Vaiśravaṇa — orchestrator: the per-candle PAPER loop (doc 30 §9).

Wires: MarketState → DecisionOrchestrator (engines→scores→gates→decisions_log)
→ paper fill → TradeLifecycle(open) → close on TP/SL/MAXHOLD → auto-evaluate
per (pair, tf, side) → kill-switch bookkeeping.

Mode is PAPER-only here (doc 30 §1 default UNREAL). LIVE execution is only
reachable through safety.promotion_gate() + human approval (Phase 10) — there is
deliberately no live order path in this module.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from config import ParameterSurface, default_surface
from decision import DecisionOrchestrator, DecisionRecord
from engines import MarketState
from evaluation import EvalReport, evaluate
from lifecycle import OpenTrade, TradeLifecycle
from safety import KillSwitch
from telemetry import Telemetry


@dataclass
class CandleOutcome:
    """What one candle-close cycle produced (for tests/monitoring)."""
    record: DecisionRecord | None
    opened: OpenTrade | None
    halted: bool = False
    halt_reason: str = ""


class PaperOrchestrator:
    """One ShadowTrader-equivalent loop body per (pair, tf) — doc 30 §8/§9."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        surface: ParameterSurface | None = None,
        kill: KillSwitch | None = None,
    ) -> None:
        self.conn = conn
        self.surface = surface or default_surface()
        self.decider = DecisionOrchestrator(conn, self.surface)
        self.lifecycle = TradeLifecycle(conn)
        self.telemetry = Telemetry(conn)
        self.kill = kill or KillSwitch(
            daily_loss_limit_pct=self.surface.daily_loss_limit_pct
        )
        self.open_trades: dict[tuple, OpenTrade] = {}   # (pair,tf,side) → 1 max (doc 30 §7)

    def on_candle_close(
        self,
        state: MarketState,
        *,
        entry_price: float,
        atr: float,
        daily_loss_pct: float = 0.0,
        adl_rank: int = 1,
        feed_frozen: bool = False,
        liquidity_ok: bool = True,
    ) -> CandleOutcome:
        # 0. kill-switch first (doc 30 §7): tripped → no decisions at all
        tripped, reason = self.kill.check_global(
            daily_loss_pct=daily_loss_pct, adl_rank=adl_rank, feed_frozen=feed_frozen
        )
        if tripped:
            self.telemetry.health("kill_switch", "FAIL", detail=reason)
            return CandleOutcome(None, None, halted=True, halt_reason=reason)

        # 1. decide (SL/TP derived from ATR multipliers, doc 21/doc 30 §3)
        #    provisional side from dual score determines SL direction; the gate
        #    then re-checks correctness.
        from scoring import decide
        prelim = decide(state, self.surface)
        if prelim.side == "SELL":
            sl = entry_price + self.surface.sl_atr_mult * atr
            tp = entry_price - self.surface.tp_atr_mult * atr
        else:
            sl = entry_price - self.surface.sl_atr_mult * atr
            tp = entry_price + self.surface.tp_atr_mult * atr

        record = self.decider.process(
            state,
            liquidity_ok=liquidity_ok,
            intraday_loss_pct=daily_loss_pct,
            sl_price=sl,
            entry_price=entry_price,
            leverage=self.surface.max_leverage,
        )
        if not record.actionable:
            return CandleOutcome(record, None)

        key = (state.symbol, state.tf, record.side)
        # per-key cooldown after losing streak (doc 30 §7)
        if self.kill.in_cooldown(*key):
            self.telemetry.exec_event(record.correlation_id, state.symbol, state.tf,
                                      "SKIP_COOLDOWN", side=record.side or "")
            return CandleOutcome(record, None)
        # max 1 open position per (pair×tf×side) — no stacking (doc 30 §7)
        if key in self.open_trades:
            return CandleOutcome(record, None)

        # 2. paper fill at entry (LIMIT@mid assumption, doc 30 §3)
        trade = self.lifecycle.open(
            correlation_id=record.correlation_id,
            pair=state.symbol, tf=state.tf, side=record.side,
            entry_price=entry_price, size=1.0, leverage=self.surface.max_leverage,
            sl_price=sl, tp_price=tp, decision_id=record.id,
            spread_bps=state.spread_bps, regime=state.regime,
            scores=record.scoring.sub_scores.as_dict(),
        )
        self.open_trades[key] = trade
        self.telemetry.exec_event(record.correlation_id, state.symbol, state.tf,
                                  "FILL", order_type="LIMIT", side=record.side,
                                  price=entry_price, qty=1.0, status="FILLED")
        return CandleOutcome(record, trade)

    def close_trade(
        self, pair: str, tf: str, side: str, exit_price: float, reason: str
    ) -> EvalReport | None:
        """Close the open (pair,tf,side) trade → log → auto-evaluate (doc 30 §5)."""
        key = (pair, tf, side)
        trade = self.open_trades.pop(key, None)
        if trade is None:
            return None
        res = self.lifecycle.close(trade, exit_price=exit_price, close_reason=reason)
        self.kill.record_close(pair, tf, side, win=bool(res["win"]))
        self.telemetry.exec_event(trade.correlation_id, pair, tf, "CLOSE",
                                  side=side, price=exit_price,
                                  status=reason)
        # auto-evaluate on every close (doc 30 §5 trigger)
        return evaluate(self.conn, pair, tf, side)
