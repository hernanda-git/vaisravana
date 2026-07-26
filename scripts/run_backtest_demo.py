"""Demo backtest run — synthetic candles, full pipeline, real DB, real report.

Usage:  python scripts/run_backtest_demo.py

This exercises the ENTIRE paper pipeline end-to-end (engines → gates →
decisions_log → paper fills → trade_logs → evaluation → report) on synthetic
data. It is NOT market validation — Phase 9 real-data runs require historical
klines from Binance (network). Output: reports/backtest_report.md.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from backtest import BacktestHarness, report_markdown  # noqa: E402
from db import init_db  # noqa: E402
from engines import MarketState  # noqa: E402
from marketdata import Candle  # noqa: E402


def synth_candles(seed: int, n: int = 400, start: float = 100.0) -> list[Candle]:
    rng = random.Random(seed)
    out, price = [], start
    trend = rng.choice([0.15, -0.1, 0.05])
    for i in range(n):
        drift = trend + rng.gauss(0, 0.4)
        o = price
        c = max(1.0, price + drift)
        hi = max(o, c) + abs(rng.gauss(0, 0.3))
        lo = min(o, c) - abs(rng.gauss(0, 0.3))
        out.append(Candle(ts=i * 300_000, o=o, h=hi, l=lo, c=c, v=1000 + rng.random() * 500))
        price = c
    return out


def state_from_candles(pair: str, tf: str):
    """Deterministic state builder: derives regime/structure flags from the data."""
    def factory(candles: list[Candle], i: int) -> MarketState:
        window = candles[max(0, i - 10): i + 1]
        closes = [c.c for c in window]
        up = closes[-1] > closes[0]
        strong = abs(closes[-1] - closes[0]) / closes[0] > 0.01
        vols = [c.v for c in window]
        vol_z = (vols[-1] - sum(vols) / len(vols)) / (max(vols) - min(vols) + 1e-9) * 3
        body = abs(candles[i].c - candles[i].o) / (candles[i].h - candles[i].l + 1e-9)
        return MarketState(
            symbol=pair, tf=tf,
            regime=("trending_bull" if up else "trending_bear") if strong else "range",
            htf_bias="bullish" if up else "bearish",
            body_ratio=body, vol_z=vol_z, delta_z=vol_z,
            bos=strong, hh=up, hl=up, lh=not up, ll=not up, choch=strong,
            liq_sweep=strong, eq_low=up, eq_high=not up, fvg=strong,
            atr_pct=0.01, spread_bps=1.5, funding_ok=True, adl_rank=1,
            last_close=candles[i].c,
        )
    return factory


def main() -> None:
    db_path = ROOT / "reports" / "backtest_demo.db"
    db_path.parent.mkdir(exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = init_db(db_path)

    pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    tfs = ["5m", "15m"]
    all_stats = []
    for pi, pair in enumerate(pairs):
        for ti, tf in enumerate(tfs):
            h = BacktestHarness(conn, state_from_candles(pair, tf))
            stats = h.run(pair, tf, synth_candles(seed=pi * 10 + ti))
            all_stats.append(stats)
            print(f"{pair} {tf}: candles={stats.candles} entries={stats.entries} "
                  f"TP={stats.tp_exits} SL={stats.sl_exits} MAXHOLD={stats.maxhold_exits} "
                  f"fees=${stats.fees_usd:.2f}")

    md = report_markdown(all_stats)
    out = ROOT / "reports" / "backtest_report.md"
    out.write_text(
        "> SYNTHETIC-DATA pipeline exercise (not market validation).\n"
        "> Real-data Phase 9 runs require Binance historical klines.\n\n" + md,
        encoding="utf-8",
    )
    print(f"\nreport → {out}")


if __name__ == "__main__":
    main()
