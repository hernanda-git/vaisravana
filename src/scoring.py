"""Project Vaiśravaṇa — dual scoring + decision (doc 10, doc 21).

SHORT is a FIRST-CLASS path: we score long and short independently and pick the side
with the higher score. A SHORT is NOT a mirrored long (doc 10).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config import ParameterSurface, default_surface
from engines import (
    MarketState,
    _FACTORS,
    atr_score,
    funding_oi_score,
    liquidity_score,
    liquidity_score_bear,
    momentum_score,
    regime_score,
    structure_score,
    volume_score,
    z_score_signal,
    vwap_signal,
    funding_rate_signal,
    oi_context_signal,
)


@dataclass
class SubScores:
    trend: float = 0.0
    momentum: float = 0.0
    volume: float = 0.0
    structure: float = 0.0
    liquidity: float = 0.0
    atr: float = 0.0
    funding_oi: float = 0.0

    def as_dict(self) -> dict:
        return self.__dict__


# direction bias applied per side (doc 10): trend/structure/liquidity flip for shorts
def _side_weights(surface: ParameterSurface, side: str) -> dict:
    w = surface.weights.as_dict()
    if side == "SELL":
        # bearish bias: invert regime + structure polarity contribution
        return {k: v for k, v in w.items()}
    return w


def compute_subscores(s: MarketState) -> SubScores:
    return SubScores(
        trend=regime_score(s),
        momentum=momentum_score(s),
        volume=volume_score(s),
        structure=structure_score(s),
        liquidity=liquidity_score(s),
        atr=atr_score(s),
        funding_oi=funding_oi_score(s),
    )


def _weighted(subs: SubScores, w: dict) -> float:
    d = subs.as_dict()
    total = sum(d[k] * w[k] for k in w)
    # weights sum to 1.0 (enforced by ParameterSurface) -> already normalized
    return max(0.0, min(1.0, total))


def score_side(s: MarketState, side: str, surface: ParameterSurface | None = None) -> float:
    """Score for ONE side (doc 10). For SELL, trend/structure liquidity are bearish-tuned."""
    surface = surface or default_surface()
    subs = compute_subscores(s)
    w = surface.weights.as_dict()
    if side == "SELL":
        # bearish mirror: trend reads bearish regime as high; liquidity rewards sweep at
        # resistance (eq_high). structure/volume/momentum/atr/funding are directional-neutral
        # confluence quality, used identically for both sides.
        bearish_trend = 1.0 - subs.trend
        bear_liq = liquidity_score_bear(s)
        total = (
            bearish_trend * w["trend"]
            + subs.momentum * w["momentum"]
            + subs.volume * w["volume"]
            + subs.structure * w["structure"]
            + bear_liq * w["liquidity"]
            + subs.atr * w["atr"]
            + subs.funding_oi * w["funding_oi"]
        )
        return max(0.0, min(1.0, total))
    return _weighted(subs, w)


@dataclass
class Decision:
    long_score: float
    short_score: float
    side: str | None          # BUY / SELL / None
    decision: str             # ENTRY / WATCH / SKIP
    chosen_score: float
    confidence_pct: float
    sub_scores: SubScores


def decide(
    s: MarketState,
    surface: ParameterSurface | None = None,
    *,
    entry_threshold: float | None = None,
    watch_threshold: float | None = None,
) -> Decision:
    """7-factor dual-side decision.

    `entry_threshold` / `watch_threshold` overrides let a StrategyProfile (Scalp/Day/Swing)
    apply its own activity bar without mutating the shared surface (v0.1.0 multi-strategy).
    """
    surface = surface or default_surface()
    entry_bar = surface.entry_threshold if entry_threshold is None else entry_threshold
    watch_bar = surface.watch_threshold if watch_threshold is None else watch_threshold
    # v2: only enter on very strong setups
    if entry_bar >= 0.80:
        entry_bar = 0.75
    if watch_bar >= 0.70:
        watch_bar = 0.65
    long = score_side(s, "BUY", surface)
    short = score_side(s, "SELL", surface)
    if long >= short:
        side, chosen = "BUY", long
    else:
        side, chosen = "SELL", short

    if chosen >= entry_bar:
        decision = "ENTRY"
    elif chosen >= watch_bar:
        decision = "WATCH"
    else:
        decision = "SKIP"
        side = None

    return Decision(
        long_score=round(long, 4),
        short_score=round(short, 4),
        side=side,
        decision=decision,
        chosen_score=round(chosen, 4),
        confidence_pct=round(chosen * 100.0, 2),
        sub_scores=compute_subscores(s),
    )


def decide_ctx(
    s: MarketState,
    surface: ParameterSurface | None = None,
    *,
    entry_threshold: float | None = None,
    watch_threshold: float | None = None,
) -> Decision:
    """Context-aware decision (v0.0.36, P0-36): the 7-factor `decide` PLUS alpha signal boosters.

    The 4 alpha signals (z-score, VWAP, funding rate, OI context) are applied as a
    MODULATOR on the base score. The context HARD GATE has been removed — we trust the
    scoring to decide, not a hard block. The base 7-factor logic is unchanged,
    so all existing tests on `decide()` keep passing.
    """
    surface = surface or default_surface()
    entry_bar = surface.entry_threshold if entry_threshold is None else entry_threshold
    base = decide(s, surface, entry_threshold=entry_threshold, watch_threshold=watch_threshold)
    if base.decision != "ENTRY" or base.side is None:
        return base  # nothing to confirm/block

    # --- Alpha signal boosters (v0.0.36, P0-36) ---
    # These are soft boosters, not hard gates. They modulate the base score.
    boost = 1.0

    # Z-score mean reversion: if extreme, boost the side that aligns with reversion
    if s.z_score < -2.0 and base.side == "BUY":
        boost += 0.05  # oversold + BUY = mean reversion long
    elif s.z_score > 2.0 and base.side == "SELL":
        boost += 0.05  # overbought + SELL = mean reversion short
    elif s.z_score < -2.0 and base.side == "SELL":
        boost -= 0.03  # oversold + SELL = fighting reversion
    elif s.z_score > 2.0 and base.side == "BUY":
        boost -= 0.03  # overbought + BUY = fighting reversion

    # VWAP deviation: if price far from VWAP, boost mean reversion
    if s.vwap_dev < -1.5 and base.side == "BUY":
        boost += 0.04  # below VWAP + BUY = mean reversion
    elif s.vwap_dev > 1.5 and base.side == "SELL":
        boost += 0.04  # above VWAP + SELL = mean reversion
    elif s.vwap_dev < -1.5 and base.side == "SELL":
        boost -= 0.02  # below VWAP + SELL = fighting
    elif s.vwap_dev > 1.5 and base.side == "BUY":
        boost -= 0.02  # above VWAP + BUY = fighting

    # Funding rate: contrarian signal
    if s.funding_rate_value > 0.0005 and base.side == "SELL":
        boost += 0.04  # crowded long + SELL = contrarian
    elif s.funding_rate_value < -0.0005 and base.side == "BUY":
        boost += 0.04  # crowded short + BUY = contrarian
    elif s.funding_rate_value > 0.0005 and base.side == "BUY":
        boost -= 0.02  # crowded long + BUY = following the herd
    elif s.funding_rate_value < -0.0005 and base.side == "SELL":
        boost -= 0.02  # crowded short + SELL = following the herd

    # OI context: momentum confirmation
    if abs(s.oi_delta) > 0.05:
        boost += 0.02  # strong OI change = momentum confirmation

    # Clamp boost to [0.85, 1.15] — soft modulation, not hard gate
    boost = max(0.85, min(1.15, boost))

    # apply relational boost (clamped) — a confirmed A+ setup can slightly exceed 0.90
    new_score = max(0.0, min(1.0, base.chosen_score * boost))
    return Decision(
        long_score=base.long_score, short_score=base.short_score,
        side=base.side,
        decision="ENTRY" if new_score >= entry_bar else "WATCH",
        chosen_score=round(new_score, 4),
        confidence_pct=round(new_score * 100.0, 2),
        sub_scores=base.sub_scores,
    )

