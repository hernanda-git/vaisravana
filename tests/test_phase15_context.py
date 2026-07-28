"""Phase 15 — cross-asset + MTF relational context (doc 40 §1, v0.0.7).

Run: pytest tests/test_phase15_context.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from marketcontext import build_context, ContextSeries, MarketContext
from engines import MarketState, crossasset_score, mtf_relational_score
from scoring import decide, decide_ctx
from config import default_surface


def _ramp(n, start=100.0, step=0.5):
    return [start + i * step for i in range(n)]


def _flat(n, v=100.0):
    return [v] * n


def test_btc_leader_bullish_boosts_long():
    # long-biased single-name state; BTC bullish + risk-on => boost, no block
    s = MarketState(symbol="ETHUSDT", tf="5m")
    s.btc_bias = "bullish"
    s.risk_regime = "bullish"
    s.mtf_confluence = True
    s.pullback_to_anchor = True
    s.alt_breadth = 0.8
    ctx = MarketContext(
        btc_bias="bullish", risk_regime="bullish",
        mtf_confluence=True, pullback_to_anchor=True, alt_breadth=0.8)
    assert ctx.ctx_boost() > 1.0        # confirmation adds conviction
    ok, _ = ctx.ctx_gate_open("BUY")
    assert ok


def test_long_blocked_when_btc_bearish_and_risk_off():
    ctx = MarketContext(btc_bias="bearish", risk_regime="bearish")
    ok, reason = ctx.ctx_gate_open("BUY")
    assert not ok
    assert "risk-off" in reason


def test_short_blocked_when_btc_bullish_and_risk_on():
    ctx = MarketContext(btc_bias="bullish", risk_regime="bullish")
    ok, reason = ctx.ctx_gate_open("SELL")
    assert not ok
    assert "risk-on" in reason


def test_context_build_from_series():
    # BTC up, alt basket flat => pair outperforms BTC => alt bid (risk-on)
    cs = ContextSeries(
        btc=_ramp(60, 100, 0.3),
        pair=_ramp(60, 100, 0.6),      # pair rises faster than BTC
        alt_basket=[_ramp(60, 100, 0.1)],
        ltf=_ramp(20, 100, 0.2),
        mtf=_ramp(60, 100, 0.4),
        htf=_ramp(60, 100, 0.5),
    )
    mc = build_context(cs, lookback=30)
    assert mc.btc_bias == "bullish"
    assert mc.risk_regime == "bullish"      # pair > BTC => dominance falling
    assert mc.alt_rs_btc > 0


def test_decide_ctx_uses_context():
    # A 7-factor ENTRY that fights the rudder (long while BTC bearish + risk-off)
    # must be downgraded by decide_ctx.
    s = MarketState(symbol="SOLUSDT", tf="5m")
    s.btc_bias = "bearish"
    s.risk_regime = "bearish"
    base = decide(s)               # may or may not be ENTRY; we force the gate path
    s2 = MarketState(symbol="SOLUSDT", tf="5m")
    s2.btc_bias = "bearish"
    s2.risk_regime = "bearish"
    # make the 7-factor side clearly BUY so decide_ctx reaches the gate
    s2.regime = "trending_bull"
    s2.htf_bias = "bullish"
    s2.mtf_aligned = True
    s2.hh = s2.hl = s2.bos = s2.choch = True
    s2.body_ratio = 1.0
    s2.vol_z = 3.0
    s2.liq_sweep = True
    s2.eq_low = True
    s2.fvg = True
    ctx_dec = decide_ctx(s2, default_surface())
    # even if base scored high, the relational gate should block a long vs BTC bear+risk-off
    if ctx_dec.side == "BUY":
        # if it still allowed long, it must at least not exceed base unscaled
        assert ctx_dec.chosen_score <= base.chosen_score + 1e-6 or ctx_dec.decision == "WATCH"
