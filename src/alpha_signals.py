"""Standalone main-bot research signals.

Pure, paper-safe helpers for noisy/complex markets. They do not place orders.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CvdDivergence:
    side: str | None
    strength: float
    reason: str


def cvd_divergence(price_returns: list[float], cvd_z: float | None,
                   *, price_threshold: float = 0.0015,
                   cvd_threshold: float = 1.0) -> CvdDivergence:
    """Detect simple price/order-flow divergence.

    BUY: price sold off while taker flow is positive.
    SELL: price rallied while taker flow is negative.
    It is a trigger candidate, never a guarantee; callers must apply fees,
    spread, regime, and risk gates.
    """
    if cvd_z is None or len(price_returns) < 2:
        return CvdDivergence(None, 0.0, "insufficient data")
    move = sum(price_returns)
    if move <= -price_threshold and cvd_z >= cvd_threshold:
        return CvdDivergence("BUY", min(1.0, (abs(move) / price_threshold + cvd_z / cvd_threshold) / 2), "price down / CVD positive")
    if move >= price_threshold and cvd_z <= -cvd_threshold:
        return CvdDivergence("SELL", min(1.0, (abs(move) / price_threshold + abs(cvd_z) / cvd_threshold) / 2), "price up / CVD negative")
    return CvdDivergence(None, 0.0, "no divergence")


def regime_tp_multiplier(regime: str, atr_pct: float, *, base: float) -> float:
    """Return bounded TP multiplier for the current volatility/regime."""
    if regime in {"trending_bull", "trending_bear", "breakout"}:
        mult = 1.15
    elif regime == "high_vol":
        mult = 1.05
    elif regime == "range":
        mult = 0.85
    else:
        mult = 1.0
    if atr_pct >= 0.02:
        mult *= 1.10
    elif atr_pct <= 0.005:
        mult *= 0.90
    return max(base * 0.75, min(base * 1.35, base * mult))
