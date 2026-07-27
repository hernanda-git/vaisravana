"""Project Vaiśravaṇa — regime-conditioned sizing / vol targeting (P2-35).

Fixes F5 (thin 11% net margin + fixed 2x lev = tail wipeout risk): size by
VOLATILITY, not by a fixed 2x. In high-vol regimes or wide-SL setups, dial
leverage DOWN so the dollar risk per entry stays bounded — a vol-targeting layer.

This is a PURE function (no I/O, fully testable). The bot's entry path calls
`regime_leverage()` to pick the leverage actually used for sizing, so the
existing `size_position()` math (risk% / SL-distance) still governs notional.

Contract:
  - base leverage (from the surface) is the MAX allowed.
  - if ATR% (bar volatility) is high, scale leverage down proportionally so a
    1-SL move costs a similar fraction of equity regardless of vol.
  - in high_vol / breakout regimes, cap leverage harder (gaps/false breaks).
  - never exceed `base_leverage`; never go below `min_leverage` (keeps margin
    efficiency). Result is rounded to an int (Binance uses integer lev for USDⓈ-M).
"""

from __future__ import annotations

import math

# Reference ATR% at which leverage is "full" (base). Above this, scale down.
REF_ATR_PCT = 1.0
MIN_LEVERAGE = 1
# Hard cap on the fraction of equity a single 1-SL move may risk at max leverage.
MAX_SL_RISK_PCT = 5.0


def regime_leverage(
    base_leverage: int,
    atr_pct: float,
    regime: str = "range",
    min_leverage: int = MIN_LEVERAGE,
) -> int:
    """Vol-targeted leverage in [min_leverage, base_leverage].

    `atr_pct` = ATR / price * 100 (bar volatility). `regime` is the MarketState
    regime string (range/trending_bull/trending_bear/breakout/high_vol).
    """
    base = max(int(base_leverage), min_leverage)
    atr_pct = max(atr_pct, 0.0)

    # vol scaling: leverage ∝ REF_ATR_PCT / atr_pct, clamped to [min, base].
    if atr_pct <= 0:
        vol_factor = 1.0
    else:
        vol_factor = min(1.0, REF_ATR_PCT / atr_pct)
    lev = base * vol_factor

    # regime hard cap: high_vol / breakout are gap-prone -> weaker leverage.
    if regime in ("high_vol", "breakout"):
        lev = min(lev, max(min_leverage, base * 0.5))

    lev = max(min_leverage, min(base, int(round(lev))))
    return lev


def vol_target_notional(
    equity: float,
    risk_pct: float,
    sl_distance_pct: float,
    leverage: int,
) -> float:
    """Notional that risks `risk_pct`% of `equity` given an SL `sl_distance_pct`%
    away and `leverage`. Mirrors size_position() economics so the bot can pre-check
    that a 1-SL move costs <= MAX_SL_RISK_PCT of equity before committing.
    """
    if sl_distance_pct <= 0 or leverage <= 0:
        return 0.0
    risk_usd = equity * (risk_pct / 100.0)
    notional = risk_usd / (sl_distance_pct / 100.0) * leverage
    return notional


def sl_risk_pct(equity: float, notional: float, sl_distance_pct: float,
                leverage: int) -> float:
    """Reverse of vol_target_notional: % of equity lost if the SL hits."""
    if equity <= 0 or leverage <= 0:
        return 0.0
    return (notional / leverage) * (sl_distance_pct / 100.0) / equity * 100.0
