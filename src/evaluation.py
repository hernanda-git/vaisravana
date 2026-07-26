"""Project Vaiśravaṇa — Evaluation Engine (doc 23, doc 30 §5).

Per (pair, tf, SIDE) — LONG and SHORT are INDEPENDENT counters, never merged
(doc 30 §5). Rolling window = last 200 closed trades for that key.

Metrics + targets (doc 30 §5):
  Win Rate ≥ 85% (headline) · Expectancy > +0.2R · Profit Factor > 1.20 ·
  Max DD < 3% · Sharpe(R) > 0.5 · Fill rate > 95% · Avg slippage < 5 bps

Composite health (doc 23 — anti reward-hacking):
  Health = 0.35·PF + 0.25·(1−MaxDD) + 0.20·Expectancy + 0.20·FillRate

Attribution (doc 23):
  - per-regime expectancy
  - False Positive:  decision=ENTRY that ended in SL
  - False Negative:  decision=SKIP that (per shadow/harness) would have profited
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field

ROLLING_WINDOW = 200   # doc 30 §5


@dataclass
class EvalTargets:
    win_rate_pct: float = 85.0
    expectancy_r: float = 0.2
    profit_factor: float = 1.20
    max_dd_pct: float = 3.0
    sharpe: float = 0.5
    fill_rate_pct: float = 95.0
    avg_slippage_bps: float = 5.0


@dataclass
class EvalReport:
    pair: str
    tf: str
    side: str
    n_trades: int
    win_rate_pct: float
    expectancy_r: float
    profit_factor: float
    max_dd_pct: float
    sharpe: float
    passes: dict = field(default_factory=dict)

    @property
    def all_pass(self) -> bool:
        return bool(self.passes) and all(self.passes.values())

    def health(self, fill_rate: float = 1.0) -> float:
        """Composite health (doc 23). PF capped at 3 then normalized to [0,1]-ish scale."""
        pf_norm = min(self.profit_factor, 3.0) / 3.0
        dd_norm = 1.0 - min(self.max_dd_pct, 100.0) / 100.0
        exp_norm = max(min(self.expectancy_r, 1.0), -1.0)
        return round(0.35 * pf_norm + 0.25 * dd_norm + 0.20 * exp_norm + 0.20 * fill_rate, 4)

    def to_markdown(self) -> str:
        """eval_report.md block (doc 26 format)."""
        rows = [
            f"## Eval — {self.pair} {self.tf} {self.side} (n={self.n_trades})",
            "",
            "| Metric | Value | Target | Pass |",
            "|--------|-------|--------|------|",
            f"| Win Rate | {self.win_rate_pct:.2f}% | ≥85% | {'✅' if self.passes.get('win_rate') else '❌'} |",
            f"| Expectancy | {self.expectancy_r:+.3f}R | >+0.2R | {'✅' if self.passes.get('expectancy') else '❌'} |",
            f"| Profit Factor | {self.profit_factor:.2f} | >1.20 | {'✅' if self.passes.get('profit_factor') else '❌'} |",
            f"| Max DD | {self.max_dd_pct:.2f}% | <3% | {'✅' if self.passes.get('max_dd') else '❌'} |",
            f"| Sharpe(R) | {self.sharpe:.2f} | >0.5 | {'✅' if self.passes.get('sharpe') else '❌'} |",
        ]
        return "\n".join(rows)


def _closed_trades(conn: sqlite3.Connection, pair: str, tf: str, side: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r_multiple, pnl_usd, pnl_pct, win, regime, close_reason
           FROM trade_logs
           WHERE pair=? AND tf=? AND side=? AND ts_closed IS NOT NULL
           ORDER BY ts_closed DESC LIMIT ?""",
        (pair, tf, side, ROLLING_WINDOW),
    ).fetchall()


def evaluate(
    conn: sqlite3.Connection,
    pair: str,
    tf: str,
    side: str,
    targets: EvalTargets | None = None,
) -> EvalReport:
    """Rolling-200 evaluation for ONE (pair, tf, side) key (doc 30 §5)."""
    targets = targets or EvalTargets()
    rows = _closed_trades(conn, pair, tf, side)
    n = len(rows)
    if n == 0:
        return EvalReport(pair, tf, side, 0, 0.0, 0.0, 0.0, 0.0, 0.0,
                          passes={"win_rate": False})

    rs = [r["r_multiple"] or 0.0 for r in rows]
    wins = sum(r["win"] or 0 for r in rows)
    win_rate = 100.0 * wins / n
    expectancy = sum(rs) / n

    gross_profit = sum(x for x in rs if x > 0)
    gross_loss = abs(sum(x for x in rs if x < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    # max drawdown on cumulative pnl_pct (accumulated unreal equity curve, doc 30 §5)
    # rows are DESC; replay oldest→newest
    curve, cum, peak, max_dd = [], 0.0, 0.0, 0.0
    for r in reversed(rows):
        cum += (r["pnl_pct"] or 0.0)
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        curve.append(cum)

    sharpe = 0.0
    if n >= 2:
        stdev = statistics.pstdev(rs)
        sharpe = (statistics.mean(rs) / stdev) if stdev > 0 else 0.0

    passes = {
        "win_rate": win_rate >= targets.win_rate_pct,
        "expectancy": expectancy > targets.expectancy_r,
        "profit_factor": profit_factor > targets.profit_factor,
        "max_dd": max_dd < targets.max_dd_pct,
        "sharpe": sharpe > targets.sharpe,
    }
    return EvalReport(pair, tf, side, n, round(win_rate, 4), round(expectancy, 4),
                      round(profit_factor, 4) if profit_factor != float("inf") else float("inf"),
                      round(max_dd, 4), round(sharpe, 4), passes)


# --- attribution (doc 23) ---

def regime_attribution(conn: sqlite3.Connection, pair: str, tf: str, side: str) -> dict[str, float]:
    """Expectancy per regime → Sentinel learns which regime to disable/tweak."""
    rows = _closed_trades(conn, pair, tf, side)
    by_regime: dict[str, list[float]] = {}
    for r in rows:
        by_regime.setdefault(r["regime"] or "unknown", []).append(r["r_multiple"] or 0.0)
    return {k: round(sum(v) / len(v), 4) for k, v in by_regime.items() if v}


def false_positives(conn: sqlite3.Connection, pair: str, tf: str, side: str) -> int:
    """decision=ENTRY that ended in SL (doc 23) — join decisions_log↔trade_logs."""
    row = conn.execute(
        """SELECT COUNT(*) AS c
           FROM trade_logs t JOIN decisions_log d ON t.decision_id = d.id
           WHERE t.pair=? AND t.tf=? AND t.side=? AND d.decision='ENTRY'
             AND t.close_reason='SL' AND t.ts_closed IS NOT NULL""",
        (pair, tf, side),
    ).fetchone()
    return row["c"]


def false_negatives(
    conn: sqlite3.Connection,
    pair: str,
    tf: str,
    shadow_outcomes: dict[str, float],
) -> int:
    """decision=SKIP where the shadow/harness says it would have profited (doc 23).

    `shadow_outcomes` maps decision id → hypothetical R (supplied by the backtest
    harness / shadow engine; the evaluator itself never invents outcomes).
    """
    rows = conn.execute(
        "SELECT id FROM decisions_log WHERE pair=? AND tf=? AND decision='SKIP'",
        (pair, tf),
    ).fetchall()
    return sum(1 for r in rows if shadow_outcomes.get(r["id"], 0.0) > 0.0)
