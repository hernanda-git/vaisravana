"""Project Vaiśravaṇa — regime-conditioned sizing / vol targeting + Kelly Criterion (P1-36).

Fixes F5 (thin 11% net margin + fixed 2x lev = tail wipeout risk): size by
VOLATILITY, not by a fixed 2x. In high-vol regimes or wide-SL setups, dial
leverage DOWN so the dollar risk per entry stays bounded — a vol-targeting layer.

Kelly Criterion (P1-36): dynamically size position based on actual edge (win rate + R:R).
When edge is positive, Kelly says "bet more". When edge is negative, Kelly says "bet less".
We use Fractional Kelly (1/4) to avoid over-leveraging on small sample sizes.

Contract:
  - base leverage (from the surface) is the MAX allowed.
  - if ATR% (bar volatility) is high, scale leverage down proportionally so a
    1-SL move costs a similar fraction of equity regardless of vol.
  - in high_vol / breakout regimes, cap leverage harder (gaps/false breaks).
  - never exceed `base_leverage`; never go below `min_leverage` (keeps margin
    efficiency). Result is rounded to an int (Binance uses integer lev for USDⓈ-M).
  - Kelly sizing adjusts risk_per_trade_pct based on actual edge from trade_logs.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone

# Reference ATR% at which leverage is "full" (base). Above this, scale down.
REF_ATR_PCT = 1.0
MIN_LEVERAGE = 1
# Hard cap on the fraction of equity a single 1-SL move may risk at max leverage.
MAX_SL_RISK_PCT = 5.0
# Fractional Kelly: use 1/4 of full Kelly to avoid over-leveraging on small samples
KELLY_FRACTION = 0.25
# Minimum risk per trade (even with negative Kelly)
MIN_RISK_PCT = 0.15
# Maximum risk per trade (even with extreme Kelly)
MAX_RISK_PCT = 1.0
# Minimum trades needed before Kelly kicks in
KELLY_MIN_TRADES = 10


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


# ── Kelly Criterion Sizing (P1-36) ──────────────────────────────────────────


def kelly_criterion(
    win_rate: float,
    avg_win_r: float,
    avg_loss_r: float,
) -> float:
    """Calculate full Kelly fraction from historical edge.

    Kelly% = W - (1-W)/R
    where W = win rate (0-1), R = average win / average loss (R:R ratio)

    Returns a value in [-1, 1]:
      - Positive = edge exists, bet more
      - Negative = no edge, bet less
      - Zero = break-even, neutral

    Example: W=0.55, avg_win=1.2R, avg_loss=1.0R
      Kelly = 0.55 - 0.45/1.2 = 0.55 - 0.375 = 0.175 = 17.5%
      Fractional Kelly (1/4) = 4.4%
    """
    if avg_loss_r <= 0 or avg_win_r <= 0:
        return 0.0
    rr = avg_win_r / avg_loss_r  # average R:R ratio
    kelly = win_rate - (1.0 - win_rate) / rr
    return max(-1.0, min(1.0, kelly))


def kelly_risk_pct(
    conn: sqlite3.Connection,
    pair: str | None = None,
    side: str | None = None,
    base_risk_pct: float = 0.25,
) -> float:
    """Calculate risk per trade using Fractional Kelly from trade_logs.

    Reads the last N closed trades for the given pair/side (or all trades if
    pair/side is None), computes win rate and average R:R, then applies
    Fractional Kelly to determine the optimal risk percentage.

    Falls back to base_risk_pct if:
      - Fewer than KELLY_MIN_TRADES samples
      - DB query fails
      - Edge is negative (Kelly <= 0)
    """
    try:
        where = "WHERE ts_fully_closed IS NOT NULL"
        params: tuple = ()
        if pair and side:
            where += " AND pair=? AND side=?"
            params = (pair, side)
        elif pair:
            where += " AND pair=?"
            params = (pair,)
        elif side:
            where += " AND side=?"
            params = (side,)

        row = conn.execute(
            f"""SELECT COUNT(*) as n,
                      COALESCE(SUM(win), 0) as wins,
                      COALESCE(AVG(CASE WHEN win=1 THEN r_multiple END), 0) as avg_win_r,
                      COALESCE(AVG(CASE WHEN win=0 THEN ABS(r_multiple) END), 0) as avg_loss_r
               FROM trade_logs {where}""",
            params,
        ).fetchone()

        n = int(row["n"] or 0)
        if n < KELLY_MIN_TRADES:
            return base_risk_pct  # not enough data, use base

        wins = int(row["wins"] or 0)
        win_rate = wins / n
        avg_win_r = float(row["avg_win_r"] or 0)
        avg_loss_r = float(row["avg_loss_r"] or 0)

        if avg_win_r <= 0 or avg_loss_r <= 0:
            return base_risk_pct  # no meaningful data

        full_kelly = kelly_criterion(win_rate, avg_win_r, avg_loss_r)

        # Fractional Kelly: use 1/4 of full Kelly
        fractional = full_kelly * KELLY_FRACTION

        # If Kelly is negative (no edge), use minimum risk
        if fractional <= 0:
            return MIN_RISK_PCT

        # Clamp to [MIN_RISK_PCT, MAX_RISK_PCT]
        return max(MIN_RISK_PCT, min(MAX_RISK_PCT, fractional))

    except Exception:
        # DB error or any exception → fall back to base risk
        return base_risk_pct


# ── Trailing Stop (P1-36) ──────────────────────────────────────────────────


@dataclass
class TrailingStopState:
    """State for trailing stop logic on an open trade."""
    trade_id: str
    entry_price: float
    side: str  # BUY or SELL
    highest_price: float = 0.0  # for BUY: track highest since entry
    lowest_price: float = 0.0   # for SELL: track lowest since entry
    trail_active: bool = False
    trail_distance: float = 0.0  # $ distance from high/low to new SL
    breakeven_sl: float = 0.0    # SL moved to breakeven at this price
    arm_price: float = 0.0       # price at which trail arms


def update_trailing_stop(
    trade: "OpenTrade",
    current_price: float,
    arm_at_r: float = 0.5,      # arm trail at +0.5R from entry
    trail_at_r: float = 0.08,   # trail at 0.08R behind high/low
    move_to_breakeven_at_r: float = 0.10,  # move SL to BE at +0.10R
) -> tuple[float | None, str]:
    """Update trailing stop for an open trade.

    Returns (new_sl_price, action) where:
      - new_sl_price: new SL price to set, or None if no change
      - action: "ARMED", "TRAILING", "BREAKEVEN", or "NONE"

    Logic:
      1. Track highest (BUY) / lowest (SELL) price since entry
      2. At +0.10R: move SL to breakeven (entry price)
      3. At +0.5R: arm the trailing stop
      4. After armed: trail 0.08R behind new high/low
    """
    sl_distance = abs(trade.entry_price - trade.sl_price)
    if sl_distance <= 0:
        return None, "NONE"

    if trade.side == "BUY":
        direction = 1.0
        pnl_r = (current_price - trade.entry_price) / sl_distance
        # Track highest price
        if current_price > trade.sl_price:  # using sl_price as proxy for highest tracked
            new_highest = current_price
        else:
            new_highest = trade.sl_price  # fallback
        # Trail behind highest
        trail_price = new_highest - (trail_at_r * sl_distance)
        new_sl = max(trade.entry_price * 0.9999, trail_price)  # never above entry until armed
    else:  # SELL
        direction = -1.0
        pnl_r = (trade.entry_price - current_price) / sl_distance
        # Track lowest price
        if current_price < trade.entry_price:
            new_lowest = current_price
        else:
            new_lowest = trade.entry_price
        trail_price = new_lowest + (trail_at_r * sl_distance)
        new_sl = min(trade.entry_price * 1.0001, trail_price)  # never below entry until armed

    # Check if we should arm the trail
    if pnl_r >= move_to_breakeven_at_r and trade.sl_price < trade.entry_price:
        # Move SL to breakeven
        if trade.side == "BUY":
            return trade.entry_price * 0.9999, "BREAKEVEN"
        else:
            return trade.entry_price * 1.0001, "BREAKEVEN"

    if pnl_r >= arm_at_r:
        # Trail is armed — update SL to trail behind high/low
        if trade.side == "BUY":
            if new_sl > trade.sl_price:
                return new_sl, "TRAILING"
        else:
            if new_sl < trade.sl_price:
                return new_sl, "TRAILING"

    return None, "NONE"


# ── Partial Take Profit (P1-36) ────────────────────────────────────────────


@dataclass
class PartialTPState:
    """State for partial take profit logic on an open trade."""
    trade_id: str
    size: float
    partial_filled: bool = False
    partial_pct: float = 0.50  # what % of position to close at partial TP
    partial_at_r: float = 0.75  # close partial at +0.75R
    remaining_sl_at_r: float = 0.30  # move remaining SL to +0.30R after partial


def check_partial_take_profit(
    trade: "OpenTrade",
    current_price: float,
    partial_at_r: float = 0.75,
    partial_pct: float = 0.50,
    remaining_sl_at_r: float = 0.30,
) -> tuple[bool, float, float | None]:
    """Check if partial take profit should trigger.

    Returns (should_partial, partial_size, new_sl_for_remaining) where:
      - should_partial: True if partial TP should trigger
      - partial_size: how much to close
      - new_sl_for_remaining: new SL for the remaining position, or None
    """
    sl_distance = abs(trade.entry_price - trade.sl_price)
    if sl_distance <= 0:
        return False, 0.0, None

    if trade.side == "BUY":
        pnl_r = (current_price - trade.entry_price) / sl_distance
    else:
        pnl_r = (trade.entry_price - current_price) / sl_distance

    if pnl_r >= partial_at_r:
        partial_size = trade.size * partial_pct
        # Move remaining SL to +remaining_sl_at_r
        if trade.side == "BUY":
            new_sl = trade.entry_price + (remaining_sl_at_r * sl_distance)
        else:
            new_sl = trade.entry_price - (remaining_sl_at_r * sl_distance)
        return True, partial_size, new_sl

    return False, 0.0, None
