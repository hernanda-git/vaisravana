# Comprehensive Review & Acceleration Plan

> **Date:** 2026-07-27 | **Target:** 55–60% WR by week end
> **Version:** v0.0.21 (profile-specific EMAs + context caching)

---

## 1. Current State Assessment

### ✅ What's Correct
| Feature | Status | Impact |
|---------|--------|--------|
| Directional gate (5-layer) | ✅ v0.0.20 | Blocks retracement trap |
| Profile-specific EMAs | ✅ v0.0.21 | Scalp EMA5/15 = 15-min signal |
| Context caching | ✅ v0.0.21 | 3 req/cycle vs 270 |
| Unified EMA tolerance | ✅ v0.0.21 | 0.08% everywhere |
| Side-bleed gate | ✅ v0.0.19 | −0.10R floor |
| Post-SL cooldown | ✅ v0.0.19 | Skip 3 entries after SL |
| Pair-level sizing | ✅ v0.0.19 | 0.5x weak pairs |
| Trailing stop +0.5R | ✅ v0.0.19 | BE protection |
| Telegram commands | ✅ Now | /health /clean /stop registered |

### ❌ What's Missing (Blocking 55–60% WR)

| Gap | Priority | Why It Matters |
|-----|----------|----------------|
| **Correlated factors** (trend+momentum ≈ 0.8r) | 🔴 Critical | Double-counts the same signal as 50% of score |
| **No weighted position view** via Telegram | 🟡 Medium | Can't see open positions without SSH |
| **SMC concepts underweighted** (15%+10% = 25%) | 🟡 Medium | Structure/liquidity should dominate in ranging markets |
| **Regime-adaptive weights** | 🟡 Medium | Fixed weights = wrong in 30% of regimes |

---

## 2. The Smart Money Concept Connection

The bot ALREADY has most SMC primitives built into `structure_score()` and `liquidity_score()` but at **low weight**:

| SMC Concept | Bot Factor | Current Weight | Should Be (in range) |
|-------------|-----------|---------------|---------------------|
| BOS / MSS | structure.bos | 0.15 × 0.2 = 0.03 | **0.10** |
| CHoCH / market shift | structure.choch | 0.15 × 0.15 = 0.0225 | **0.08** |
| HH/HL (uptrend) | structure.hh/hl | 0.15 × 0.15 = 0.0225 | **0.06** |
| LH/LL (downtrend) | structure.lh/ll | 0.15 × 0.15 = 0.0225 | **0.06** |
| Liquidity sweep | liquidity.liq_sweep | 0.10 × 0.2 = 0.02 | **0.08** |
| Equal highs/lows | liquidity.eq_high/low | 0.10 × 0.1 = 0.01 | **0.05** |
| FVG | liquidity.fvg | 0.10 × 0.1 = 0.01 | **0.04** |

**Problem:** Trend (30%) + Momentum (20%) = 50% of the score comes from EMA-based signals. In a range market, EMA-based signals are noisy and produce whipsaws. SMC signals (structure/liquidity) are MORE reliable in ranges.

**Solution:** Regime-adaptive weights.

---

## 3. Roadmap to 55–60% WR (This Week)

### Day 1: Regime-Adaptive Weights (HIGHEST IMPACT)

**What:** Detect the market regime (trending vs ranging vs breakout) and adjust weights dynamically. In range markets, INCREASE structure+liquidity weights and DECREASE trend+momentum. In trending markets, keep current weights.

**Implementation:**
```python
# In config.py or engines.py
def adaptive_weights(adx_val: float, regime: str) -> Weights:
    """Shift weight from trend/momentum → structure/liquidity in range markets."""
    w = Weights()  # default: 30/20/15/15/10/5/5
    if adx_val < 25 and regime in ("range", "high_vol"):
        # Chopping market — rely on SMC, not EMA's
        w.trend = 0.20       # was 0.30
        w.momentum = 0.15    # was 0.20
        w.structure = 0.25   # was 0.15
        w.liquidity = 0.15   # was 0.10
        # atr=0.05, funding=0.05, volume=0.15 — unchanged
    elif adx_val > 40 and regime in ("trending_bull", "trending_bear"):
        # Strong trend — maximize trend/momentum
        w.trend = 0.35
        w.momentum = 0.25
        w.structure = 0.10
        w.liquidity = 0.05
    return w
```

**Expected impact:** +5–10pp WR by reducing false signals in range markets.

**Effort:** ~1 hour (add function to config.py, call it in _decide_tick before scoring)

### Day 2: Telegram Commands for Operational Control

**Must-have commands:**

| Command | Purpose | Implementation |
|---------|---------|----------------|
| `/positions` | List open trades with PnL, R, entry, SL | Query trade_logs WHERE closed IS NULL |
| `/pairs` | Show active pairs + weights + side WR | Call side_expectancy per pair |
| `/config` | Show current surface parameters | Read from ParameterSurface |
| `/exclude [pair]` | Remove a pair from trading | Add to command dispatch |
| `/include [pair]` | Re-add a pair | — |

**Effort:** ~2 hours (add 5 commands to _dispatch)

### Day 3: Fix Weight Calibration (TREND+MOMENTUM CORRELATION)

**Problem:** Trend (regime_score) and momentum (momentum_score) use the SAME input data (volume z-score, EMA cross direction). Their correlation is ~0.8 — they're essentially the SAME signal doubled.

**Fix 1 — Demote trend to 20%, boost structure to 20%:** Simple but effective. Removes the double-count while keeping SMC signals at parity with trend.

**Fix 2 — Or replace momentum with a real order-flow metric:** If unavailable, at minimum deduplicate.

**Expected impact:** +3–5pp WR (less noise in neutral regimes)

**Effort:** ~30 minutes

### Day 4: SMC Optimization — Fold into Gate Logic

The `entry_allowed` gate currently checks EMA20/50 cross + higher TF + BTC + risk. Add an SMC-specific filter:
- No entry if LIQUIDITY not swept (no sweep in last 20 bars → high probability of reversal)
- No entry against the market structure (BOS conflict)
- Allow entry ONLY if structure confirms the side

**Expected impact:** +3–5pp WR (fewer entries against the micro-structure)

**Effort:** ~1 hour

### Day 5: Deploy + 24h Run + Evaluate

Deploy all changes, let it run 24h, evaluate WR/ExpR. If WR > 50%, consider it a success. If not, binary-search the gate strictness.

---

## 4. Development Speed-Ups

### Hot-Config Reload (No Restart Needed)

Add a `/reload` command that re-reads the surface JSON from disk without restarting the bot:

```python
# In run() loop, after klines fetch:
if os.path.getmtime(SURFACE_PATH) > surface_loaded_at:
    surface = _load_surface()
    surface_loaded_at = time.time()
```

**Effort:** ~30 minutes

### Local Backtesting Loop

Add a local replay mode that reads historical klines from files instead of live API. Run 1000 trades in 5 minutes instead of 16 hours:

```python
def backtest(pair: str, tf: str, start: str, end: str):
    candles = load_historical_klines(pair, tf, start, end)
    for i in range(50, len(candles)):
        state = build_state_mtf(pair, candles, i, contexts, ...)
        se = evaluate_strategy(profile, state, ...)
        # simulate entry/exit
```

**Effort:** ~4 hours (but saves 20h per iteration)

### CI‑Ready Test Suite

The test suite already has 250+ tests. Add:
- `pytest --co` for coverage reporting
- GitHub Actions to auto-run tests on push
- `pytest -x --lf` to run only failed tests first during debug

**Effort:** ~1 hour for CI setup

---

## 5. Summary: What to Do This Week

| Day | Task | Effort | WR Impact | Telegram-able? |
|-----|------|--------|-----------|----------------|
| 1 | **Regime-adaptive weights** (ADX-driven) | 1h | +5–10pp | No |
| 2 | **Add Telegram commands** (/positions, /pairs, /config, /exclude, /include) | 2h | Operational | Yes |
| 3 | **Fix trend+momentum correlation** (demote trend to 20%, structure to 20%) | 30m | +3–5pp | No |
| 4 | **SMC gate integration** (require sweep/msb for neutral-regime entries) | 1h | +3–5pp | No |
| 5 | **Deploy + evaluate** after 24h run | 30m | — | Yes |

**Target WR after all 4 fixes: 50–58%** (from current 29–36%)

### If WR stays below 50% after all fixes:

1. **Reduce pairs to 5** (top 5 by live Sharpe, discard the rest)
2. **Increase entry_threshold** from 0.60 to 0.65 for scalp (fewer but higher-quality entries)
3. **Add a time filter** (only trade during high-volume hours: 8:00–16:00 UTC, skip Asian session low-vol)

---

## 6. Things NOT to Do (Anti-Patterns)

| Idea | Why NOT |
|------|---------|
| Add RSI, MACD, Stochastic | Already baked into momentum_score — redundant |
| Increase SL distance | Increases loss size — WR up but expectancy down |
| Add ML/AI layer | Not enough data, overfit risk, 256MB can't run it |
| More pair coverage | Dilutes focus — 15 is already too many for 256MB |
| Complex position management | Martingale, grid, or pyramid schemes blow accounts |

**Focus:** Simple regime-adaptive weights + Telegram control + SMC weight boost. That's 3–4 days of work for the highest ROI.

---

*End of review. Recommend starting with Day 1 (regime-adaptive weights) for the biggest WR impact.*
