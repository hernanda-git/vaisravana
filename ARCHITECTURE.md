# VaiÅravaá¹a — System Architecture (Master Design)

> **This is the top-level design.** Every other doc (`docs/*.md`) is a detail of a box
> in this document. If you read only one file, read this. If something conflicts with
> another doc, **this architecture wins** — and the other doc must be fixed.

---

## 0. How to read this document

| Section | What it gives you |
|---------|-------------------|
| 1. Goals & non-negotiables | What the system MUST deliver |
| 2. Design principles | The rules that shaped every decision |
| 3. High-level architecture | The big picture (one diagram) |
| 4. Component map | The 10 components, what each does |
| 5. Multi-timeframe shadow engine | How 5/10/15m × all-pairs runs |
| 6. Win-rate +85% strategy | How the headline goal is engineered |
| 7. Two-bot loop | Trader ↔ Sentinel cycle |
| 8. Data flow | Event path, end to end |
| 9. Document map | Where every topic lives |
| 10. Consistency rules | Single source of truth (no drift) |

**Reader shortcut:** Human → read §1–§3, §6. Future-me (agent) → read all, then `30-concrete-spec.md`.

---

## 1. Goals & Non-Negotiables

| # | Goal | Non-negotiable? | Measure |
|---|------|-----------------|---------|
| G1 | **Time-sensitive accuracy** | YES | Decision→entry latency < 200ms; fill within 2s |
| G2 | **Stability** | YES | Max drawdown (unreal & live) < 3% |
| G3 | **High win rate (+85%)** | YES (target) | Per-pair/per-TF shadow WR ≥ 85% to promote to live |
| G4 | **Micro-timeframe trades** | YES | Trade windows: 5m, 10m, 15m |
| G5 | **All Binance pairs tradable** | YES (universe) | Universe = all USDT perpetuals (liquidity-filtered) |
| G6 | **Shadow-first** | YES | Zero live capital until gate passed on unreal |

> **Honest note on G3:** +85% is the *target gate*, not a guarantee. The architecture
> **measures and gates** on it (§6). If a pair/TF can't sustain 85% in shadow, it is
> pruned — we never force live capital into a sub-85% setup.

---

## 2. Design Principles

| P | Principle | Consequence in design |
|---|-----------|----------------------|
| P1 | **Stability > profit** | Small R:R accepted; tight SL; hard daily-loss cap |
| P2 | **Evidence, not indicators** | 9-engine confluence; single-pattern entries banned |
| P3 | **Shadow before live** | All win/loss recorded in unreal first (`30` §1) |
| P4 | **Bounded self-correction** | Sentinel edits only parameter surface (`21`), via shadow (`25`) |
| P5 | **Dynamic reasoning** | 5W1H engine (`29`) handles novel situations, not just fixed rules (`28`) |
| P6 | **Everything logged** | Every decision, fill, tp/close, health event persisted (`22`) |
| P7 | **Per-pair / per-TF isolation** | Each pair×TF validated and pruned independently |
| P8 | **Human-readable audit** | Every change documented automatically (`26`) |

---

## 3. High-Level Architecture

```
                         ┌─────────────────────────────┐
                         │      BINANCE  (all USDT)     │
                         │  WS klines × pair × TF      │
                         │  + orderflow / funding / OI │
                         └──────────────┬──────────────┘
                                        │ market data
                                        ▼
        ┌───────────────────────────────────────────────────────────┐
        │                    VAIÅRAVAá¹A-TRADER (active)                  │
        │                                                            │
        │  ┌────────────┐   ┌──────────────────────────────────┐    │
        │  │ MARKET DATA│   │  FEATURE/ENGINE LAYER (per pair)   │    │
        │  │  LAYER     │──▶│  9 engines → per-pair sub-scores   │    │
        │  │ (fan-out)  │   └──────────────────────────────────┘    │
        │  └────────────┘                 │                          │
        │                                  ▼                          │
        │  ┌─────────────────────────────────────────────────────┐  │
        │  │  MULTI-TIMEFRAME SHADOW ENGINE (5/10/15m × all pairs)│  │
        │  │  • each pair×TF = independent shadow trader          │  │
        │  │  • logs unreal win/loss (G6)                          │  │
        │  │  • gates on +85% WR before any live (G3)             │  │
        │  └─────────────────────────────────────────────────────┘  │
        │                                  │                          │
        │                                  ▼                          │
        │  ┌──────────────┐   ┌────────────────────┐  ┌───────────┐  │
        │  │ SCORING+DECIS│   │   RISK MANAGER      │  │ EXECUTION│  │
        │  └──────────────┘   └────────────────────┘  └───────────┘  │
        └──────────────┬──────────────────────────┬─────────────────┘
               telemetry│                          │ orders (PAPER/LIVE)
                        ▼                          ▼
              ┌──────────────────┐        ┌──────────────────┐
              │ TELEMETRY STORE   │        │    EXCHANGE      │
              │ (all events, §22) │        └──────────────────┘
              └────────┬──────────┘
                       │ read
                       ▼
        ┌──────────────────────────────────────────────────────────┐
        │              VAIÅRAVAá¹A-SENTINEL (correction)                  │
        │  EVALUATE (§23) → REASON 5W1H (§29) → REVIEW (§24)        │
        │   → CORRECT (shadow) → IMPROVE (promote) → DOCUMENT (§26)  │
        └───────────────────────────┬──────────────────────────────┘
                                     │ apply bounded param (§21/§25)
                                     └──────────▶ back to Trader
```

---

## 4. Component Map (10 boxes)

| # | Component | Responsibility | Doc |
|---|-----------|----------------|-----|
| C1 | Market Data Layer | Fan-out WS per pair×TF; gap/freeze detection; orderflow | `22`, `28-A/C` |
| C2 | Feature/Engine Layer | 9 engines → per-pair sub-scores (regime, structure, liq, candle, vol, volat, MTF) | `11`, `01`–`08` |
| C3 | Multi-TF Shadow Engine | Independent shadow trader per (pair×tf×side); records unreal WR per SIDE | `30` §3,`§5`,`§8` |
| C4 | Scoring & Decision | Aggregate → total score → entry/watch/skip with high threshold | `10`, `09` |
| C5 | Risk Manager | Per-pair sizing, global exposure cap, daily-loss kill switch | `11` §8, `25`, `30` §7 |
| C6 | Execution | LIMIT orders, fill tracking, reject/partial handling | `28-B`, `30` §3 |
| C7 | Telemetry Store | Persist every event (decision/fill/exit/health) | `22`, `30` §4 |
| C8 | Evaluation Engine | Auto-evaluate per (pair×tf×side): WR, expectancy, attribution | `23` |
| C9 | Reasoning Engine (5W1H) | Dynamic hypothesis (incl. novel H3) | `29` |
| C10 | Sentinel (Correction) | Review → correct → shadow → promote → document | `24`, `26`, `20` |

---

## 5. Multi-Timeframe Shadow Engine (G4 × G5)

The core scaling piece. It runs **shadow (unreal) trades on 5m, 10m, 15m windows across all Binance USDT pairs**.

### 5.1 Universe management
- Start from **all Binance USDT perpetuals**.
- Apply **liquidity filter** (not a hard 2-coin cap): drop pairs with avg spread > X bps or 24h vol < threshold. This keeps "all pairs available" while protecting stability (G2, G5).
- New pairs auto-enter the universe; delisted/expired pairs auto-exit (`28-D`).

### 5.2 Isolation model
```
for each pair P in universe:
  for each TF in {5m, 10m, 15m}:
     spawn ShadowTrader(P, TF)
        - independent state, scores, WR counter
        - logs every unreal trade to trade_logs (§22/§30)
        - promotes to LIVE only if WR ≥ 85% over N trades (§6)
```
- Each `ShadowTrader` is isolated: a bad pair/TF cannot contaminate others (P7).
- Sentinel can **disable** a single pair×TF without touching the rest.

### 5.3 Why 5/10/15m (not 1m)
- Less noise & spread-sensitivity than 1m → easier to hit stable high WR (G3, G4).
- Still "micro" enough for time-sensitive entries (G1).
- Three windows give regime diversity without over-fragmenting.

---

## 6. Win-Rate +85% Strategy (G3)

High win rate is **engineered**, not hoped for. The levers:

| Lever | Setting | Why it lifts WR |
|-------|---------|-----------------|
| Entry threshold | **0.90+** (vs 0.82 before) | Only A+ confluence entries |
| Regime gate | Trade only regimes with proven shadow WR ≥ 85% | Skip uncertain regimes |
| Multi-TF confluence | HTF bias + LTF trigger must agree | Filters false decisions |
| Liquidity + structure | Enter after sweep, at support/resistance | High-probability zones |
| Tight TP | Take profit at nearest logical target (R:R ~0.9–1.1) | Small wins accumulate; high hit rate |
| Tight SL | 1.0–1.2 ATR | Small loss when wrong |
| Per-pair shadow gate | Promote only if shadow WR ≥ 85% (N≥200 trades) | Live only proven setups |
| Continuous pruning | Sentinel disables pair×TF if WR drops < 85% | Maintain portfolio WR |

### Expectancy check
At 85% WR with R:R 1.0: expectancy ≈ 0.85×1R − 0.15×1R = **+0.70R per trade**.
Even R:R 0.8 → 0.85×0.8 − 0.15×1 = +0.53R. **Positive across a wide R:R band** — this is
why high WR is the chosen path to stability (P1).

### Measurement & gate (no fake claims)
- `Evaluation Engine` computes **per-pair×per-TF WR** continuously (`23`).
- `Promotion Gate` (§6 of `30`): live only after shadow WR ≥ 85% over ≥200 trades,
  expectancy > +0.2R, DD < 3%.
- If a live pair×TF falls below 85% WR for a validation window → Sentinel reverts it to
  shadow or disables it.

---

## 7. Two-Bot Loop (C10 ↔ Trader)

```
[every candle close on each pair×TF shadow]
   → engines → score → decisions_log
   → if ENTRY & checks pass → LIMIT order (PAPER) → trade_logs (open)
[on exit: TP/SL/trailing/maxhold]
   → trade_logs update → AUTO-EVALUATE (rolling)
[window: 200 trades / daily]
   → eval_report → Sentinel REASON(5W1H) → review → correct(shadow) → promote
[gate §6 passed + human approve]
   → LIVE enabled for that pair×TF (shadow keeps running as baseline)
```
Full detail: `27-feedback-loop.md`, `20-meta-system-overview.md`, `24-review-correction-bot.md`.

---

## 8. Data Flow (end to end)

```
Exchange WS ─▶ C1 Market Data ─▶ C2 Engines ─▶ C3 Shadow Engine
                                                    │
                                    every event ──▶ C7 Telemetry (persist)
                                    decision ──────▶ C4 Scoring
                                                    │ pass
                                                    ▼
                                    C5 Risk (size/SL) ─▶ C6 Execution (PAPER/LIVE)
                                                    │
                                    exit ─────────────▶ C7 Telemetry (pnl)
                                                     │
                                    rolling ─────────▶ C8 Evaluate ─▶ C9 Reason
                                                     │
                                    proposal ───────▶ C10 Sentinel ─▶ apply bounded
```

---

## 9. Document Map

| Topic | Primary doc |
|-------|-----------|
| Master architecture (this) | `ARCHITECTURE.md` |
| 8 trading layers (education) | `docs/01`–`docs/08` |
| Smart candle analysis / decision tree | `docs/09-smart-candle-analysis.md` |
| Scoring system | `docs/10-scoring-system.md` |
| 9-engine architecture | `docs/11-bot-architecture.md` |
| Two-bot overview | `docs/20-meta-system-overview.md` |
| Parameter surface (bounds) | `docs/21-active-bot.md` |
| Telemetry schema | `docs/22-telemetry.md` |
| Evaluation engine | `docs/23-evaluation-engine.md` |
| Sentinel (reason/review/correct) | `docs/24-review-correction-bot.md` |
| Safety / shadow / rollback | `docs/25-safety-shadow-rollback.md` |
| Auto documentation output | `docs/26-documentation-output.md` |
| Feedback loop | `docs/27-feedback-loop.md` |
| Blind spots | `docs/28-unexpected-factors.md` |
| Dynamic reasoning 5W1H | `docs/29-dynamic-reasoning-5w1h.md` |
| **Concrete spec (this architecture's instance)** | `docs/30-concrete-spec.md` |
| Glossary / cross-ref / open Qs | `docs/31-glossary.md` |

---

## 10. Consistency Rules (single source of truth)

1. **`ARCHITECTURE.md` wins** on any conflict.
2. **`docs/30-concrete-spec.md`** is the authoritative *values* (defaults, bounds, schema).
3. **`docs/21-active-bot.md`** is the authoritative *parameter bounds*.
4. All examples in `23/24/26` MUST match `30`/`21` values (no stale `0.80`/`3.0`/`lev 5`).
5. Default mode is **PAPER/unreal** unless gate (`30` §6) passed.
6. Win-rate gate is **85%** per (pair, tf, SIDE) — LONG and SHORT gated independently — in shadow before live.
7. Any doc edit that changes a value must propagate to dependents (see §9 map).

---
▶ Implement from: `ARCHITECTURE.md` → `docs/30-concrete-spec.md` → `docs/22` schema → `docs/23` evaluator → loop (`27`).
