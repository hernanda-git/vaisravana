"""Project Vaiśravaṇa — cross-asset & multi-timeframe relational context (v0.0.7).

The single-name 7-factor engine (doc 10) scores structure/liquidity/etc. on ONE symbol.
For a scalper this is incomplete: crypto is a *system*. Three relational facts dominate
intraday edges (doc 40 §1, user brief):

  1. BTC is the leader. A long on an alt while BTC is dumping has terrible expectancy.
  2. BTC Dominance (BTC.d) regime = risk-on/off. Falling dominance = alt bid; rising =
     BTC bid / alt bleed. We model it as a proxy when no direct dominance feed exists:
     `alt_basket_return - btc_return` (positive = capital rotating into alts).
  3. LTF / MF / HTF are RELATED. A scalping entry wants: HTF sets the bias, MF confirms,
     LTF pulls back INTO that bias (a liquidity pocket), then resumes. That "pullback to
     anchor" is the entry trigger — not just "aligned".

This module computes those relational factors as PURE functions of candle series. It is
engine-agnostic: `build_context()` returns a `MarketContext` that `engines`/`scoring` turn
into a confirmation boost + a hard gate.

All functions are pure (no I/O). The bot fetches the candle series; this module only math.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Bias = Literal["bullish", "bearish", "neutral"]


def _ema(closes: list[float], period: int) -> float:
    if not closes:
        return 0.0
    n = min(period, len(closes))
    k = 2.0 / (n + 1)
    ema = closes[0]
    for p in closes[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def _bias_of(closes: list[float], period: int = 50, tol: float = 0.0008) -> Bias:
    """EMA20 vs EMA50 directional bias with a dead-band (neutral)."""
    if len(closes) < period:
        return "neutral"
    e20 = _ema(closes[-20:], 20)
    e50 = _ema(closes, period)
    if e20 > e50 * (1 + tol):
        return "bullish"
    if e20 < e50 * (1 - tol):
        return "bearish"
    return "neutral"


def _ret(closes: list[float], lookback: int = 20) -> float:
    if len(closes) < 2:
        return 0.0
    a, b = closes[max(0, len(closes) - lookback)], closes[-1]
    return (b - a) / (abs(a) + 1e-12)


@dataclass
class MarketContext:
    """Relational cross-asset + MTF snapshot for one decision (per pair)."""

    # --- BTC leader ---
    btc_bias: Bias = "neutral"            # HTF trend of BTC (the market's rudder)
    btc_ret: float = 0.0                  # BTC return over the context window
    # --- dominance / risk regime (proxy) ---
    dominance_delta: float = 0.0          # <0 = alt bid (risk-on), >0 = BTC bid (risk-off)
    risk_regime: Bias = "neutral"         # derived from dominance_delta
    # --- alt relative strength ---
    alt_rs_btc: float = 0.0               # this pair's return minus BTC return
    alt_breadth: float = 0.5              # fraction of alt basket above its EMA (0..1)
    # --- MTF relational ---
    ltf_bias: Bias = "neutral"            # low TF (1-5m)
    mtf_bias: Bias = "neutral"            # mid TF (15m-1h)
    htf_bias: Bias = "neutral"            # high TF (4h-1d)
    mtf_confluence: bool = False          # all three TFs agree (same non-neutral bias)
    pullback_to_anchor: bool = False      # LTF retraced into MF/HTF bias then resumed

    def ctx_boost(self) -> float:
        """Confirmation boost in [0.9, 1.12].

        Scalping wants CONTEXT CONFIRMATION, not just more raw score. We reward a trade
        that is aligned with BTC + dominance + MTF confluence, and slightly penalize one
        that fights the market's rudder. This is a *modulator* on the existing 7-factor
        score, so the doc-21 Σweights=1.0 invariant is preserved (doc 40 §1).
        """
        boost = 1.0
        # BTC leader:同向 = +; 逆势 = -
        if self.btc_bias == "bullish":
            boost += 0.04
        elif self.btc_bias == "bearish":
            boost -= 0.05
        # risk regime: alt bid (risk-on) helps longs; BTC bid (risk-off) helps shorts
        if self.risk_regime == "bullish":      # alt bid
            boost += 0.03
        elif self.risk_regime == "bearish":    # BTC bid / risk-off
            boost -= 0.04
        # MTF confluence: the cleanest scalping condition
        if self.mtf_confluence:
            boost += 0.05
        # pullback-to-anchor: the actual entry trigger
        if self.pullback_to_anchor:
            boost += 0.03
        # breadth: broad participation
        boost += 0.02 * (self.alt_breadth - 0.5) * 2.0
        return max(0.9, min(1.12, boost))

    def ctx_gate_open(self, side: str) -> tuple[bool, str]:
        """Hard relational gate. Returns (allowed, reason).

        A scalper does NOT take a long while BTC is in a clear downtrend and dominance is
        rising (risk-off) — that is statistically adverse regardless of the local pattern.
        We only HARD-block the worst conflicts; softer conflicts are left to ctx_boost.
        """
        # long while BTC bearish AND risk-off (dominance rising) -> block
        if side == "BUY" and self.btc_bias == "bearish" and self.risk_regime == "bearish":
            return False, "BTC downtrend + risk-off (dominance rising) — long blocked"
        # short while BTC bullish AND risk-on (alt bid) -> block
        if side == "SELL" and self.btc_bias == "bullish" and self.risk_regime == "bullish":
            return False, "BTC uptrend + risk-on (alt bid) — short blocked"
        # MTF fully opposed to the side -> block (don't scalp against the stack)
        opposed = (side == "BUY" and self.htf_bias == "bearish" and self.mtf_bias == "bearish"
                   and self.ltf_bias == "bearish")
        if opposed:
            return False, "LTF/MF/HTF all bearish — long blocked"
        opposed_s = (side == "SELL" and self.htf_bias == "bullish" and self.mtf_bias == "bullish"
                     and self.ltf_bias == "bullish")
        if opposed_s:
            return False, "LTF/MF/HTF all bullish — short blocked"
        return True, ""


@dataclass
class ContextSeries:
    """Raw candle series needed to build a MarketContext (one tick)."""

    btc: list[float] = field(default_factory=list)            # BTCUSDT closes (HTF)
    pair: list[float] = field(default_factory=list)           # tradable closes (HTF)
    alt_basket: list[list[float]] = field(default_factory=list)  # other alts' closes (HTF)
    ltf: list[float] = field(default_factory=list)            # tradable LTF closes
    mtf: list[float] = field(default_factory=list)            # tradable MF closes
    htf: list[float] = field(default_factory=list)            # tradable HTF closes
    dominance: list[float] = field(default_factory=list)      # optional BTC.d series


def build_context(cs: ContextSeries, lookback: int = 30) -> MarketContext:
    """Compute relational cross-asset + MTF context from raw series.

    `lookback` controls the return window for dominance/RS proxies. All inputs are
    *closes* (lists of floats); the caller converts Candle -> .c.
    """
    btc_bias = _bias_of(cs.btc, 50)
    btc_ret = _ret(cs.btc, lookback)

    # dominance proxy: alt basket avg return minus BTC return
    if cs.alt_basket:
        basket_ret = sum(_ret(a, lookback) for a in cs.alt_basket) / len(cs.alt_basket)
    else:
        basket_ret = _ret(cs.pair, lookback)  # fallback: pair vs itself = no RS info
    pair_ret = _ret(cs.pair, lookback)
    alt_rs = pair_ret - btc_ret

    if cs.dominance:
        dom_delta = cs.dominance[-1] - cs.dominance[max(0, len(cs.dominance) - lookback)]
    else:
        # proxy: if alts outperform BTC, capital is rotating into alts => dominance falling
        dom_delta = -alt_rs  # negative = alt bid (risk-on)

    risk = ("bullish" if dom_delta < -0.002 else
            "bearish" if dom_delta > 0.002 else "neutral")

    breadth = 0.5
    if cs.alt_basket:
        above = sum(1 for a in cs.alt_basket if _bias_of(a, 50) != "bearish")
        breadth = above / len(cs.alt_basket)

    ltf_bias = _bias_of(cs.ltf, 20) if len(cs.ltf) >= 20 else "neutral"
    mtf_bias = _bias_of(cs.mtf, 50) if len(cs.mtf) >= 50 else "neutral"
    htf_bias = _bias_of(cs.htf, 50) if len(cs.htf) >= 50 else _bias_of(cs.btc, 50)

    biases = [b for b in (ltf_bias, mtf_bias, htf_bias) if b != "neutral"]
    mtf_confluence = len(biases) >= 2 and len(set(biases)) == 1

    # pullback_to_anchor: LTF retraced against the HTF bias recently, then resumed toward it
    pullback = False
    if htf_bias != "neutral" and len(cs.ltf) >= 20:
        ltf_ret = _ret(cs.ltf, 10)
        if htf_bias == "bullish":
            # LTF dipped (negative) but pair still above HTF anchor -> bought the dip
            pullback = ltf_ret < 0 and pair_ret >= 0
        else:
            pullback = ltf_ret > 0 and pair_ret <= 0

    return MarketContext(
        btc_bias=btc_bias, btc_ret=btc_ret,
        dominance_delta=dom_delta, risk_regime=risk,
        alt_rs_btc=alt_rs, alt_breadth=breadth,
        ltf_bias=ltf_bias, mtf_bias=mtf_bias, htf_bias=htf_bias,
        mtf_confluence=mtf_confluence, pullback_to_anchor=pullback,
    )
