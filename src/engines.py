"""Project Vaiśravaṇa — 9 engines: 8 factor sub-scores + aggregated dual scoring (doc 01–11, doc 10).

Each engine is a PURE function MarketState -> sub-score in [0,1]. No side effects, no I/O.
The dual-score path (doc 10) computes `long_score` and `short_score` separately — a SHORT
is NOT a mirrored long. Decision = pick the higher side if it clears `entry_threshold`.

NOTE: 7 weighted factors (doc 10 / doc 21): trend, momentum, volume, structure, liquidity,
atr, funding_oi. Candle/PA quality is folded into structure_score() per doc 05. Per-engine
ceilings are calibrated so a genuine A+ confluence reaches ~0.95-1.0, making the documented
entry_threshold 0.90 an achievable (not unreachable) high bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Side = Literal["BUY", "SELL"]


@dataclass
class MarketState:
    symbol: str
    tf: str
    regime: str = "range"            # trending_bull/trending_bear/range/breakout/high_vol
    htf_bias: str = "neutral"        # bullish/bearish/neutral (1h/4h)
    # price action
    candles: list = field(default_factory=list)   # list[(o,h,l,c)]
    last_close: float = 0.0
    body_ratio: float = 0.5          # candle body / range (0..1)
    is_exhaustion_spike: bool = False
    # structure
    hh: bool = False
    hl: bool = False
    lh: bool = False
    ll: bool = False
    bos: bool = False
    choch: bool = False
    # liquidity
    liq_sweep: bool = False
    eq_high: bool = False
    eq_low: bool = False
    fvg: bool = False
    # volume
    vol_z: float = 0.0               # volume z-score (current vs avg)
    delta_z: float = 0.0
    # volatility
    atr: float = 0.0
    atr_pct: float = 0.01
    # multi-tf
    mtf_aligned: bool = False
    # market data health
    spread_bps: float = 3.0
    funding_ok: bool = True
    adl_rank: int = 1                # 1..5
    oi_z: float = 0.0


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


# --- 7 factor engines: each returns 0..1 ---

def regime_score(s: MarketState) -> float:
    """Trend 30% weight source (doc 10). Bullish regime + HTF bullish -> high long bias."""
    base = {
        "trending_bull": 0.8,
        "trending_bear": 0.2,
        "range": 0.5,
        "breakout": 0.6,
        "high_vol": 0.45,
    }.get(s.regime, 0.5)
    if s.htf_bias == "bullish":
        base = _clamp(base + 0.15)
    elif s.htf_bias == "bearish":
        base = _clamp(base - 0.15)
    return _clamp(base)


def momentum_score(s: MarketState) -> float:
    """Momentum 20%. Reject exhaustion spikes (doc 09 Layer 3)."""
    if s.is_exhaustion_spike:
        return 0.15
    m = 0.4 + 0.4 * _clamp(s.vol_z / 3.0) + 0.2 * _clamp(s.delta_z / 3.0)
    return _clamp(m)


def volume_score(s: MarketState) -> float:
    """Volume 15%. Anomaly/confirmation of movement; strong volume -> ~1.0."""
    return _clamp(0.5 + 0.5 * _clamp(s.vol_z / 3.0))


def structure_score(s: MarketState) -> float:
    """Market structure 15% (doc 02/05). BOS/CHoCH + HH/HL or LH/LL + candle/PA quality."""
    sc = 0.35
    if s.bos:
        sc += 0.2
    if s.choch:
        sc += 0.15
    if s.hh and s.hl:
        sc += 0.15
    if s.lh and s.ll:
        sc += 0.15
    # candle/PA quality folded in here (doc 04/09): quality body, not a wick
    sc += 0.15 * s.body_ratio
    return _clamp(sc)


def liquidity_score(s: MarketState) -> float:
    """Liquidity 10% (doc 06). For LONG: enter AFTER a sweep at support (eq_low)."""
    sc = 0.5
    if s.liq_sweep:
        sc += 0.2            # sweep cleared -> entry zone
    if s.eq_low:
        sc += 0.1            # sweep at support = long entry zone
    if s.fvg:
        sc += 0.1
    return _clamp(sc)


def liquidity_score_bear(s: MarketState) -> float:
    """Liquidity 10% for SHORT: enter AFTER a sweep at resistance (eq_high)."""
    sc = 0.5
    if s.liq_sweep:
        sc += 0.2
    if s.eq_high:
        sc += 0.1            # sweep at resistance = short entry zone
    if s.fvg:
        sc += 0.1
    return _clamp(sc)


def atr_score(s: MarketState) -> float:
    """Volatility 5% (doc 07). Sweet-spot ATR (~0.5%-2%) scores highest (1.0);
    too-low or too-high volatility is mildly penalized but still valid."""
    if s.atr_pct <= 0:
        return 0.6
    if s.atr_pct < 0.003:
        return 0.7
    if s.atr_pct > 0.03:
        return 0.75
    return 1.0


def funding_oi_score(s: MarketState) -> float:
    """Funding/OI 5% (doc 03/28-D). Healthy funding/ADL -> 1.0; extreme -> caution."""
    sc = 1.0
    if not s.funding_ok:
        sc -= 0.4
    if s.adl_rank >= 4:
        sc -= 0.3
    return _clamp(sc)


def candle_score(s: MarketState) -> float:
    """Candle / PA quality 0..1 (doc 04/09). Quality body, not a wick.
    NOTE: folded into structure_score() per doc 05; kept as a standalone helper for
    attribution/testing only (not a separate weight — doc 10 defines 7 weights)."""
    return _clamp(0.4 + 0.4 * s.body_ratio)


# factor registry (doc 10 weights — 7 factors, sum = 1.0)
_FACTORS = {
    "trend": regime_score,
    "momentum": momentum_score,
    "volume": volume_score,
    "structure": structure_score,
    "liquidity": liquidity_score,
    "atr": atr_score,
    "funding_oi": funding_oi_score,
}
