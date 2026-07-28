"""Tests for Phase 4: execution — rounding, sizing, validate/repair, OrderManager,
SL dual mechanism, position monitor. All mocked; NO live calls (plan cross-cutting rule)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from execution import (  # noqa: E402
    OrderDraft,
    OrderManager,
    OrderResult,
    VALIDATION_SKIP,
    classify_error,
    place_stop_loss,
    repair_order,
    round_price,
    round_qty,
    size_position,
    validate_order,
)
from monitor import MAX_HOLD_BY_TF, Position, PositionMonitor  # noqa: E402
from symbols import SymbolInfo, SymbolRegistry  # noqa: E402


def _registry() -> SymbolRegistry:
    reg = SymbolRegistry()
    reg.bulk_load([
        SymbolInfo(symbol="BTCUSDT", tick_size=0.1, step_size=0.001,
                   min_notional=100.0, avg_spread_bps=1.0, vol_24h_usd=1e10),
        # 1000x meme perp: integer lots, tiny price (doc 32 L2)
        SymbolInfo(symbol="1000BONKUSDT", tick_size=0.0000001, step_size=1.0,
                   min_notional=5.0, avg_spread_bps=3.0, vol_24h_usd=1e8),
    ])
    return reg


class MockExchange:
    """Scriptable mock exchange. reject_codes: list of codes for successive place_order."""

    def __init__(self, reject_codes=None, fill=True, stop_reject_code=None, mark=100.0):
        self.reject_codes = list(reject_codes or [])
        self.fill = fill
        self.stop_reject_code = stop_reject_code
        self._mark = mark
        self.placed: list[OrderDraft] = []
        self.stops: list[OrderDraft] = []
        self.canceled: list[str] = []

    def place_order(self, draft):
        self.placed.append(draft)
        if self.reject_codes:
            code = self.reject_codes.pop(0)
            return OrderResult("REJECTED", error_code=code, error_msg="mock reject")
        if self.fill:
            return OrderResult("FILLED", order_id="o1", filled_qty=draft.qty,
                               avg_price=draft.price)
        return OrderResult("NEW", order_id="o1")

    def cancel_order(self, symbol, order_id):
        self.canceled.append(order_id)
        return OrderResult("CANCELED", order_id=order_id)

    def order_status(self, symbol, order_id):
        return OrderResult("FILLED" if self.fill else "NEW", order_id=order_id)

    def place_conditional_stop(self, draft, stop_price):
        self.stops.append(draft)
        if self.stop_reject_code is not None:
            return OrderResult("REJECTED", error_code=self.stop_reject_code)
        return OrderResult("NEW", order_id="sl1")

    def mark_price(self, symbol):
        return self._mark


# --- rounding / sizing (doc 30 §3, doc 32 L2) ---

def test_round_price_to_tick():
    info = SymbolInfo(symbol="BTCUSDT", tick_size=0.1)
    assert round_price(100.17, info) == pytest.approx(100.1)


def test_round_qty_integer_lots_1000x():
    info = SymbolInfo(symbol="1000BONKUSDT", step_size=1.0)
    assert round_qty(123.9, info) == 123.0


def test_sizing_loops_up_to_min_notional():
    """1000x perp: risk-based qty too small for minNotional → bump in stepSize."""
    info = SymbolInfo(symbol="1000BONKUSDT", step_size=1.0, min_notional=5.0)
    qty = size_position(equity=10_000, risk_per_trade_pct=0.25, entry=0.02,
                        sl_price=0.0199, leverage=2, info=info)
    assert qty > 0 and qty * 0.02 >= 5.0
    assert qty == int(qty)  # integer lots


def test_sizing_respects_margin_cap():
    info = SymbolInfo(symbol="BTCUSDT", step_size=0.001, min_notional=100.0)
    qty = size_position(equity=1_000, risk_per_trade_pct=0.25, entry=100.0,
                        sl_price=99.9, leverage=2, info=info, free_margin=1_000)
    # notional*lev must be ≤ 50% of free margin
    assert qty * 100.0 * 2 <= 500.0 + 1e-6


def test_sizing_zero_when_sl_equals_entry():
    info = SymbolInfo(symbol="BTCUSDT")
    assert size_position(1000, 0.25, 100.0, 100.0, 2, info) == 0.0


# --- validate / repair (doc 32 L3) ---

def test_validate_rejects_off_grid_then_repair_fixes():
    reg = _registry()
    bad = OrderDraft(symbol="BTCUSDT", side="BUY", price=100.17, qty=1.0005)
    ok, reason = validate_order(bad, reg)
    assert not ok
    fixed = repair_order(bad, reg)
    ok2, reason2 = validate_order(fixed, reg)
    assert ok2, reason2


def test_error_categories_doc32_l7():
    assert classify_error(401) == ("AUTH", False)
    assert classify_error(429) == ("RATE_LIMIT", True)
    assert classify_error(503) == ("SERVER", True)
    assert classify_error(None, network=True) == ("NETWORK", True)
    assert classify_error(-4130) == ("ORDER_REJECT", False)


# --- OrderManager (doc 30 §3) ---

def test_order_manager_repairs_and_resubmits_once():
    reg = _registry()
    ex = MockExchange(reject_codes=[-4130])   # first send rejected, resubmit fills
    om = OrderManager(ex, reg)
    out = om.submit(OrderDraft(symbol="BTCUSDT", side="BUY", price=100.1, qty=1.0))
    assert out.status == "FILLED" and out.repaired
    assert len(ex.placed) == 2


def test_order_manager_double_reject_is_validation_skip():
    reg = _registry()
    ex = MockExchange(reject_codes=[-4130, -4130])
    om = OrderManager(ex, reg)
    out = om.submit(OrderDraft(symbol="BTCUSDT", side="BUY", price=100.1, qty=1.0))
    assert out.status == VALIDATION_SKIP
    assert len(ex.placed) == 2   # resubmit ONCE, never a third


def test_order_manager_no_chase_cancels_unfilled():
    reg = _registry()
    ex = MockExchange(fill=False)
    om = OrderManager(ex, reg)
    out = om.submit(OrderDraft(symbol="BTCUSDT", side="BUY", price=100.1, qty=1.0))
    assert out.status == "CANCELED_UNFILLED"
    assert ex.canceled == ["o1"]


def test_unrepairable_draft_is_validation_skip():
    reg = _registry()
    ex = MockExchange()
    om = OrderManager(ex, reg)
    out = om.submit(OrderDraft(symbol="NOPEUSDT", side="BUY", price=1.0, qty=1.0))
    assert out.status == VALIDATION_SKIP
    assert ex.placed == []       # never sent


# --- SL dual mechanism (doc 32 L2) ---

def test_sl_conditional_stop_primary():
    ex = MockExchange()
    st = place_stop_loss(ex, "BTCUSDT", "BUY", 1.0, 99.0)
    assert st.mode == "CONDITIONAL" and st.side == "SELL"
    assert ex.stops[0].reduce_only and ex.stops[0].order_type == "STOP_MARKET"


def test_sl_falls_back_to_mark_price_on_4120():
    ex = MockExchange(stop_reject_code=-4120)
    st = place_stop_loss(ex, "1000BONKUSDT", "SELL", 100.0, 0.021)
    assert st.mode == "MARK_PRICE_POLL" and st.side == "BUY"


# --- Position Monitor (doc 32 L4) ---

def _pos(sl_mode="MARK_PRICE_POLL", side="BUY", tf="5m", opened=0.0, **kw):
    from execution import StopLossState
    return Position(
        correlation_id="c1", symbol="BTCUSDT", tf=tf, side=side, qty=1.0,
        entry_price=100.0,
        sl=StopLossState(sl_mode, kw.pop("stop", 99.0), "SELL" if side == "BUY" else "BUY"),
        tp_price=kw.pop("tp", 105.0), opened_ts=opened,
        sl_on_exchange=(sl_mode == "CONDITIONAL"), tp_on_exchange=False, **kw,
    )


def test_monitor_mark_price_sl_closes_long():
    ex = MockExchange(mark=98.5)
    mon = PositionMonitor(ex, clock=lambda: 10.0)
    mon.track(_pos())
    events = mon.tick()
    assert len(events) == 1 and events[0].reason == "SL"
    close = ex.placed[-1]
    assert close.reduce_only and close.side == "SELL" and close.order_type == "MARKET"


def test_monitor_short_sl_breach_is_upside():
    ex = MockExchange(mark=101.5)
    mon = PositionMonitor(ex, clock=lambda: 10.0)
    mon.track(_pos(side="SELL", stop=101.0, tp=95.0))
    events = mon.tick()
    assert len(events) == 1 and events[0].reason == "SL"
    assert ex.placed[-1].side == "BUY"   # closing a short = BUY reduceOnly


def test_monitor_self_heals_lost_conditional_sl_once():
    ex = MockExchange(mark=100.0)
    mon = PositionMonitor(ex, clock=lambda: 10.0)
    p = _pos(sl_mode="CONDITIONAL")
    p.sl_on_exchange = False          # SL vanished from exchange
    mon.track(p)
    mon.tick()
    assert p.healed and p.sl_on_exchange
    assert len(ex.stops) == 1
    mon.tick()
    assert len(ex.stops) == 1          # 1x per session, never re-placed again


def test_monitor_max_hold_closes_at_tf_budget():
    ex = MockExchange(mark=100.0)
    now = MAX_HOLD_BY_TF["5m"] + 1.0
    mon = PositionMonitor(ex, clock=lambda: now)
    mon.track(_pos(tf="5m", opened=0.0))
    events = mon.tick()
    assert len(events) == 1 and events[0].reason == "MAXHOLD"
