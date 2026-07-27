"""Phase 25 (v0.0.20) — hierarchical HTF entry gate (the retracement trap fix).

Tests the rewritten entry_allowed() with 5-layer hierarchy:
- BUY blocked unless htf bullish AND htf2 NOT bearish AND btc NOT bearish AND risk NOT bearish
- SELL blocked unless htf bearish AND htf2 NOT bullish AND btc NOT bullish AND risk NOT bullish
- Neutral HTF requires pullback_to_anchor
- Side-bleed check (unchanged from v0.0.18)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bot_paper as b  # noqa: E402


def _state(htf="neutral", htf2="neutral", btc="neutral", risk="neutral", pullback=False):
    class _S:
        pass
    s = _S()
    s.htf_bias = htf
    s.htf_bias2 = htf2
    s.btc_bias = btc
    s.risk_regime = risk
    s.pullback_to_anchor = pullback
    return s


# ── BUY tests ────────────────────────────────────────────────────────────

def test_buy_allowed_all_bullish():
    """BUY allowed when HTF is bullish, higher TF not bearish, BTC not bearish."""
    s = _state(htf="bullish", htf2="bullish", btc="bullish", risk="bullish")
    ok, _ = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is True


def test_buy_blocked_htf_bearish():
    """BUY blocked when pair's OWN trend is bearish (Layer 1)."""
    s = _state(htf="bearish")
    ok, reason = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is False
    assert "htf= bearish" in reason or "htf=bearish" in reason


def test_buy_blocked_htf2_bearish():
    """BUY blocked when higher TF is bearish — THE retracement trap fix."""
    s = _state(htf="bullish", htf2="bearish")  # 15m bull, 1h bear = retracement
    ok, reason = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is False
    assert "retracement trap" in reason or "htf2" in reason


def test_buy_blocked_btc_bearish():
    """BUY blocked when BTC is bearish (Layer 3 override down)."""
    s = _state(htf="bullish", btc="bearish")
    ok, reason = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is False
    assert "BTC" in reason


def test_buy_blocked_risk_off():
    """BUY blocked when risk regime is bearish (Layer 4)."""
    s = _state(htf="bullish", risk="bearish")
    ok, reason = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is False
    assert "risk-off" in reason


def test_buy_neutral_htf_requires_pullback():
    """BUY in neutral HTF requires pullback_to_anchor (Layer 5)."""
    s = _state(htf="neutral", pullback=False)
    ok, reason = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is False
    assert "pullback" in reason

    s2 = _state(htf="neutral", pullback=True)
    ok2, _ = b.entry_allowed(s2, "BUY", 0, 0.0)
    assert ok2 is True


def test_buy_allowed_htf_bullish_htf2_neutral():
    """BUY allowed when htf bullish, htf2 neutral (no disagreement)."""
    s = _state(htf="bullish", htf2="neutral")
    ok, _ = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is True


def test_buy_allowed_htf_bullish_btc_neutral():
    """BUY allowed when htf bullish, btc neutral (no disagreement)."""
    s = _state(htf="bullish", btc="neutral")
    ok, _ = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is True


# ── SELL tests ───────────────────────────────────────────────────────────

def test_sell_allowed_all_bearish():
    """SELL allowed when HTF bearish, higher TF not bullish, BTC not bullish."""
    s = _state(htf="bearish", htf2="bearish", btc="bearish", risk="bearish")
    ok, _ = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is True


def test_sell_blocked_htf_bullish():
    """SELL blocked when pair's OWN trend is bullish (Layer 1)."""
    s = _state(htf="bullish")
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is False
    assert "SELL blocked" in reason


def test_sell_blocked_htf2_bullish():
    """SELL blocked when higher TF is bullish (retracement trap for shorts)."""
    s = _state(htf="bearish", htf2="bullish")
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is False
    assert "retracement trap" in reason or "htf2" in reason


def test_sell_blocked_btc_bullish():
    """SELL blocked when BTC is bullish (Layer 3 override down)."""
    s = _state(htf="bearish", btc="bullish")
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is False
    assert "BTC" in reason


def test_sell_blocked_risk_on():
    """SELL blocked when risk regime is bullish (Layer 4)."""
    s = _state(htf="bearish", risk="bullish")
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is False
    assert "risk-on" in reason


def test_sell_neutral_htf_requires_pullback():
    """SELL in neutral HTF requires pullback_to_anchor."""
    s = _state(htf="neutral", pullback=False)
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is False
    assert "pullback" in reason

    s2 = _state(htf="neutral", pullback=True)
    ok2, _ = b.entry_allowed(s2, "SELL", 0, 0.0)
    assert ok2 is True


# ── Side-bleed tests (unchanged from v0.0.18) ────────────────────────────

def test_bleeding_side_blocked():
    """Side with >= MIN_SAMPLES and negative expR is blocked."""
    s = _state(htf="bullish", pullback=True)
    ok, reason = b.entry_allowed(s, "BUY", 25, -1.0)
    assert ok is False
    assert "bleeding" in reason


def test_unproven_side_not_blocked_by_bleed():
    """Side with < MIN_SAMPLES is NOT blocked by bleed rule."""
    s = _state(htf="bullish", pullback=True)
    ok, _ = b.entry_allowed(s, "BUY", 5, -1.0)
    assert ok is True
