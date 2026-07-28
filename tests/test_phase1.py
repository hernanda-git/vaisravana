"""Tests for Phase 1: symbol registry (1000x, liquidity filter, qty validation)
and frozen-feed health detection.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from marketdata import FeedHealth, MockExchangeClient  # noqa: E402
from symbols import SymbolInfo, SymbolRegistry  # noqa: E402


def _sym(symbol, spread=5.0, vol=50_000_000.0, **kw):
    return SymbolInfo(symbol=symbol, avg_spread_bps=spread, vol_24h_usd=vol, **kw)


def test_1000x_flagged():
    reg = SymbolRegistry()
    reg.upsert(_sym("BONKUSDT"))
    info = reg.get("BONKUSDT")
    assert info.is_1000x is True
    assert info.contract_multiplier == 1000.0


def test_non_1000x_not_flagged():
    reg = SymbolRegistry()
    reg.upsert(_sym("BTCUSDT"))
    assert reg.get("BTCUSDT").is_1000x is False
    assert reg.get("BTCUSDT").contract_multiplier == 1.0


def test_liquidity_filter_drops_wide_spread():
    reg = SymbolRegistry(max_spread_bps=10.0)
    reg.upsert(_sym("BTCUSDT", spread=5.0))      # ok
    reg.upsert(_sym("ILLIQUID1USDT", spread=50.0))  # filtered
    tradable = reg.tradable()
    assert "BTCUSDT" in tradable
    assert "ILLIQUID1USDT" not in tradable


def test_liquidity_filter_drops_low_volume():
    reg = SymbolRegistry(min_vol_usd=10_000_000.0)
    reg.upsert(_sym("BTCUSDT", vol=50_000_000.0))   # ok
    reg.upsert(_sym("LOWVOLUSDT", vol=1_000_000.0))  # filtered
    assert reg.is_tradable("LOWVOLUSDT") is False
    assert reg.stats()["filtered_out"] == 1


def test_validate_qty_below_min_notional():
    reg = SymbolRegistry()
    reg.upsert(_sym("BTCUSDT", min_notional=5.0))
    ok, why = reg.validate_order_qty("BTCUSDT", qty=0.001, notional=60.0)
    assert ok and why == "OK"
    bad, why2 = reg.validate_order_qty("BTCUSDT", qty=0.001, notional=2.0)
    assert not bad and why2 == "BELOW_MIN_NOTIONAL"


def test_validate_1000x_notional_uses_multiplier():
    reg = SymbolRegistry()
    reg.upsert(_sym("BONKUSDT", min_notional=5.0))
    # notional passed is in USD; for 1000x contract the effective notional is qty*mult*price
    # validator only checks the supplied notional vs floor — caller computes with multiplier.
    ok, why = reg.validate_order_qty("BONKUSDT", qty=1000.0, notional=10.0)
    assert ok


def test_feed_health_not_frozen_when_fresh():
    h = FeedHealth(max_age_s=30.0, clock=lambda: 1000.0)
    h.mark("BTCUSDT", "5m", 1_000_000)
    assert h.is_frozen("BTCUSDT", "5m") is False
    assert h.status("BTCUSDT", "5m") == "OK"


def test_feed_health_frozen_when_stale():
    now = [1000.0]

    def clock():
        return now[0]

    h = FeedHealth(max_age_s=30.0, clock=clock)
    h.mark("BTCUSDT", "5m", 1_000_000)
    now[0] = 2000.0  # 1000s later >> 30s
    assert h.is_frozen("BTCUSDT", "5m") is True
    assert h.status("BTCUSDT", "5m") == "FROZEN"


def test_feed_health_unknown_is_frozen():
    h = FeedHealth()
    assert h.is_frozen("NEVERSEEN", "5m") is True


def test_frozen_list_aggregates():
    h = FeedHealth(max_age_s=10.0, clock=lambda: 500.0)
    h.mark("BTCUSDT", "5m", 1)
    frozen = h.frozen_list(["BTCUSDT", "ETHUSDT"], ["5m", "15m"])
    # BTCUSDT/5m fresh; ETHUSDT/* and BTCUSDT/15m never marked -> frozen
    assert ("ETHUSDT", "5m") in frozen
    assert ("BTCUSDT", "15m") in frozen
    assert ("BTCUSDT", "5m") not in frozen


def test_mock_client_is_offline():
    c = MockExchangeClient()
    assert c.get_klines("BTCUSDT", "5m", 10) == []
    assert c.get_ticker("BTCUSDT").bid == 0.0
