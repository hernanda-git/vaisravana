"""Fetch real Binance USDⓈ-M klines directly (VPS is not geo-blocked here).

Saves under data/klines/{PAIR}_{TF}.json for the honest backtest harness.
Mirrors the bot's own fetch_klines URL exactly.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "klines"
OUT.mkdir(parents=True, exist_ok=True)

# Binance futures use 1000x prefixed symbols for sub-cent tokens.
SYM_MAP = {
    "PEPE": "1000PEPEUSDT",
    "BONK": "1000BONKUSDT",
}
PAIRS = "BTCUSDT,ETHUSDT,SOLUSDT,PEPE,BONK,ENA,WLD,PENGU,AAVE,TAO,INJ,APE,PUMP,WIF,CRV".split(",")


def _binance_sym(pair: str) -> str:
    return SYM_MAP.get(pair, pair)
TFS = ["1m", "5m", "15m"]
LIMIT = 1500


def fetch(pair: str, tf: str, limit: int = LIMIT) -> list:
    sym = _binance_sym(pair)
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={tf}&limit={limit}"
    last = None
    for attempt in range(6):
        try:
            raw = json.loads(urllib.request.urlopen(url, timeout=20).read().decode())
            if not raw:
                raise RuntimeError("empty payload")
            return raw
        except Exception as e:
            last = e
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError(f"{pair} {tf}: {last}")


def main() -> None:
    for pair in PAIRS:
        for tf in TFS:
            path = OUT / f"{pair}_{tf}.json"
            if path.exists():
                print(f"skip {pair} {tf} (exists)")
                continue
            try:
                data = fetch(pair, tf)
                path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
                print(f"{pair} {tf}: {len(data)} candles -> {path.name}")
            except Exception as e:
                print(f"FAIL {pair} {tf}: {type(e).__name__} {e}")
            time.sleep(1.5)  # avoid Binance burst throttle between requests

if __name__ == "__main__":
    main()
