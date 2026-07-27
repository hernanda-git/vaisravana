# Vaiśravaṇa E2E Evaluation v2 — Expert Quant Review

**Date:** 2026-07-27
**Data:** 60 closed trades, Jul 26 23:19 – Jul 27 00:38 UTC (~80 min)
**Live version:** Pre-v0.0.18 (directional gate not deployed)

---

## 1. Current Metrics

| Metric | Value | Target |
|--------|-------|--------|
| **WR** | 36.7% | ≥56% |
| **Expectancy** | −0.029R | >+0.10R |
| **Profit Factor** | ~0.75 (est) | >1.2 |
| **Activity** | ~45 trades/hr | ≥5/hr |
| **SL win rate** | 0% (13 closes) | >0% |
| **TP rate** | 13% of closes | >20% |
| **MAXHOLD rate** | 65% (avg −0.02R) | <50% |

---

## 2. Root Cause Analysis

### #1 (THE BIG ONE): BUY bias into a bearish regime — −8.78R bleed

| Side | Count | WR | Sum R | Exp R |
|------|-------|-----|-------|-------|
| **BUY** | 38 (63%) | 23.7% | −8.78R | **−0.231R** |
| **SELL** | 22 (37%) | 59.1% | +7.03R | **+0.320R** |

SELL alone is profitable (+7.03R). BUY alone is a disaster (−8.78R). The bot is **long-biasing into a downtrend** with no regime awareness on the deployed version. Code fix exists (v0.0.18 `entry_allowed` gate) but was **never deployed.**

**Evidence:** BUY R-distribution = 11 big losses + 17 small losses vs 4 big wins + 6 small wins. SELL = 3 big losses vs 10 big wins. The direction of the trade determines outcome more than the entry quality.

### #2: SL placement = guaranteed loss (0% win rate on 13 closes)

Every SL hit was a full loss. The SL distance (1.0×ATR for scalp, 1.5× for day, 2.0× for swing) is mathematically correct, but the **entry price is wrong** — trades are entered at swing extremes (buying highs / selling lows), so any reversal triggers SL immediately.

**Root cause:** No `pullback_to_anchor` filter on the live version. Entry fills at the 1m close without checking if price has already run too far.

### #3: 65% MAXHOLD rate

Two out of three trades expire at break-even without reaching SL or TP. In a choppy/range market this is expected, but the **regime filter** (#1) turns many of these into directional wins. The v0.0.18 gate fixes this by ensuring BUY only fires in a bullish regime — so the trend helps the trade reach TP instead of oscillating until MAXHOLD.

### #4: Per-pair volatility mismatch

Same SL/TP mults for BTC (low vol) and 1000BONK (high vol). A 1.0×ATR SL on 1000BONK is ~2× tighter in price distance than on BTC because meme coins have higher ATR%. This results in meme coin SL being triggered by normal volatility noise.

---

## 3. Improvement Proposal (Ranked By Impact)

### TIER 1 — Deploy the directional fix (highest ROI)

| # | Fix | Expected Impact | Effort |
|---|-----|-----------------|--------|
| 1 | **Deploy v0.0.18 entry gate** — blocks BUY in non-bullish regime, requires pullback confirmation in neutral regimes | **36.7% → ~50% WR, exp positive** (SELL is already +0.32R) | 1 deploy |
| 2 | **ADX trend strength filter** — block entries when ADX < 20 (weak/choppy trend → high MAXHOLD rate) | Reduce MAXHOLD from 65% → ~40%, improve avg R per trade | ½ day |
| 3 | **Volatility-adaptive SL** — scale SL mult by pair's ATR percentile (tighter for stable pairs, wider for memes) | Reduce SL rate on meme coins, keep BTC stops tight | ½ day |

### TIER 2 — Structural improvements

| # | Fix | Rationale |
|---|-----|-----------|
| 4 | **Trailing stop after +0.5R** — convert MAXHOLD to a runner that locks in partial profit | Converts 65% break-even closes into small wins |
| 5 | **Per-side entry threshold** — BUY requires 0.63 (harder) when regime is neutral/bearish, SELL gets 0.58 (easier) | Auto-rebalance BUY/SELL ratio from 63:37 toward 50:50 |
| 6 | **Tighter side-bleed gate** — lower `SIDE_EXP_FLOOR_R` from −0.05 to −0.10 (currently per-side gate is −0.05, which means a side can bleed 5 trades at −1R each before being blocked) | Catch directional bleed faster |

### TIER 3 — Optimization

| # | Fix | Rationale |
|---|-----|-----------|
| 7 | **Pair-level sizing** — reduce notional on consistently losing pairs (SOL, WLD, 1000BONK, ETH) by 50% | Lower drawdown on unprofitable pairs |
| 8 | **Post-SL cooldown** — skip next 3 entries on a pair+side after an SL hit | Prevents revenge re-entry into the same losing setup |

---

## 4. Decision

**Recommendation:** Deploy v0.0.18 first (fixes #1 immediately, ~0 dev time). Then implement Tier 2 items (trailing stop + per-side thresholds + tighter side gate) as v0.0.19.

The data proves that the bot's scoring engine WORKS — SELL produces +0.32R expectancy at 59.1% WR. The only problem is that 63% of trades are in the wrong direction. Fix the direction and the WR solves itself.
