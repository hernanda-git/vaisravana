"""Project Vaiśravaṇa — walk-forward OOS demo (P1-33).

Runs the rolling walk-forward harness on synthetic (offline) candles so CI/you can
see the loop produce multiple OOS folds WITHOUT network. With real klines in
data/*.csv it replays them instead.

Usage:
    python scripts/run_walk_forward.py [--pair BTCUSDT] [--tf 1m] [--train 1000]
                                       [--test 500] [--step 500] [--bars 2600]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from engines import MarketState  # noqa: E402
from marketdata import Candle  # noqa: E402
from walk_forward import walk_forward  # noqa: E402
from config import default_surface  # noqa: E402

try:
    from run_backtest_real import load, state_factory  # real, honest MarketState
except Exception:
    load = None
    state_factory = None


def synth(pair: str, tf: str, n: int = 2600, seed: int = 7) -> list[Candle]:
    candles = []
    price = 100.0 + hash((pair, tf)) % 50
    for i in range(n):
        shock = math.sin(i / 11.0 + seed) * 0.4 + math.sin(i / 3.0) * 0.15
        price = max(1.0, price * (1 + 0.001 * shock))
        o = price
        c = price * (1 + 0.0008 * math.sin(i / 7.0))
        h = max(o, c) * (1 + 0.0012 * abs(math.sin(i / 5.0)))
        l = min(o, c) * (1 - 0.0012 * abs(math.cos(i / 5.0)))
        candles.append(Candle(o=round(o, 2), h=round(h, 2), l=round(l, 2),
                              c=round(c, 2), v=1000.0, ts=i * 60_000))
    return candles


def _neutral_factory(candles, i):
    return MarketState(symbol="BTCUSDT", tf="1m")


def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="BTCUSDT")
    ap.add_argument("--tf", default="1m")
    ap.add_argument("--train", type=int, default=1000)
    ap.add_argument("--test", type=int, default=500)
    ap.add_argument("--step", type=int, default=500)
    ap.add_argument("--bars", type=int, default=2600)
    args = ap.parse_args()

    # real klines if present (honest state), else synth + neutral (offline proof)
    candles = None
    factory = None
    if load is not None:
        try:
            candles = load(args.pair, args.tf)
            factory = state_factory(args.pair, args.tf)
        except FileNotFoundError:
            candles = None
    if candles is None:
        candles = synth(args.pair, args.tf, n=args.bars)
        factory = _neutral_factory
    surface = default_surface()
    res = walk_forward(candles, factory, pair=args.pair, tf=args.tf,
                       train_bars=args.train, test_bars=args.test, step=args.step)

    src = "REAL klines" if load is not None and len(candles) else "SYNTH (offline)"
    print(f"# Walk-Forward OOS — {args.pair} {args.tf}  [{src}]")
    print(f"- folds={res.folds}  OOS entries={res.oos_entries}  OOS trades={res.oos_trades}")
    print("- each fold scores ONLY its test window; train window skipped (true OOS)")
    for side, rep in res.reports.items():
        print(f"  {side}: n={rep.n_trades} WR={rep.win_rate_pct:.1f}% "
              f"exp={rep.expectancy_r:+.3f}R net$={rep.net_expectancy_usd:+.4f} "
              f"PF={rep.profit_factor}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
