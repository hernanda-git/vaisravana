"""Project Vaiśravaṇa — market-data client abstraction + frozen-feed health (doc 22 §6, doc 32).

Offline-first: the real Binance client is injected behind the `ExchangeClient` protocol.
In paper/shadow mode a `MockExchangeClient` (or none) is used, so no network/keys needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Candle:
    ts: int          # open time (ms)
    o: float
    h: float
    l: float
    c: float
    v: float
    tb: float = 0.0  # v0.0.35: taker-buy base volume (klines idx 9) — feeds CVD


@dataclass
class OrderBook:
    symbol: str
    bid: float
    ask: float
    ts: int


@runtime_checkable
class ExchangeClient(Protocol):
    """Minimal surface the bot needs. Real impl wraps python-binance / connector."""

    def get_klines(self, symbol: str, tf: str, limit: int) -> list[Candle]: ...
    def get_ticker(self, symbol: str) -> OrderBook: ...
    def get_exchange_info(self) -> dict: ...


class FeedHealth:
    """Detects frozen/stale market data per (symbol, tf) (doc 22 §6, doc 32 group A).

    A feed is FROZEN if its last-seen timestamp is older than `max_age_s` OR a gap
    (missing candle) is detected. Blind-spot group A is the single most dangerous failure
    (bot trades on stale prices) — so this fails LOUD.
    """

    def __init__(self, max_age_s: float = 30.0, clock: callable = time.time) -> None:
        self.max_age_s = max_age_s
        self._clock = clock
        self._last_seen: dict[tuple[str, str], float] = {}
        self._last_ts: dict[tuple[str, str], int] = {}

    def mark(self, symbol: str, tf: str, candle_ts_ms: int) -> None:
        key = (symbol, tf)
        now = self._clock()
        self._last_seen[key] = now
        self._last_ts[key] = candle_ts_ms

    def age_s(self, symbol: str, tf: str) -> float | None:
        key = (symbol, tf)
        if key not in self._last_seen:
            return None
        return self._clock() - self._last_seen[key]

    def is_frozen(self, symbol: str, tf: str) -> bool:
        age = self.age_s(symbol, tf)
        return age is None or age > self.max_age_s

    def frozen_list(self, symbols: list[str], tfs: list[str]) -> list[tuple[str, str]]:
        return [(s, t) for s in symbols for t in tfs if self.is_frozen(s, t)]

    def status(self, symbol: str, tf: str) -> str:
        return "FROZEN" if self.is_frozen(symbol, tf) else "OK"


class MockExchangeClient:
    """Offline client for paper/shadow + tests. Returns empty/static data."""

    def get_klines(self, symbol: str, tf: str, limit: int) -> list[Candle]:
        return []

    def get_ticker(self, symbol: str) -> OrderBook:
        return OrderBook(symbol=symbol, bid=0.0, ask=0.0, ts=0)

    def get_exchange_info(self) -> dict:
        return {"symbols": []}
