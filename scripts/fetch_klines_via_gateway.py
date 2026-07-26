"""Fetch real Binance USDⓈ-M klines through the binance-gateway Fly VM (region: sin).

Local Binance is geo-blocked (ID); the Fly VM in Singapore is not. We pipe a small
python program to `flyctl ssh console -C python3`, which prints klines as JSON lines;
stdout is captured locally and saved under data/klines/.

Usage: python scripts/fetch_klines_via_gateway.py [pairs...] [--tf 5m,15m] [--limit 1500]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "klines"

REMOTE_PROG = """
import urllib.request, json, sys
pair, tf, limit = {pair!r}, {tf!r}, {limit}
u = f"https://fapi.binance.com/fapi/v1/klines?symbol={{pair}}&interval={{tf}}&limit={{limit}}"
data = json.loads(urllib.request.urlopen(u, timeout=20).read().decode())
print("KLINES_BEGIN")
print(json.dumps(data, separators=(",", ":")))
print("KLINES_END")
"""


def fetch(pair: str, tf: str, limit: int = 1500) -> list:
    prog = REMOTE_PROG.format(pair=pair, tf=tf, limit=limit)
    r = subprocess.run(
        ["flyctl", "ssh", "console", "-a", "binance-gateway", "-C", "python3"],
        input=prog, capture_output=True, text=True, timeout=120,
    )
    out = r.stdout
    if "KLINES_BEGIN" not in out:
        raise RuntimeError(f"{pair} {tf}: no payload. stderr={r.stderr[:200]} out={out[:200]}")
    payload = out.split("KLINES_BEGIN")[1].split("KLINES_END")[0].strip()
    data = json.loads(payload)
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"{pair} {tf}: bad payload {str(data)[:120]}")
    return data


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pairs = args or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    tfs = ["5m", "15m"]
    limit = 1500
    for a in sys.argv[1:]:
        if a.startswith("--tf"):
            tfs = a.split("=", 1)[1].split(",")
        if a.startswith("--limit"):
            limit = int(a.split("=", 1)[1])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for pair in pairs:
        for tf in tfs:
            path = OUT_DIR / f"{pair}_{tf}.json"
            data = fetch(pair, tf, limit)
            path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
            first_ts, last_ts = data[0][0], data[-1][0]
            print(f"{pair} {tf}: {len(data)} candles  {first_ts}..{last_ts}  → {path.name}")


if __name__ == "__main__":
    main()
