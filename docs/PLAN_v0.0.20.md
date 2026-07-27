# Vaiśravaṇa — Direction Fix Plan (v0.0.20)

> **Author:** Expert Quant Review
> **Date:** 2026-07-27
> **Status:** Plan — ready for implementation
> **Target version:** v0.0.20

---

## 1. Executive Summary

The bot's win rate (29–36% across two live runs) is driven by a single root cause:
**the direction system allows BUY trades in regimes where BUY is systematically
unprofitable.** The scoring engine uses a single EMA20/50 crossover on one timeframe
(15m) to determine direction, and the entry gate (`entry_allowed`) is too permissive
(`or` logic across three independent signals).

**Fix:** Replace the flat `or` gate with a **hierarchical HTF gate** that requires
the pair's own trend to agree with the trade direction AND checks a higher timeframe
(1h/4h) to prevent buying retracements within larger downtrends.

**Projected impact:** 29–36% WR → **50–58% WR** (SELL achieved 51.9% in live data
when the engine correctly picked it).

---

## 2. Historical Data Summary

### Run 1 — Pre-v0.0.19 (65 closed trades, ~3.5h)

| Metric | BUY | SELL | Overall |
|--------|-----|------|---------|
| Closed | 38 (58%) | 27 (42%) | **65** |
| WR | 23.7% | **51.9%** | 35.4% |
| Exp R | −0.231R | **+0.174R** | −0.063R |
| ΣR | −8.78R | +4.69R | −4.09R |

### Run 2 — v0.0.19 fresh (34 closed trades, ~25 min)

| Metric | BUY | SELL | Overall |
|--------|-----|------|---------|
| Closed | **34 (100%)** | 0 (0%) | **34** |
| WR | 29.4% | N/A | 29.4% |
| Exp R | −0.279R | N/A | −0.279R |
| ΣR | −9.49R | — | −9.49R |

### Combined (99 trades)

| Side | Closed | WR | Exp R |
|------|--------|----|-------|
| BUY | 72 | **25.0%** | **−0.254R** |
| SELL | 27 | **51.9%** | **+0.174R** |

**SELL is profitable. BUY is a disaster. The fix is to stop buying when the market
does not support long positions.**

---

## 3. Scoring Engine — Full Technical Reference

### 3.1 The 7 Factors (Σ weights = 1.0)

Defined in `src/config.py` (Weights class) and `src/engines.py`.

| # | Factor | Weight | Function | Range | What It Measures |
|---|--------|--------|----------|-------|-----------------|
| 1 | **Trend** | **30%** | `regime_score()` | [0,1] | Market regime classification + **EMA20/50 cross** (directional) |
| 2 | Momentum | 20% | `momentum_score()` | [0,1] | Volume z-score, delta z-score, exhaustion cap |
| 3 | Volume | 15% | `volume_score()` | [0,1] | Volume anomaly confirmation |
| 4 | Structure | 15% | `structure_score()` | [0,1] | BOS, CHoCH, HH/HL/LH/LL, candle body ratio |
| 5 | Liquidity | 10% | `liquidity_score()` | [0,1] | Sweep at support (long) or resistance (short), FVG |
| 6 | ATR | 5% | `atr_score()` | [0,1] | Volatility sweet spot (0.5%–2% ATR = 1.0) |
| 7 | Funding/OI | 5% | `funding_oi_score()` | [0,1] | Funding rate health, ADL rank |

For **SELL**, two factors differ from BUY:
- `regime_score()` is inverted: `trend_contrib = (1 - regime_score) * 0.30`
- `liquidity_score_bear()` checks `eq_high` (resistance sweep) instead of `eq_low`

### 3.2 The Scoring Calculation

```
BUY_score  = trend*0.30 + momentum*0.20 + volume*0.15 + structure*0.15
           + liquidity*0.10 + atr*0.05 + funding_oi*0.05

SELL_score = (1-trend)*0.30 + momentum*0.20 + volume*0.15 + structure*0.15
           + liquidity_bear*0.10 + atr*0.05 + funding_oi*0.05

decision   = "BUY" if BUY_score >= SELL_score else "SELL"
chosen     = max(BUY_score, SELL_score)
entry      = chosen >= entry_threshold (0.60 scalp / 0.58 day / 0.56 swing)
```

### 3.3 Moving Average — The EMA20/50 Cross

```python
# In scripts/bot_paper.py (the ONLY moving average in the system):

def _ema(vals: list[float], period: int) -> float:
    """Exponential Moving Average. k = 2/(period+1)."""
    k = 2.0 / (period + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e

def _ema_cross(closes: list[float]) -> tuple[bool, bool]:
    """Return (bullish, bearish) from EMA20 vs EMA50."""
    if len(closes) < 50:
        return False, False
    ema20 = _ema(closes[-20:], 20)
    ema50 = _ema(closes, 50)
    return ema20 > ema50 * 1.0005, ema20 < ema50 * 0.9995

# htf_bias is set from the HIGHEST structural context TF available:
#   scalp → 15m, day → 1h, swing → 4h
# Used in: (a) regime_score() as +/-0.15, (b) entry_allowed() gate
htf_bias = "bullish" if ema20 > ema50 else \
           "bearish" if ema20 < ema50 else \
           "neutral"
```

### 3.4 Sub-Score Calculations

Each factor function (from `src/engines.py`):

```python
def regime_score(s):                    # Trend 30%
    base = {"trending_bull": 0.8, "trending_bear": 0.2,
            "range": 0.5, "breakout": 0.6, "high_vol": 0.45}[s.regime]
    if s.htf_bias == "bullish":  base += 0.15
    elif s.htf_bias == "bearish": base -= 0.15
    return clamp(base)

def momentum_score(s):                  # Momentum 20%
    if s.is_exhaustion_spike: return 0.15
    return 0.4 + 0.4*clamp(s.vol_z/3) + 0.2*clamp(s.delta_z/3)

def volume_score(s):                    # Volume 15%
    return 0.5 + 0.5*clamp(s.vol_z/3)

def structure_score(s):                 # Structure 15%
    sc = 0.35
    if s.bos:    sc += 0.2
    if s.choch:  sc += 0.15
    if s.hh and s.hl:   sc += 0.15
    if s.lh and s.ll:   sc += 0.15
    sc += 0.15 * s.body_ratio
    return clamp(sc)

def liquidity_score(s):                 # Liquidity 10% (BUY)
    sc = 0.5
    if s.liq_sweep: sc += 0.2
    if s.eq_low:    sc += 0.1
    if s.fvg:       sc += 0.1
    return clamp(sc)

def liquidity_score_bear(s):            # Liquidity 10% (SELL)
    sc = 0.5
    if s.liq_sweep: sc += 0.2
    if s.eq_high:   sc += 0.1
    if s.fvg:       sc += 0.1
    return clamp(sc)

def atr_score(s):                       # Volatility 5%
    if s.atr_pct < 0.003: return 0.7
    if s.atr_pct > 0.03:  return 0.75
    if s.atr_pct <= 0:    return 0.6
    return 1.0

def funding_oi_score(s):                # Funding/OI 5%
    sc = 1.0
    if not s.funding_ok: sc -= 0.4
    if s.adl_rank >= 4:  sc -= 0.3
    return clamp(sc)
```

---

## 4. Root Cause Analysis

### 4.1 Primary Cause: The Retracement Trap

The single EMA20/50 cross on 15m generates `htf_bias`. When price rallies within a
larger downtrend, the 15m EMA can cross bullish (price retraces), but the 1h/4h EMA
remains bearish (downtrend intact). The bot interprets the 15m bullish cross as a
valid BUY signal and enters at the retracement top. The downtrend resumes, the trade
hits SL at −1R.

```
1h EMA:  bearish ╲      ╱      ← 15m looks bullish here
                   ╲    ╱        (retracement within downtrend)
                    ╲  ╱
                     ╲╱
                     BUY entry → reversal → SL

BOT: htf_bias = "bullish" (15m EMA20 > EMA50) → BUY ✓
REALITY: htf_bias2 (1h) = "bearish" → this is a pullback, not a trend change
```

**Bot has `htf_bias2` (the 1h/4h EMA cross) in `MarketState` but NEVER uses it in
the direction gate.** It's only consumed by `mtf_relational_score()`, a zero-weight
modulator that has no effect on the decision.

### 4.2 Secondary Cause: `or` Logic in Gate

```python
# Current gate (too permissive):
bull = (state.htf_bias == "bullish"
        OR state.btc_bias == "bullish"
        OR state.risk_regime == "bullish")

if side == "BUY" and not bull:
    return False  # BLOCKED (never reached — bull is always True)
```

Any one of three signals being bullish allows BUY. In practice, **BUY is never
blocked** because at least one signal is always bullish (0/34 BUY attempts blocked
in v0.0.19 run).

### 4.3 Tertiary Cause: Structural BUY Bias in Scoring

The `decide()` function picks the higher of BUY/SELL scores. In a neutral/choppy
market where both scores are similar, BUY tends to edge out SELL because:
- `regime_score` defaults to 0.5 in range markets (equal for both sides)
- With equal trend contribution, momentum/volume/structure decide
- These favor the side with recent price movement — typically the direction price
  just moved (chasing)

---

## 5. Proposed Fix — v0.0.20

### 5.1 Fix #1: Hierarchical HTF Direction Gate (CRITICAL)

Replace the flat `or` gate in `entry_allowed()` with a **tiered hierarchy**:

```
LAYER 1 — Pair's own HTF (htf_bias, EMA20/50 on highest context TF)
LAYER 2 — Higher TF agreement (htf_bias2, EMA20/50 on 1h/4h)
LAYER 3 — BTC context (btc_bias) — only overrides DOWN
LAYER 4 — Risk regime (risk_regime) — only overrides DOWN
LAYER 5 — Pullback confirmation for neutral regimes
```

```
For BUY:
  htf == "bullish"           (pair's own trend)
  AND htf2 != "bearish"      (higher TF doesn't disagree)
  AND btc  != "bearish"      (BTC leader doesn't disagree)
  AND risk != "bearish"      (risk regime doesn't disagree)

For SELL:
  htf == "bearish"           (pair's own trend)
  AND htf2 != "bullish"      (higher TF doesn't disagree)
  AND btc  != "bullish"      (BTC leader doesn't disagree)
  AND risk != "bullish"      (risk regime doesn't disagree)

For NEUTRAL htf:
  pullback_to_anchor required for BOTH sides
```

**Expected impact:** BUY blocked in all regimes where the higher TF disagrees.
This eliminates the retracement trap.

### 5.2 Fix #2: Gate Mirrors the Scoring Engine (IMPORTANT)

The direction gate currently uses `or` across three signals, but the scoring engine
uses a weighted sum. The gate should follow the same logic as the scoring engine:
- `htf_bias` is the primary directional signal (30% weight trend factor)
- `btc_bias` / `risk_regime` are secondary context modulators (cross-asset score is
  only 5% in the modulator, not a primary factor)
- The gate should respect this hierarchy

### 5.3 Fix #3: ADX on Structural TF (IMPORTANT)

Current ADX filter runs on the decision TF (1m) which is too noisy. Move it to the
highest structural TF available (15m for scalp, 1h for day). Increase threshold from
20 to 25.

### 5.4 Fix #4: Tighter Entry Thresholds (OPTIONAL)

The average entry score in v0.0.19 was 0.75 — well above the 0.60 threshold. Raising
the threshold to 0.65 would have blocked 38% of losing trades (the 0.65-0.70 bucket)
while only costing 20% of the winners. Consider after deploying Fix #1.

---

## 6. Execution Plan

### Phase 1: Fix Gate + Test (30 min)

| Step | File | Change | Tests |
|------|------|--------|-------|
| 1 | `scripts/bot_paper.py` | Rewrite `entry_allowed()`: hierarchical HTF gate | Update `test_phase25_entry_gate.py` |
| 2 | `scripts/bot_paper.py` | Move ADX to structural TF, threshold 25 | Update ADX tests |
| 3 | Run full suite | `pytest -q` | 231+ green |

### Phase 2: Commit + Tag (5 min)

| Step | Command |
|------|---------|
| 1 | `git add -A && git commit -m "v0.0.20: hierarchical HTF gate + ADX fix"` |
| 2 | `git tag v0.0.20 && git push origin main --tags` |

### Phase 3: Deploy + Verify (10 min)

| Step | Command | Expected |
|------|---------|----------|
| 1 | `flyctl deploy --remote-only --push --strategy immediate` | v0.0.20 live |
| 2 | `flyctl logs -n \| grep "v0\.0\.20"` | Boot confirmed |
| 3 | SSH query after 30 min | WR > 40%, SELL >= BUY |

### Phase 4: Monitor (ongoing)

| Metric | Target | Check |
|--------|--------|-------|
| WR | >50% | After 50+ trades |
| BUY/SELL ratio | 30-70% | Not >80% BUY |
| SL rate | <25% | Down from 38% |
| TP rate | >15% | Up from 5.9% |
| MAXHOLD rate | <50% | Down from 56% |

---

## 7. Rollback Plan

If v0.0.20 underperforms after 100 trades:

1. **Revert commit:**
   ```bash
   git revert HEAD --no-edit
   git push origin main
   flyctl deploy --remote-only --push --strategy immediate
   ```
2. **Alternative:** Tune gate parameters (htf2 check, ADX threshold)
   without rolling back the structural change.

---

## 8. Success Criteria

The fix is successful when, after 100+ closed trades:

- [ ] **WR ≥ 50%** (up from 29-36%)
- [ ] **Exp R ≥ +0.05R** (up from −0.06R to −0.28R)
- [ ] **BUY/SELL ratio between 30:70 and 70:30** (not 100:0)
- [ ] **SL rate < 25%** (down from 23-38%)
- [ ] **No BUY entries when htf2 is bearish** (the retracement trap)
- [ ] **BUY WR ≥ 40%** (up from 23-29%)

---

*End of plan document. Implement as v0.0.20.*
