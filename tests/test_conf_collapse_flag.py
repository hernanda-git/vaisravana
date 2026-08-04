import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from execution import StopLossState, OrderResult
from monitor import Position, PositionMonitor


class Exchange:
    def __init__(self):
        self.price = 99.5
    def mark_price(self, symbol): return self.price
    def place_order(self, draft): return None
    def place_conditional_stop(self, draft, stop): return OrderResult("NEW", "ok")


def test_conf_collapse_can_be_disabled(monkeypatch):
    monkeypatch.setenv("VAISRAVANA_CONF_COLLAPSE_ENABLED", "0")
    ex = Exchange()
    mon = PositionMonitor(ex, clock=lambda: 100.0)
    mon.track(Position("c", "BTCUSDT", "1m", "BUY", 1.0, 100.0,
                       StopLossState("CONDITIONAL", 99.0, "SELL"), 105.0,
                       0.0, sl_on_exchange=False, tp_on_exchange=False))
    assert mon.tick() == []
    assert mon.positions["c"].closed is False



def test_conf_collapse_default_can_close(monkeypatch):
    monkeypatch.delenv("VAISRAVANA_CONF_COLLAPSE_ENABLED", raising=False)
    ex = Exchange()
    ex.price = 98.0
    mon = PositionMonitor(ex, clock=lambda: 100.0)
    mon.track(Position("c", "BTCUSDT", "1m", "BUY", 1.0, 100.0,
                       StopLossState("MARK_PRICE_POLL", 95.0, "SELL"), 105.0,
                       0.0, sl_on_exchange=False, tp_on_exchange=False))
    events = mon.tick()
    assert events and events[0].reason == "CONF_COLLAPSE"
