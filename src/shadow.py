"""Project Vaiśravaṇa — honest shadow replay for the Sentinel (doc 24 fase 3).

The previous shadow comparison re-weighted *stored* sub-scores and could only ever
ROLL BACK — re-weighting cannot change a trade's win/loss, so shadow expectancy could
never exceed baseline, making the Sentinel's "promote" branch unreachable.

This module instead re-simulates the FULL pipeline on raw candles with each candidate
ParameterSurface via `BacktestHarness`, producing genuine per-(pair,tf,side) EvalReports
for baseline vs candidate. Shadow can now actually beat baseline, so the Sentinel's
promote/rollback decision is real (doc 23 composite health).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

from backtest import BacktestHarness
from config import ParameterSurface
from db import init_db
from evaluation import EvalReport, evaluate
from marketdata import Candle


@dataclass
class ShadowComparison:
    """Mirrors sentinel.ShadowComparison's API so the Sentinel needs no changes."""

    baseline: EvalReport
    shadow: EvalReport

    @property
    def shadow_not_worse(self) -> bool:
        return (self.shadow.expectancy_r >= self.baseline.expectancy_r
                and self.shadow.max_dd_pct <= self.baseline.max_dd_pct)

    @property
    def health_improved(self) -> bool:
        return self.shadow.health() > self.baseline.health()

    @property
    def promotable(self) -> bool:
        return self.shadow_not_worse and self.health_improved


def _simulate(
    surface: ParameterSurface,
    factories: dict[tuple, Callable[[list, int], object]],
    max_hold_bars: int,
    fees: tuple,
) -> dict[tuple, EvalReport]:
    """Replay every (pair,tf) with `surface`; return per-(pair,tf,side) EvalReports."""
    conn = init_db(":memory:")
    harness = BacktestHarness(
        conn, None, surface=surface, max_hold_bars=max_hold_bars, fees=fees
    )
    reports: dict[tuple, EvalReport] = {}
    for key, factory in factories.items():
        pair, tf = key
        harness.state_factory = factory  # harness calls factory(candles, i)
        # we need candles; the caller stashes them on the factory via attribute
        candles = getattr(factory, "_candles", None)
        if not candles or len(candles) <= 20:
            continue
        harness.run(pair, tf, candles)
    for (pair, tf) in factories:
        for side in ("BUY", "SELL"):
            rep = evaluate(conn, pair, tf, side)
            if rep.n_trades:
                reports[(pair, tf, side)] = rep
    conn.close()
    return reports


def _aggregate(reports: list[EvalReport]) -> EvalReport:
    if not reports:
        return EvalReport("", "", "", 0, 0.0, 0.0, 0.0, 0.0, 0.0, passes={})
    n = sum(r.n_trades for r in reports)
    wins = sum(round(r.win_rate_pct / 100.0 * r.n_trades) for r in reports)
    exp = sum(r.expectancy_r * r.n_trades for r in reports) / n if n else 0.0
    dd = max((r.max_dd_pct for r in reports), default=0.0)
    finite_pf = [r.profit_factor for r in reports
                 if r.profit_factor != float("inf") and r.profit_factor > 0]
    pf = (sum(finite_pf) / len(finite_pf)) if finite_pf else float("inf")
    return EvalReport(
        pair="AGG", tf="", side="", n_trades=n,
        win_rate_pct=round(100.0 * wins / n, 4) if n else 0.0,
        expectancy_r=round(exp, 4),
        profit_factor=round(pf, 4) if pf != float("inf") else float("inf"),
        max_dd_pct=round(dd, 4), sharpe=0.0, passes={},
    )


def shadow_compare(
    baseline_surface: ParameterSurface,
    candidate_surface: ParameterSurface,
    factories: dict[tuple, Callable[[list, int], object]],
    max_hold_bars: int = 60,
    fees: tuple = (0.0005, 0.0002, 0.0005),
) -> ShadowComparison:
    """Genuine baseline-vs-candidate replay on the same candles.

    `factories` maps (pair, tf) -> state_factory(candles, i). Each factory must carry
    its candle series as `factory._candles` (set by the caller) so the harness can replay.
    """
    base = _aggregate(list(
        _simulate(baseline_surface, factories, max_hold_bars, fees).values()))
    cand = _aggregate(list(
        _simulate(candidate_surface, factories, max_hold_bars, fees).values()))
    return ShadowComparison(baseline=base, shadow=cand)
