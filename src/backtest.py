"""Project Vaiśravaṇa — backtest / replay harness (doc 30 §backtest, doc 28 group E).

Replays historical candles per (pair, tf) through the PAPER pipeline:
  candle → derive MarketState → PaperOrchestrator.on_candle_close →
  simulate TP/SL/MAXHOLD exits from subsequent candles → trade_logs → evaluate.

Anti-overfitting (doc 28 G / plan Phase 9 risk):
  - `split()` provides rolling in-sample / out-of-sample partitions.
  - Fees: Binance USDⓈ-M VIP0 assumption — maker 0.02%, taker 0.05%
    ([OPEN] in doc 31, resolved here as VIP0; entries are LIMIT (maker),
    SL/MAXHOLD exits are market (taker), TP is limit (maker)).

The harness NEVER fabricates outcomes: every simulated fill/exit is derived from
actual candle high/low crossings.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from engines import MarketState
from evaluation import EvalReport, evaluate
from marketdata import Candle
from orchestrator import PaperOrchestrator

# Honest fee model (doc 28 group E): the 1m "jump" cadence is a TAKER at entry
# (marketable limit), TP is a maker limit, SL/MAXHOLD are taker. Previous harness
# assumed maker entry (0.02%) — too optimistic. Defaults below are realistic VIP0.
MAKER_FEE = 0.0002   # Binance USDⓈ-M VIP0 maker 0.02%
TAKER_FEE = 0.0005   # VIP0 taker 0.05%
MAX_HOLD_BARS = 60   # HONEST default: up to 60 bars (≈1h on 1m) before MAXHOLD,
                     # not a single next-bar gamble. Configurable per run.


def split(candles: list[Candle], oos_frac: float = 0.3) -> tuple[list[Candle], list[Candle]]:
    """In-sample / out-of-sample split (doc 28 group E: OOS decay)."""
    cut = int(len(candles) * (1.0 - oos_frac))
    return candles[:cut], candles[cut:]


@dataclass
class ReplayStats:
    pair: str
    tf: str
    candles: int = 0
    entries: int = 0
    tp_exits: int = 0
    sl_exits: int = 0
    maxhold_exits: int = 0
    fees_usd: float = 0.0
    reports: dict = field(default_factory=dict)   # side -> EvalReport


def _atr(candles: list[Candle], i: int, period: int = 14) -> float:
    """Simple ATR(14) on true ranges of the last `period` bars ending at i."""
    lo = max(1, i - period + 1)
    trs = []
    for j in range(lo, i + 1):
        prev_c = candles[j - 1].c
        tr = max(candles[j].h - candles[j].l,
                 abs(candles[j].h - prev_c),
                 abs(candles[j].l - prev_c))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


class BacktestHarness:
    """Replay one (pair, tf) series through the paper pipeline.

    `state_factory(candles, i) -> MarketState` builds the engine input per bar —
    injected so tests can use deterministic fixtures and the real system can use
    the full indicator stack without this module depending on it.

    SL/TP are derived **inside** the orchestrator from the surface's ATR multipliers,
    exactly as production does (so backtest == live logic). The only knobs here are
    `max_hold_bars` (how many bars before MAXHOLD) and `fees` (entry, tp, exit).
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        state_factory,
        orchestrator: PaperOrchestrator | None = None,
        surface=None,
        max_hold_bars: int = MAX_HOLD_BARS,
        fees: tuple[float, float, float] = (TAKER_FEE, MAKER_FEE, TAKER_FEE),
    ) -> None:
        self.conn = conn
        self.state_factory = state_factory
        self.orch = orchestrator or PaperOrchestrator(conn, surface)
        self.max_hold_bars = max_hold_bars
        # (entry_fee, tp_fee, exit_fee) — entry is TAKER for the 1m jump cadence
        self.entry_fee, self.tp_fee, self.exit_fee = fees

    def run(self, pair: str, tf: str, candles: list[Candle]) -> ReplayStats:
        stats = ReplayStats(pair=pair, tf=tf, candles=len(candles))

        for i in range(14, len(candles) - 1):
            state: MarketState = self.state_factory(candles, i)
            entry_price = candles[i].c
            atr = _atr(candles, i)
            if atr <= 0:
                continue

            out = self.orch.on_candle_close(state, entry_price=entry_price, atr=atr)
            if out.opened is None:
                continue
            stats.entries += 1
            side = out.opened.side
            sl, tp = out.opened.sl_price, out.opened.tp_price

            # walk forward until TP/SL/MAXHOLD — outcome from REAL candle extremes
            exit_price, reason = None, None
            for k in range(i + 1, min(i + 1 + self.max_hold_bars, len(candles))):
                bar = candles[k]
                if side == "BUY":
                    # conservative: if both touched in one bar, assume SL first
                    if bar.l <= sl:
                        exit_price, reason = sl, "SL"
                        break
                    if bar.h >= tp:
                        exit_price, reason = tp, "TP"
                        break
                else:
                    if bar.h >= sl:
                        exit_price, reason = sl, "SL"
                        break
                    if bar.l <= tp:
                        exit_price, reason = tp, "TP"
                        break
            if reason is None:
                k = min(i + self.max_hold_bars, len(candles) - 1)
                exit_price, reason = candles[k].c, "MAXHOLD"

            # honest fees: entry taker (1m jump), TP maker, SL/MAXHOLD taker
            exit_fee = self.tp_fee if reason == "TP" else self.exit_fee
            stats.fees_usd += entry_price * self.entry_fee + exit_price * exit_fee

            self.orch.close_trade(pair, tf, side, exit_price=exit_price, reason=reason)
            if reason == "TP":
                stats.tp_exits += 1
            elif reason == "SL":
                stats.sl_exits += 1
            else:
                stats.maxhold_exits += 1

        for side in ("BUY", "SELL"):
            rep = evaluate(self.conn, pair, tf, side)
            if rep.n_trades:
                stats.reports[side] = rep
        return stats


def report_markdown(all_stats: list[ReplayStats]) -> str:
    """Aggregate WR distribution report (plan Phase 9 item 2/5) for chronicle.md."""
    lines = ["# Backtest Report — per (pair, tf, side)", "",
             "| Pair | TF | Side | Trades | WR | Expectancy | PF | MaxDD |",
             "|------|----|------|--------|----|------------|----|-------|"]
    for st in all_stats:
        for side, rep in st.reports.items():
            pf = f"{rep.profit_factor:.2f}" if rep.profit_factor != float("inf") else "∞"
            lines.append(
                f"| {st.pair} | {st.tf} | {side} | {rep.n_trades} "
                f"| {rep.win_rate_pct:.1f}% | {rep.expectancy_r:+.3f}R "
                f"| {pf} | {rep.max_dd_pct:.2f}% |"
            )
    return "\n".join(lines)
