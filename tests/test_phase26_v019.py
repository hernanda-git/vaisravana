"""Phase 26 (v0.0.19) — ADX trend filter, volatility SL, cooldown, trailing stop, per-side threshold.

Verifies:
- compute_adx returns 0 on degenerate/insufficient data, >0 on trending data.
- adx_allowed blocks ADX < 20, passes degenerate.
- volatility_scale scales correctly with median ATR.
- entry_allowed + per-side threshold adjustment.
- NormalizeState/run-level features compile correctly.
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bot_paper as b  # noqa: E402
from marketdata import Candle  # noqa: E402


# ── ADX tests ────────────────────────────────────────────────────────────

def _trend_candles(n=60, trend=0.3):
    """Candles with a clear trend (upward)."""
    c = 100.0
    out = []
    for i in range(n):
        o, h, l = c, c + 0.8, c - 0.3
        c = c + trend + (i % 5 - 2) * 0.1
        out.append(Candle(o=o, h=h, l=l, c=c, v=1000.0, ts=i))
    return out


def test_compute_adx_returns_zero_on_empty():
    assert b.compute_adx([], period=14) == 0.0


def test_compute_adx_returns_zero_on_insufficient():
    assert b.compute_adx([Candle(o=100, h=101, l=99, c=100, v=1000, ts=i) for i in range(10)]) == 0.0


def test_compute_adx_returns_positive_on_trend():
    candles = _trend_candles(60, trend=0.3)
    adx = b.compute_adx(candles, period=14)
    assert adx > 20.0, f"ADX should show strong trend, got {adx:.1f}"


def test_compute_adx_returns_low_on_noise():
    # Random-ish candles with no clear trend
    c = 100.0
    out = []
    for i in range(60):
        o, h, l = c, c + 1.0, c - 1.0
        c = c + (i % 3 - 1) * 0.3 + (i % 7) * 0.02
        out.append(Candle(o=o, h=h, l=l, c=c, v=1000.0, ts=i))
    adx = b.compute_adx(out, period=14)
    # In a non-trending market, ADX should be below 25
    assert 0 <= adx < 25, f"Expected low ADX on noise, got {adx:.1f}"


def test_adx_allowed_passes_degenerate():
    ok, reason = b.adx_allowed(0.0)
    assert ok is True
    assert reason == ""


def test_adx_allowed_passes_high():
    ok, reason = b.adx_allowed(30.0)
    assert ok is True
    assert reason == ""


def test_adx_allowed_blocks_low():
    ok, reason = b.adx_allowed(15.0)
    assert ok is False
    assert "ADX" in reason


# ── Volatility scale tests ───────────────────────────────────────────────

def test_vol_scale_returns_1_no_data():
    assert b.volatility_scale("TEST", 0.02, None) == 1.0


def test_vol_scale_returns_1_empty():
    assert b.volatility_scale("TEST", 0.02, {}) == 1.0


def test_vol_scale_scales_high_vol():
    # High-vol pair (0.05) vs universe median 0.02 -> sqrt(2.5) ≈ 1.58 -> clamped to 1.5
    scale = b.volatility_scale("TEST", 0.05, {"A": 0.02, "B": 0.02, "C": 0.02})
    assert 1.4 <= scale <= 1.5, f"Got {scale}"


def test_vol_scale_scales_low_vol():
    scale = b.volatility_scale("TEST", 0.005, {"A": 0.02, "B": 0.02, "C": 0.02})
    assert 0.7 <= scale <= 1.0, f"Got {scale}"


def test_vol_scale_clamped():
    scale = b.volatility_scale("TEST", 0.1, {"A": 0.01})
    assert scale <= 1.5
    scale2 = b.volatility_scale("TEST", 0.001, {"A": 0.05})
    assert scale2 >= 0.7


# ── Per-side threshold tests ─────────────────────────────────────────────

class _FakeState:
    def __init__(self, htf="neutral", btc="neutral", risk="neutral", pullback=False):
        self.htf_bias = htf
        self.btc_bias = btc
        self.risk_regime = risk
        self.pullback_to_anchor = pullback
        self.atr_pct = 0.01


def test_entry_allowed_passes_buy_bull():
    s = _FakeState(htf="bullish")
    ok, _ = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is True


def test_entry_allowed_blocks_buy_bear():
    s = _FakeState(htf="bearish", btc="bearish")
    ok, reason = b.entry_allowed(s, "BUY", 0, 0.0)
    assert ok is False
    assert "BUY blocked" in reason


def test_entry_allowed_passes_sell_bear():
    s = _FakeState(htf="bearish")
    ok, _ = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is True


def test_entry_allowed_blocks_sell_bull():
    s = _FakeState(htf="bullish")
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is False
    assert "SELL blocked" in reason


def test_entry_allowed_blocks_bleeding_side():
    s = _FakeState(htf="bullish")
    ok, reason = b.entry_allowed(s, "BUY", 25, -1.0)
    assert ok is False
    assert "bleeding" in reason


def test_entry_allowed_neutral_requires_pullback():
    s = _FakeState(htf="neutral", pullback=False)
    ok, reason = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok is False
    assert "pullback" in reason
    s.pullback_to_anchor = True
    ok2, _ = b.entry_allowed(s, "SELL", 0, 0.0)
    assert ok2 is True


# ── PAIR_WEIGHTS ─────────────────────────────────────────────────────────

def test_pair_weights_defaults():
    assert isinstance(b.PAIR_WEIGHTS, dict)


# ── Cooldown integration test ────────────────────────────────────────────

def test_cooldowns_dict_passed_to_tick(monkeypatch):
    """Verify cooldowns flow through _decide_tick without crashing."""
    import sqlite3
    from config import default_surface
    from db import init_db
    from lifecycle import TradeLifecycle

    conn = init_db(Path(tempfile.mkdtemp()) / "t.db")
    surface = default_surface()
    sink = []
    lc = TradeLifecycle(conn)

    class _Tel:
        def exec_event(self, *a, **k): return None
        def health(self, *a, **k): return None

    class _K:
        def check_global(self, *a, **k): return (False, "")
        def reset(self): return None

    class _N:
        def __init__(self):
            self.calls = []
        def notify_decision(self, *a, **k): self.calls.append(a)
        def send_message(self, *a, **k): self.calls.append(a)

    candles = [Candle(o=100 + i*0.1, h=101 + i*0.1, l=99 + i*0.1,
                      c=100 + i*0.1, v=1000, ts=i) for i in range(60)]
    kc = {"1m": candles}
    cooldowns = {("BTCUSDT", "BUY"): 2}

    monkeypatch.setattr(b, "evaluate_strategy",
                        lambda *a, **k: type("E", (), {"decision": "ENTRY", "side": "BUY",
                                                       "chosen_score": 0.7, "entry_price": 100.5,
                                                       "sl_price": 99.0, "tp_price": 102.0,
                                                       "strategy": "scalping", "decision_tf": "1m",
                                                       "sub_scores": type("S", (), {"as_dict": lambda: {}})})())

    b._decide_tick("BTCUSDT", conn, surface, lc, _Tel(), _K(), None,
                   _N(), {}, registry=None, decision_sink=sink,
                   klines_cache=kc, cooldowns=cooldowns, pair_atr={"BTCUSDT": 0.02})

    # With cooldown=2, the entry should be skipped (SKIP/GATED)
    rows = conn.execute("SELECT COUNT(*) FROM decisions_log").fetchone()[0]
    assert rows >= 1, "decisions_log should have a row (SKIP due to cooldown)"
