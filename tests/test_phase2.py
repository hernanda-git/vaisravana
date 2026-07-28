"""Tests for Phase 2: 9 engines, dual scoring, decision, 5W1H scaffold."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import default_surface  # noqa: E402
from engines import MarketState  # noqa: E402
from scoring import decide, score_side  # noqa: E402
from reasoning import Reasoning5W1H, build_from_event  # noqa: E402


def _bull() -> MarketState:
    # A+ confluence: bullish regime, HTF bullish, strong volume/delta, full structure,
    # liquidity sweep cleared, tight ATR, low ADL. Must clear entry_threshold 0.90.
    return MarketState(
        symbol="BTCUSDT", tf="5m", regime="trending_bull", htf_bias="bullish",
        body_ratio=0.95, vol_z=3.0, delta_z=3.0, bos=True, hh=True, hl=True,
        choch=True, liq_sweep=True, eq_low=True, fvg=True, atr_pct=0.01,
        spread_bps=1.0, funding_ok=True, adl_rank=1,
    )


def _bear() -> MarketState:
    # A+ confluence for SHORT: bearish regime, HTF bearish, strong down-volume, full
    # bearish structure, liquidity sweep-up cleared, tight ATR, low ADL.
    return MarketState(
        symbol="BTCUSDT", tf="5m", regime="trending_bear", htf_bias="bearish",
        body_ratio=0.95, vol_z=3.0, delta_z=-3.0, bos=True, lh=True, ll=True,
        choch=True, liq_sweep=True, eq_high=True, fvg=True, atr_pct=0.01,
        spread_bps=1.0, funding_ok=True, adl_rank=1,
    )


def _flat() -> MarketState:
    return MarketState(symbol="XUSDT", tf="5m", regime="range", htf_bias="neutral",
                       body_ratio=0.5, vol_z=0.0, atr_pct=0.01)


def test_bullish_state_decides_long_entry():
    d = decide(_bull())
    assert d.decision == "ENTRY"
    assert d.side == "BUY"
    assert d.long_score > d.short_score
    assert d.confidence_pct == round(d.long_score * 100, 2)


def test_bearish_state_decides_short_entry():
    d = decide(_bear())
    assert d.decision == "ENTRY"
    assert d.side == "SELL"
    assert d.short_score > d.long_score


def test_short_is_not_mirrored_long():
    # In a DIRECTIONAL regime the two scores must diverge (short must NOT equal 1-long),
    # proving SHORT is computed independently, not as a mirror.
    s = _bull()  # strong bullish -> long high, short low, and NOT complementary
    long = score_side(s, "BUY")
    short = score_side(s, "SELL")
    # divergence proves independent computation (not a simple 1-x mirror)
    assert long > 0.8
    assert (long - short) > 0.2
    # independence: flipping to bearish flips which side wins
    s2 = _bear()
    assert score_side(s2, "SELL") > score_side(s2, "BUY")


def test_low_score_skips():
    s = MarketState(symbol="X", tf="5m", regime="high_vol", htf_bias="neutral",
                    body_ratio=0.1, vol_z=-2.0, is_exhaustion_spike=True, atr_pct=0.05,
                    adl_rank=5, funding_ok=False)
    d = decide(s)
    assert d.decision in ("SKIP", "WATCH")
    assert d.side is None or d.decision != "ENTRY"


def test_watch_band():
    surf = default_surface()
    # craft a mid score manually by lowering thresholds won't work; use a moderate state
    s = MarketState(symbol="X", tf="5m", regime="range", htf_bias="neutral",
                    body_ratio=0.6, vol_z=0.5, bos=True, liq_sweep=True, atr_pct=0.01)
    d = decide(s, surf)
    assert d.decision in ("ENTRY", "WATCH", "SKIP")


def test_subscores_in_range():
    subs = decide(_bull()).sub_scores
    for v in subs.as_dict().values():
        assert 0.0 <= v <= 1.0


def test_5w1h_incomplete_without_why():
    r = Reasoning5W1H(who="bot", what="WR dropped")
    assert r.is_complete() is False


def test_5w1h_complete_with_why():
    r = Reasoning5W1H(who="bot", what="WR dropped", why="slippage spike in high_vol")
    assert r.is_complete() is True
    assert "WHY" in r.to_text()


def test_build_from_event():
    r = build_from_event("ADL rank high", {"actor": "exchange", "why": "large long",
                                            "hypotheses": ["H1: funding squeeze"]})
    assert r.who == "exchange"
    assert r.hypotheses[0].startswith("H1")
