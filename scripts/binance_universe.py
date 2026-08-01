"""Binance 24hr ticker-based dynamic pair selector for Vaiśravaṇa main bot.

Selects multiple top-momentum pairs dynamically each cycle from Binance fapi
24hr ticker endpoint. Filters by USDT-margined, min volume, and min absolute change.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Optional

log = logging.getLogger("vaisravana.universe")

FETCH_URL = os.getenv(
    "VAISRAVANA_UNIVERSE_URL",
    "https://fapi.binance.com/fapi/v1/ticker/24hr",
)
FETCH_TIMEOUT = int(os.getenv("VAISRAVANA_UNIVERSE_TIMEOUT", "10"))
MIN_VOLUME_USDT = float(os.getenv("VAISRAVANA_MIN_VOLUME", "500000"))
MIN_ABS_CHANGE_PCT = float(os.getenv("VAISRAVANA_MIN_CHANGE_PCT", "1.0"))
TOP_N = int(os.getenv("VAISRAVANA_PAIRS_COUNT", "15"))


def _fetch_tickers() -> list[dict]:
    try:
        req = urllib.request.Request(FETCH_URL, headers={"User-Agent": "VaisravanaBot/1.0"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
    except Exception as e:
        log.debug("universe: fetch failed (%s)", e)
        return []


def _is_eligible(ticker: dict) -> bool:
    symbol = ticker.get("symbol", "")
    if not symbol.endswith("USDT"):
        return False
    vol = float(ticker.get("volume", "0"))
    if vol < MIN_VOLUME_USDT:
        return False
    change = abs(float(ticker.get("priceChangePercent", "0")))
    if change < MIN_ABS_CHANGE_PCT:
        return False
    return True


def select_pairs(n: int | None = None, tickers: list[dict] | None = None) -> list[str]:
    """Return top-N pairs sorted by absolute price change (highest momentum).

    Picks the pairs with the largest absolute 24hr change, both directions.
    """
    if tickers is None:
        tickers = _fetch_tickers()
    if not tickers:
        return []

    eligible = [t for t in tickers if _is_eligible(t)]
    if not eligible:
        return []

    count = n or TOP_N
    eligible.sort(key=lambda t: abs(float(t.get("priceChangePercent", "0"))), reverse=True)
    selected = eligible[:count]
    symbols = [t.get("symbol", "") for t in selected]
    log.info("universe: selected %d pairs (vol>%.0f, |chg|>%.1f%%) — %s",
             len(symbols), MIN_VOLUME_USDT, MIN_ABS_CHANGE_PCT,
             ",".join(symbols[:5]) + ("..." if len(symbols) > 5 else ""))
    return symbols


def select_pair(bias_direction: str = "neutral", tickers: list[dict] | None = None) -> Optional[str]:
    """Single-pair selector (wave bot compatibility)."""
    if tickers is None:
        tickers = _fetch_tickers()
    if not tickers:
        return None

    eligible = [t for t in tickers if _is_eligible(t)]
    if not eligible:
        return None

    mode = "bearish" if bias_direction == "bearish" else "bullish"
    if mode == "bearish":
        eligible.sort(key=lambda t: float(t.get("priceChangePercent", "0")))
    else:
        eligible.sort(key=lambda t: float(t.get("priceChangePercent", "0")), reverse=True)

    pick = eligible[:TOP_N][0]
    symbol = pick.get("symbol", "")
    change = float(pick.get("priceChangePercent", "0"))
    log.info("universe: selected %s (bias=%s, change=%.2f%%)", symbol, bias_direction, change)
    return symbol
