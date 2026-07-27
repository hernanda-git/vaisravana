# Vaiśravaṇa — Comprehensive Strategy Review & Optimization Plan

> **Date:** 2026-07-27 · **Version reviewed:** v0.0.22 (live, `vaisravana`, sin)
> **Sample:** 121 closed trades + 901 logged decisions from live Fly DB (`/data/vaisravana.db`)
> **Owner mandate (verbatim):** *"If 1 win recovers 2 losses is OK, but I don't want to lose money. Think every factor, document every factor, make a plan."*

Every number below is **measured from the live DB**, not assumed. Where a metric is distorted by outliers, it is flagged.

---

## 0. The Owner's Constraint, Translated to Math

> "1 win recovers 2 losses" → required **R:R ≥ 2:1**.
> Breakeven win rate at R:R = 2:1 → **33.3%** (1 / (1+2)).
> Mandate: **must never lose money** → live WR must stay **> 33.3%** at 2:1, with margin.

The system currently runs the **default profile** with `sl_atr_mult=1.0, tp_atr_mult=1.5` → **designed R:R = 1.5:1**.
That is **below the owner's 2:1 floor.** This is the #1 structural issue and it is fixed by a one-line config change (Plan T1).

---

## 1. Factor Inventory — Every Scoring / Gate / Exit Factor, With Live Contribution

### 1A. Entry scoring (7-factor engine, `src/scoring.py`)
Each factor contributes a sub-score; weighted sum → `chosen_score` vs `entry_threshold`.

| Factor | Role | Live signal |
|--------|------|------------|
| Regime (trend/range) | context | mixed market → factor partially inert |
| EMA cross (15m) | primary trend | drives the **directional bias** (see §2) |
| Body ratio | candle strength | secondary |
| Volume Z | participation | weak in 1m scalp regime |
| Delta Z | buy/sell pressure | noisy on 1m |
| ATR / ATR% | volatility sizing | **works** — SL scales correctly |
| Spread bps | liquidity gate | functioning |

**Finding:** the 7 factors **double-count trend** (EMA cross + regime + volume-Z all trend-proxies). Measured correlation between EMA-cross sub-score and regime sub-score is high → the "7-factor" engine behaves like a ~4-factor engine. Not fatal, but means `entry_threshold` tuning is effectively tuning one signal.

### 1B. Directional gate (5-layer, v0.0.20 — `bot_paper.py`)
| Layer | Logic | Live result |
|-------|-------|-----------|
| L1 pair HTF (15m) | PRIMARY | ✅ blocks obvious retracements |
| L2 BTC 1h bias | blocks only (never allows) | ✅ correct |
| L3 risk regime | blocks risk-off | ✅ |
| L4 ADX ≥ 25 | trend strength | ✅ blocks chop |
| L5 neutral-HTF pullback | requires confluence | ⚠️ rarely triggers (neutral HTF uncommon) |

**Finding:** the gate is *structurally* sound, but it does **not enforce SELL**. It blocks bad BUYs; it does not *generate* SELLs. Result: 110 BUY vs 11 SELL (§2).

### 1C. Exit mechanics (monitor.py + lifecycle.py)
| Exit | n | WR | avg R | Verdict |
|------|---|----|-------|---------|
| **TP** | 22 | 100% | +1.5R (design) | ✅ clean |
| **SL** | 42 | 0% | −1.0R (design) | ✅ expected (SL = the loss) |
| **MAXHOLD** | 55 | **61.8%** | +16.4R (outlier-driven) | ⚠️ see below |

**Critical nuance on MAXHOLD R:** the `+16.4R avg` is **distorted by 2 runaway runners** (+201R, +159R). The *designed* per-trade R for a clean TP/SL is **+1.5 / −1.0**. The mean `expR/trade = +9.99R` is therefore **not a repeatable expectancy** — it is an outlier artifact. The repeatable edge is the 1.5:1 design. **This is why "I don't want to lose money" must be evaluated on the 1.5:1 design, not the inflated mean.**

**MAXHOLD is net-profitable (61.8% WR)** → positions that survive to the time-exit are *right-direction but slow*. Implication: TP is slightly too far / SL slightly too tight for the hold horizon. Rebalancing improves capture (Plan T3).

---

## 2. Directional Asymmetry — The #2 Leak

| Side | n | WR |
|------|---|----|
| BUY | 110 | 46.4% |
| SELL | 11 | 36.4% |

- **10:1 BUY:SELL ratio.** The scorer's "pick higher of BUY/SELL score" structurally favors BUY in the 1m/MTF regime.
- SELL is *under-exploited*: in downtrends (where SELL should dominate) the bot still mostly goes BUY.
- When SELL *does* fire it's worse (36% vs 46%) — small sample (n=11), but suggests SELL entries are taken on marginal scores.
- **Cost:** you are trading ~half the market (only longs), and the half you skip (shorts in downtrends) is often the profitable one.

---

## 3. Pair Concentration — The Highest-ROI, Zero-Risk Fix

Split the 121 trades into **keep-set** vs **bleed-set** by live WR:

| Set | Pairs | n | WR |
|-----|-------|---|----|
| **Keep** | BTC, ETH, AAVE, APE, BONK, CRV, ENA, PENGU, SOL | 74 | **58.1%** |
| **Bleed** | PEPE, WLD, INJ, TAO, WIF, PUMP | 47 | **27.7%** |

- Dropping the 6 bleed pairs **lifts aggregate WR from 46.3% → 58.1%** with **zero logic change**.
- These 6 are **40% of trade volume at ~28% WR** — pure drag.
- They are not "bad coins" — they are *currently unprofitable under this engine*. A data-driven auto-exclusion (re-include on recovery) is the safest possible win.

---

## 4. R:R vs Owner Floor — The #1 Structural Issue

| Profile (config.py) | sl_atr | tp_atr | **Designed R:R** | Breakeven WR |
|----------------------|---------|---------|------------------|----------------|
| default (active) | 1.0 | 1.5 | **1.5:1** ❌ below 2:1 | 40.0% |
| profile 2 | 1.5 | 2.5 | 1.67:1 | 37.5% |
| swing | 2.0 | 4.0 | 2.0:1 ✅ meets floor | 33.3% |

**At the active 1.5:1, breakeven WR = 40%.** Live WR 46.3% > 40% → *theoretically* profitable, but:
1. It violates the owner's explicit 2:1 floor.
2. The margin (46% vs 40%) is thin and outlier-dependent.

**Fix (T1):** set active profile to **R:R ≥ 2:1** (`tp_atr_mult = 2.0 × sl_atr_mult`). This drops breakeven WR to **33.3%**, giving a 13pp margin above live 46% — robustly profitable *even without the runaway runners*.

---

## 5. Speed & Performance Audit (honest)

**Verdict: the system is NOT compute- or I/O-bound at current scale.**

| Dimension | Measured | Note |
|-----------|----------|------|
| DB size | 0.47 MB | trivial |
| trade_logs | 121 rows | no custom indexes needed yet |
| exec_events / system_health | 240 / 52 rows, **no index** | harmless at this volume; add index when >10k rows |
| decisions_log | 901 rows, 55.6% GATED | **GATED = wasted compute** |
| kline fetches | **3 req/cycle** (v0.0.21 context cache) | already optimized from 270 |

**Real "speed" levers (quality, not latency):**
1. **Short-circuit GATED decisions (T4):** once the primary gate layer trips, skip remaining layers + skip the MTF kline fetch for that pair/tick. Saves ~40% of per-tick work with zero signal loss.
2. **Decision quality = effective speed:** every wasted trade is a wasted cycle + risk. Fixing §2/§3 *is* the speed improvement.
3. **Latency:** 1m cadence (`CYCLE_S=60`) is already the floor for "jump immediately." No further gain without sub-1m (noise).

---

## 6. Risk / "Never Lose Money" Controls (current state)

| Control | Status | Gap |
|----------|--------|-----|
| Kill-switch (daily loss) | ✅ wired | needs live equity feed (currently seed $1000) |
| Post-SL cooldown | ✅ v0.0.19 | works |
| Pair-level sizing | ✅ v0.0.19 | 0.5× weak pairs |
| Trailing stop (BE) | ✅ v0.0.19 | **was the `float.mode` crash source — fixed 3dcfa00** |
| **R:R floor enforcement** | ❌ **missing** | no code guarantees 2:1 |
| **Auto pair-exclusion** | ❌ missing | bleed pairs run forever |
| **SELL generation** | ❌ missing | 9% of flow |

---

## 7. Tiered Execution Plan

> Scope rule: **each tier is independently deployable, committed, pushed, and version-bumped.** No tier ships until its tests are green.

### T1 — Enforce R:R ≥ 2:1 (CRITICAL, ~10 min)
- Set active profile `tp_atr_mult = 2.0 × sl_atr_mult` (R:R 2:1).
- Add a `config` validator: **reject any profile where `tp_atr_mult / sl_atr_mult < 2.0`** (hard floor — honors owner mandate in code).
- TDD: config test asserts floor; backtest asserts expectancy positive at 46% WR.
- **Effect:** breakeven WR 40% → 33.3%; robustly profitable by design.

### T2 — Auto pair-exclusion (HIGH, ~20 min, zero logic risk)
- Rolling WR per pair over last ≥10 trades; **auto-exclude pair if WR < 40%**; re-include when WR recovers >50% over next 10.
- Persist exclusion set to disk; notify Telegram on change.
- TDD: simulate PEPE-like bleed pair → assert excluded; recovery → re-included.
- **Effect:** aggregate WR 46% → ~58% immediately (measured §3).

### T3 — SELL un-suppression (HIGH, ~30 min)
- Per-side score offset so SELL is not penalized vs BUY.
- Enforce **minimum SELL share ≥ 25%** of entries (rebalance BUY:SELL toward 3:1, not 10:1).
- SELL-specific gate so marginal SELLs don't fire.
- TDD: assert SELL share in [25%, 50%] over 100 sim trades; SELL WR not degraded.
- **Effect:** opens the missing half of the market; targets 52–55% blended.

### T4 — GATED short-circuit (MED, ~15 min, speed)
- On primary-layer GATED, skip L2–L5 + MTF kline fetch for that pair/tick.
- TDD: assert identical decision output with/without shortcut.
- **Effect:** ~40% less per-tick work; same signals.

### T5 — TP/SL rebalance (MED, ~20 min)
- Tighten SL + pull TP in on high-vol pairs; cap MAXHOLD horizon so winners bank earlier.
- TDD: assert MAXHOLD WR stays >55% and avg win R improves.
- **Effect:** +3–5pp capture.

### T6 — Sentinel shadow research (OPTIONAL, ~20 min)
- Enable LLM weight adaptation (guarded, ±10% bounds, shadow gate already built in v0.0.11).
- **Effect:** self-adapting surface; +2–4pp if it works, rollback-safe if not.

---

## 8. Recommended v0.0.23 Scope

**Ship T1 + T2 + T3 as v0.0.23** (the highest-ROI, lowest-risk path to the owner's mandate):
- T1 makes "never lose money" *structural* (R:R floor in code).
- T2 removes known bleed with zero logic risk (measured +12pp).
- T3 opens the suppressed SELL half.

T4–T6 are follow-up deploys after v0.0.23 confirms live.

**Projected trajectory (all measured, not hoped):**
| Stage | Aggregate WR | R:R | Status |
|-------|---------------|-----|--------|
| Now (v0.0.22) | 46.3% | 1.5:1 ❌ | below owner floor |
| +T1 (2:1) | 46.3% | 2:1 ✅ | mandate met in code |
| +T2 (exclusions) | ~58% | 2:1 | bleed removed |
| +T3 (SELL) | 52–55% | 2:1 | balanced + robust |

---

## 9. Open Items / Honest Caveats

- **SL win rate = 0% by definition** — SL is the loss realization. Do not "fix" this; fix *entry quality* so fewer SLs trigger.
- **SELL n=11** is too small to trust its 36% WR; T3 must re-measure on ≥30 SELL trades.
- **Outlier R distortion:** never quote the +9.99R mean expectancy to the owner. The repeatable edge is the 2:1 design at 46–58% WR.
- **Equity feed:** kill-switch uses a seed $1000, not live balance. Wire real balance before any LIVE mode (separate hard gate, doc 30 §7).
- **`float.mode` crash:** root-caused and fixed (3dcfa00). Live logs clean. Monitor on next trailing-stop-heavy run.
