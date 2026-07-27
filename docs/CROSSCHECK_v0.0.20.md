# Vaiśravaṇa — Comprehensive Cross-Check & Blind Spot Analysis

> **Date:** 2026-07-27
> **Version:** v0.0.20
> **Type:** Deep audit — architecture, assumptions, hidden flaws

---

## 1. Executive Summary

After fixing the directional gate (v0.0.20), the bot still has **8 blind spots**
that range from theoretical (weight calibration) to structural (the context system
cannot actually run on the production VM). The biggest finding: **the bot is both
overengineered and underpowered** — it has sophisticated multi-asset, multi-timeframe
logic that cannot physically execute on the 256MB Fly VM within the 60-second
cycle window, so most of the "smart" features silently fall back to neutral defaults.

---

## 2. Blind Spot #1: The Context System Doesn't Actually Run

### Problem

`build_context_for()` is called once per pair per cycle (15× per minute). Each call
makes **18+ independent HTTP requests**:
- 1× BTCUSDT 1h klines
- 14× alt basket 1h klines (every other pair)
- 1× pair klines (1h)
- 1× LTF klines (1m)
- 1× MTF klines (15m or 1h)

**Total: 270 HTTP requests per 60-second cycle.**

Each request uses `urllib.request.urlopen(url, timeout=15)` — synchronous, blocking.
On a 256MB Fly VM with ~2 vCPUs, these requests queue up. With timeout=15s and
~270 requests, the expected wall-clock time to complete ALL fetches is:
- If all succeed instantly (unlikely): ~15-30s per pair = 15-30s × 15 pairs... 
  actually they're sequential, not parallel, within one `build_context_for` call.
- More realistic: most requests timeout → context data defaults to "neutral"

### Evidence

From the v0.0.19 run: ADX blocked 52 entries. But the decisions_log also shows
the engine produced 34 ENTRY decisions with scores averaging 0.75 — HIGH confidence.
If the context data were actually working (btc_bias, risk_regime), the gate would
have blocked more. The fact that BUY was never blocked (0/34) suggests btc_bias
and risk_regime were "neutral" — the gate defaulted to allowing BUY.

### Impact

**The entire cross-asset and MTF relational context system is cosmetic.**
`btc_bias`, `risk_regime`, `pullback_to_anchor`, `mtf_confluence` are "neutral" /
"false" most of the time because the HTTP requests to populate them time out.

### Fix

Either:
- **Cache the context data** across cycles (BTC data changes slowly — cache for
  5-15 min, not 60s)
- **Reduce the number of pairs** (15 is too many for the VM)
- **Increase VM memory** to 512MB+
- **Move BTC/dominance data to a separate low-frequency fetcher** that runs every
  5 min, not every tick

---

## 3. Blind Spot #2: ctx_boost() Is a Placebo

### Problem

`ctx_boost()` returns a multiplier in [0.9, 1.12]. For a typical entry score
of 0.75:

```
Worst boost:  0.75 × 0.90 = 0.675 (still well above 0.60 entry threshold) ✅
Best boost:   0.75 × 1.12 = 0.84  (also above threshold) ✅
```

**The boost never changes a decision outcome.** A score that's above threshold
stays above. A score below threshold stays below. The only thing it changes is
how "confident" the bot looks — it has zero effect on whether trades are taken.

### Impact

**ctx_boost() consumes CPU cycles producing a number that's never used to make
a decision.**

### Fix

Remove the boost or make it meaningful: ±0.15 instead of ±0.05, or eliminate it
entirely and rely on the hard gate (`entry_allowed`) which actually blocks entries.

---

## 4. Blind Spot #3: Two Different EMA Tolerances

### Problem

There are TWO implementations of the EMA20/50 bias check with DIFFERENT tolerances:

| Location | Tolerance | Code |
|----------|-----------|------|
| `scripts/bot_paper.py:235-236` | **0.05%** | `ema20 > ema50 * 1.0005` |
| `src/marketcontext.py:47-48` | **0.08%** | `e20 > e50 * (1 + 0.0008)` |

The `build_state()` uses 0.05%; `build_context()` uses 0.08%. These produce
DIFFERENT `htf_bias` results for the same kline data. With a 0.03% gap between
them, the same pair can be "bullish" in one place and "neutral" in the other.

### Impact

The `entry_allowed` gate (v0.0.20) checks `state.htf_bias` from `build_state()`.
But the `decide_ctx()` context gate checks `MarketContext.htf_bias` from
`build_context()`. These can disagree, creating a **race condition** where one
gate permits and the other blocks inconsistently.

### Fix

Unify the tolerance. Pick one value and use it everywhere.

---

## 5. Blind Spot #4: ctx_gate_open() Is Redundant

### Problem

There are **4 independent gate layers** running sequentially on every entry:

```
Decide() → decide_ctx()
  └── ctx_gate_open()        ← blocks extreme conflicts (BTC+risk both adverse)
Score passes?
  → evaluate_strategy()

Entry Gate in _decide_tick:
  └── ADX gate               ← blocks low ADX
  └── entry_allowed()        ← hierarchical HTF gate (v0.0.20)
  └── Per-side threshold     ← adjusts threshold for BUY/SELL
```

Each gate is designed independently but they overlap. `ctx_gate_open()` blocks
BUY when BTC bearish AND risk bearish. But `entry_allowed()` ALSO blocks BUY
when BTC bearish (single condition). And the ADX gate also blocks in weak trends.

### Impact

**Layered gates don't improve signal quality — they just reduce the number of
trades.** The pass-through rate after 4 gates is low but the remaining trades
still have the same win probability as the unfiltered set. This is called
"selection bias": filtering doesn't create edge, it just reduces sample size.

### Fix

Consolidate into ONE gate with clear, non-overlapping conditions. Remove
`ctx_gate_open()` entirely (it's redundant with `entry_allowed` now).

---

## 6. Blind Spot #5: EMA20/50 Is Wrong for 1m Scalping

### Problem

**Timeframe mismatch:** The EMA20/50 cross on 15m needs 50 bars × 15m = 750 min
(12.5 hours) to produce a stable signal. But the scalp profile holds trades for
only 15 min (MAXHOLD). **The entry signal is 50× slower than the trade duration.**

```
EMA20/50 on 15m → stabilizes after 12.5 hours → signal: bullish
                                      ↓
                    Scalp entry at 1m close → hold 15 min
                                      ↓
                    15m EMA still bullish (slow to change)
                                      ↓
                    But 1m price can reverse 3-4 times in 15 min
                                      ↓
                    Trade closes at SL or MAXHOLD while 15m is still bullish
```

The signal says "the 15m trend is up" but the trade duration (15 min) is too
short for the 15m trend to express itself. The bot enters on a 15m trend signal
but exits before the trend can deliver.

### Evidence

- **64.6% MAXHOLD rate** in historical data — trades expire before reaching TP
- **23.1% SL rate** — trades reverse within the hold period
- **Only 12.3% TP rate** — most trades don't survive long enough to reach TP
- **MAXHOLD avg R = −0.026R** — essentially randomly expired at market price

### Fix

**Match the signal timeframe to the hold timeframe:**

| Strategy | Hold Time | Use EMA | Signal Stabilizes | Match? |
|----------|-----------|---------|-------------------|--------|
| Scalp | 15 min | **EMA5/15 on 1m** (not 15m!) | 5-15 min | ✅ |
| Day | 4 hours | EMA20/50 on 15m | 12.5 hours | ✅ |
| Swing | 48 hours | EMA50/200 on 1h | 50-200 hours | ✅ |

Currently ALL three strategies use the 15m EMA20/50 for `htf_bias`. They should
each use their OWN profile-appropriate EMA.

---

## 7. Blind Spot #6: The 3 Strategies Are Not Independent

### Problem

All three strategies (scalp, day, swing) share the SAME `htf_bias` from the
SAME context TFs. The only differences are:
- `entry_threshold` (0.60 vs 0.58 vs 0.56)
- `sl_atr_mult` / `tp_atr_mult`
- `max_hold_min`

**They all enter on the same signal with different exits.** This is not three
strategies — it's one strategy with three risk profiles.

### Evidence

In the v0.0.19 run with 34 trades:
- Likely >90% from Scalp (1m) because Day (15m) produces ~1 signal per pair per
  15 min × 15 pairs = ~15 signals per 15 min vs Scalp's 15/min × 15 pairs
- Swing (1h) produces even fewer

### Impact

The "multi-strategy" design creates the illusion of diversification but doesn't
actually provide independent trading streams. A single market regime affects all
three the same way.

### Fix

Make strategies genuinely independent:
- **Profile-specific EMAs**: Scalp uses 1m EMA5/15, Day uses 15m EMA20/50,
  Swing uses 1h EMA50/200
- **Profile-specific context TFs**: Scalp's context TFs should be faster
  (1m, 5m), Day's should be medium (15m, 1h), Swing's should be slow (4h, 1d)

---

## 8. Blind Spot #7: ctx_gate_open() Can't Flip Direction

### Problem

`ctx_gate_open()` in `marketcontext.py` is called inside `decide_ctx()` AFTER
`decide()` has already picked a side (BUY or SELL). The gate can only DOWNGRADE
an ENTRY to WATCH — it cannot CHANGE which side the bot picks.

```python
base = decide(s, surface, ...)  # picks BUY or SELL
if base.decision != "ENTRY":
    return base
# ctx can only block or boost — never change the side
allowed, reason = ctx.ctx_gate_open(base.side)
if not allowed:
    return Decision(side=None, decision="WATCH", ...)
```

If the 7-factor engine picks BUY (score 0.75) and the context says BTC is
bearish, the gate can:
- Block entry (good) → WATCH
- Or allow entry (bad) → ENTRY

**But it can't switch to SELL.** Even if the context overwhelmingly favors
shorts, the engine's decision is locked.

### Fix

The context should influence the side selection BEFORE the decision is made,
not after. Move the context data into the scoring itself:
```python
# Instead of:
base = decide()       # pick side
ctx_boost(base)       # modulate after

# Should be:
long = score_side(s, "BUY", surface, context)
short = score_side(s, "SELL", surface, context)
# Context is part of each side's score, not an afterthought
```

---

## 9. Blind Spot #8: Statistical Insignificance

### Problem

All conclusions so far are based on:
- Pre-v0.0.19: **65 trades** (about 3.5 hours)
- v0.0.19 fresh: **34 trades** (25 minutes)
- Total: **99 trades**

For a 15-pair, 3-strategy bot, this is **not enough data.** At 95% confidence,
you need approximately:

| Target WR | Trades needed | At current rate (18/hr) | 
|-----------|--------------|------------------------|
| ±5% precision | ~384 trades | ~21 hours |
| ±3% precision | ~1,067 trades | ~59 hours |
| ±2% precision | ~2,401 trades | ~133 hours |

All the improvements made (directional gate, ADX, vol-SL, trailing stop, etc.)
need 500+ trades to evaluate properly. The 34-trade v0.0.19 run was only 25
minutes — not even one full trading session.

### Impact

We don't know if the changes actually improve WR or if the results are noise.

### Fix

Let the bot run for **24-48 hours minimum** before evaluating. Cancel any
conclusions drawn from <50 trades.

---

## 10. Summary of Issues by Severity

| # | Issue | Severity | Fix Effort | Expected Impact |
|---|-------|----------|------------|-----------------|
| 1 | Context system doesn't run (270 req/cycle) | 🔴 Critical | Moderate | Gate works correctly |
| 2 | ctx_boost() is a placebo | 🟡 Medium | Low | No change (cosmetic) |
| 3 | Two different EMA tolerances | 🟡 Medium | Low | Consistent signals |
| 4 | ctx_gate_open() redundant with entry_allowed | 🟡 Medium | Low | Cleaner code |
| 5 | EMA20/50 wrong for scalp (50× slower than hold) | 🔴 Critical | Moderate | **High** — fixes timeframe mismatch |
| 6 | 3 strategies not independent | 🟡 Medium | Moderate | True diversification |
| 7 | ctx_gate can't flip direction | 🟡 Medium | Low | Better direction selection |
| 8 | Statistical insignificance | 🟢 Info | None (time) | Wait 24-48h before evaluating |

---

## 11. Recommended v0.0.21 Action Plan

### Immediate (high impact, low effort)

1. **Consolidate gates** — remove redundant `ctx_gate_open()`, keep only
   `entry_allowed()` with the hierarchical HTF gate (already fixed in v0.0.20)

2. **Unify EMA tolerance** — use 0.08% everywhere (consistent with marketcontext)

3. **Remove ctx_boost()** or make it meaningful (±0.15)

4. **Cache context data** — BTC bias and risk regime change slowly; fetch every
   5 min, not every tick. Store in module-level dict.

### High Impact (moderate effort)

5. **Profile-specific EMAs:**
   - Scalp: `htf_bias` from **1m EMA5/15** (5-15 min → matches 15 min hold)
   - Day: `htf_bias` from **15m EMA20/50** (unchanged)
   - Swing: `htf_bias` from **1h EMA50/200** (slow enough for 48h hold)

   This is THE most important fix. The timeframe mismatch (#5) means the entry
   signal and exit time don't align.

6. **Make ctx influence side selection:**
   - Pass contextual bias (BTC, dominance) into `score_side()` so it changes
     LONG vs SHORT scores directionally, not just boosts the chosen side.

### Requires Testing

7. **Run for 24h minimum** before any evaluation. Track trades, compare against
   the baseline. Don't change parameters during the run.

---

*End of cross-check analysis. The fix order should be: cache context →
profile-specific EMAs → directional ctx influence → 24h run before evaluating.*
