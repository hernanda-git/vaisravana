"""Project Vaiśravaṇa — concurrent multi-strategy layer (v0.1.0).

Runs Scalping / Day / Swing profiles side-by-side on the same pair. Each profile carries its
own decision timeframe, entry bar, and SL/TP ATR multipliers, so the bot is active across
timescales instead of waiting for one rare A+ setup.

Pure logic: the caller injects the per-TF MarketState (built by the engine stack from klines).
No network, no DB — fully unit-testable offline, consistent with the paper-first design.

Key derived object: `StrategyEntry` = a concrete, sized-agnostic entry proposal (side, entry,
SL, TP, and the profile that produced it). The orchestrator/bot turns it into a paper order.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from config import ParameterSurface, StrategyProfile, default_profiles, default_surface
from engines import MarketState
from scoring import Decision, decide_ctx
from alpha_signals import regime_tp_multiplier


@dataclass
class StrategyEntry:
    strategy: str            # scalping / day / swing
    decision_tf: str
    side: str                # BUY / SELL
    decision: str            # ENTRY / WATCH / SKIP
    chosen_score: float
    confidence_pct: float
    entry_price: float
    sl_price: float
    tp_price: float
    rr: float
    sub_scores: object = None  # scoring.SubScores (persisted into trade_logs)


def active_strategies(
    surface: ParameterSurface | None = None,
    profiles: dict[str, StrategyProfile] | None = None,
) -> list[StrategyProfile]:
    """Return the enabled strategy profiles.

    Disable any subset at deploy time with VAISRAVANA_DISABLED_STRATEGIES="swing,day"
    (comma-separated names). By default all three run — that is the "very active" posture.
    """
    profiles = profiles or default_profiles()
    disabled = {
        x.strip().lower()
        for x in os.environ.get("VAISRAVANA_DISABLED_STRATEGIES", "").split(",")
        if x.strip()
    }
    return [p for name, p in profiles.items() if name not in disabled]


def _sl_tp(side: str, entry_price: float, atr: float, profile: StrategyProfile,
           atr_pct: float = 0.01, regime: str = "range") -> tuple[float, float]:
    """Derive SL/TP from the profile's ATR multipliers (LONG below/above, SHORT mirrored).

    ATR regime modifier (additive, env-tunable): in high-vol regimes (atr_pct > 0.02)
    TP widens to capture larger moves; in tight range (atr_pct < 0.005) TP tightens
    to avoid getting picked off by noise. All additive — no engine changes.
    """
    sl_dist = profile.sl_atr_mult * atr
    regime_mult = 1.0 + max(0.0, (atr_pct - 0.01)) * 10.0  # wider TP when vol > 1%
    base_tp = profile.tp_atr_mult * regime_mult
    # Feature flag preserves current defaults; enable only in a paper A/B run.
    if os.environ.get("VAISRAVANA_REGIME_ADAPTIVE_TP", "0") == "1":
        base_tp = regime_tp_multiplier(regime, atr_pct, base=base_tp)
    tp_dist = base_tp * atr
    if side == "BUY":
        return entry_price - sl_dist, entry_price + tp_dist
    return entry_price + sl_dist, entry_price - tp_dist


def evaluate_strategy(
    profile: StrategyProfile,
    state: MarketState,
    entry_price: float,
    atr: float,
    surface: ParameterSurface | None = None,
) -> StrategyEntry:
    """Score `state` under one profile and produce a concrete entry proposal.

    Uses the profile's own entry/watch thresholds (activity bar) and SL/TP mults (R:R).
    The 7-factor + context engine logic is shared with production `decide_ctx`.
    """
    surface = surface or default_surface()
    dec: Decision = decide_ctx(
        state, surface,
        entry_threshold=profile.entry_threshold,
        watch_threshold=profile.watch_threshold,
    )
    side = dec.side or ("BUY" if dec.long_score >= dec.short_score else "SELL")
    sl_price, tp_price = _sl_tp(side, entry_price, atr, profile,
                                atr_pct=state.atr_pct, regime=state.regime)
    return StrategyEntry(
        strategy=profile.name,
        decision_tf=profile.decision_tf,
        side=side if dec.decision == "ENTRY" else (dec.side or side),
        decision=dec.decision,
        chosen_score=dec.chosen_score,
        confidence_pct=dec.confidence_pct,
        entry_price=entry_price,
        sl_price=round(sl_price, 10),
        tp_price=round(tp_price, 10),
        rr=round(profile.rr, 4),
        sub_scores=dec.sub_scores,
    )


def evaluate_all(
    states: dict[str, MarketState],
    entry_price: float,
    atr_by_strategy: dict[str, float],
    surface: ParameterSurface | None = None,
    profiles: dict[str, StrategyProfile] | None = None,
) -> list[StrategyEntry]:
    """Evaluate every active strategy for one pair.

    `states` maps strategy name -> MarketState (built on that strategy's decision_tf).
    `atr_by_strategy` maps strategy name -> ATR on that TF. Missing entries are skipped.
    Returns only ENTRY proposals, sorted by confidence descending (most conviction first).
    """
    surface = surface or default_surface()
    out: list[StrategyEntry] = []
    for profile in active_strategies(surface, profiles):
        st = states.get(profile.name)
        atr = atr_by_strategy.get(profile.name, 0.0)
        if st is None or atr <= 0:
            continue
        se = evaluate_strategy(profile, st, entry_price, atr, surface)
        if se.decision == "ENTRY":
            out.append(se)
    out.sort(key=lambda e: e.confidence_pct, reverse=True)
    return out
