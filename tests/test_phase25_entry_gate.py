"""Phase 25 (v0.1.8) — directional + expectancy entry gate (the WR fix).

Verifies the pure, testable `entry_allowed(state, side, sc, sexp)` gate:
- BUY blocked when regime is not bullish (the live BUY 23.7% WR / -8.78R bleed).
- SELL allowed in a bearish regime; SELL blocked only in a bullish regime.
- A bleeding side (>= MIN_SAMPLES, negative expR) is blocked.
- In a neutral regime, a pullback_to_anchor is required (no chasing extremes).
- An aligned trend side (BUY+bull / SELL+bear) is allowed without a pullback.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bot_paper as b  # noqa: E402


def _state(htf="neutral", btc="neutral", risk="neutral", pullback=False):
    class _S:
        pass
    s = _S()
    s.htf_bias = htf
    s.btc_bias = btc
    s.risk_regime = risk
    s.pullback_to_anchor = pullback
    return s


def test_buy_blocked_in_bear_regime():
    s = _state(htf="bearish", btc="bearish")
    ok, reason = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is False
    assert "BUY blocked" in reason


def test_buy_allowed_in_bull_regime_without_pullback():
    # bull regime is aligned with BUY, so pullback not required
    s = _state(htf="bullish", pullback=False)
    ok, reason = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is True


def test_sell_allowed_in_bear_regime():
    s = _state(htf="bearish", btc="bearish")
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is True


def test_sell_blocked_in_bull_regime():
    s = _state(htf="bullish")
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is False
    assert "SELL blocked" in reason


def test_neutral_regime_requires_pullback():
    s = _state(htf="neutral", pullback=False)
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is False
    assert "pullback" in reason
    s2 = _state(htf="neutral", pullback=True)
    ok2, _ = b.entry_allowed(s2, "SELL", 0, 0.0)
    assert ok2 is True


def test_bleeding_side_blocked():
    s = _state(htf="bullish", pullback=True)
    ok, reason = b.entry_allowed(s, "BUY", 25, -1.0)
    assert ok is False
    assert "bleeding" in reason


def test_unproven_side_not_blocked_by_bleed_rule():
    s = _state(htf="bullish", pullback=True)
    ok, _ = b.entry_allowed(s, "BUY", 5, -1.0)
    assert ok is True
