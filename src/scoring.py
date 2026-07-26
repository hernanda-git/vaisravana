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
    crossasset_score,
    funding_oi_score,
    liquidity_score,
    liquidity_score_bear,
    momentum_score,
    mtf_relational_score,
    regime_score,
    structure_score,
    volume_score,
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


def decide(s: MarketState, surface: ParameterSurface | None = None) -> Decision:
    surface = surface or default_surface()
    long = score_side(s, "BUY", surface)
    short = score_side(s, "SELL", surface)
    if long >= short:
        side, chosen = "BUY", long
    else:
        side, chosen = "SELL", short

    if chosen >= surface.entry_threshold:
        decision = "ENTRY"
    elif chosen >= surface.watch_threshold:
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


def decide_ctx(s: MarketState, surface: ParameterSurface | None = None) -> Decision:
    """Context-aware decision (v0.0.7): the 7-factor `decide` PLUS cross-asset + MTF
    relational confirmation.

    The relational factors are applied as a MODULATOR on the base score (preserving the
    doc-21 Σweights=1.0 invariant) and as a HARD gate when the trade fights the market's
    rudder (BTC downtrend + risk-off long, etc.). The base 7-factor logic is unchanged,
    so all existing tests on `decide()` keep passing.
    """
    surface = surface or default_surface()
    base = decide(s, surface)
    if base.decision != "ENTRY" or base.side is None:
        return base  # nothing to confirm/block

    from marketcontext import MarketContext
    ctx = MarketContext(
        btc_bias=s.btc_bias, btc_ret=s.btc_ret,
        dominance_delta=s.dominance_delta, risk_regime=s.risk_regime,
        alt_rs_btc=s.alt_rs_btc, alt_breadth=s.alt_breadth,
        ltf_bias=s.ltf_bias, mtf_bias=s.mtf_bias, htf_bias=s.htf_bias2,
        mtf_confluence=s.mtf_confluence, pullback_to_anchor=s.pullback_to_anchor,
    )
    boost = ctx.ctx_boost()
    allowed, reason = ctx.ctx_gate_open(base.side)
    if not allowed:
        # context hard-blocks the entry -> downgrade to WATCH with a note
        return Decision(
            long_score=base.long_score, short_score=base.short_score,
            side=None, decision="WATCH",
            chosen_score=round(base.chosen_score * 0.9, 4),
            confidence_pct=round(base.chosen_score * 90.0, 2),
            sub_scores=base.sub_scores,
        )
    # apply relational boost (clamped) — a confirmed A+ setup can slightly exceed 0.90
    new_score = max(0.0, min(1.0, base.chosen_score * boost))
    return Decision(
        long_score=base.long_score, short_score=base.short_score,
        side=base.side,
        decision="ENTRY" if new_score >= surface.entry_threshold else "WATCH",
        chosen_score=round(new_score, 4),
        confidence_pct=round(new_score * 100.0, 2),
        sub_scores=base.sub_scores,
    )

