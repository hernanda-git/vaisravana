# Vaisravana — Robustness & Stability Plan

**Companion to:** `docs/REVIEW-ROBUSTNESS-2026-07-27.md`
**Principle:** every phase TDD-first, version-bumped, committed, **pushed but NOT
auto-deployed unless explicitly approved**. Human-gated deploy per phase.
**Sequencing:** P0 (correctness/robustness, zero model risk) → P1 (validity
before live) → P2 (adaptiveness + closed meta-loop). No live capital until P1 passes.

---

## P0 — Correctness & robustness (no model risk)

### Phase 30 — Lock the R:R floor (regression test)
- **Goal:** make a sub-2:1 live open position *impossible to ship*.
- **Work:**
  - Add boot-time scan: assert **no open `trade_logs` row has R:R < floor**; if
    found, alert + refuse to trade that pair until repaired.
  - `test_phase30_rr_floor_lock`: synthesize an open trade at R:R 1.5 → scan fails.
  - Optional: tighten `ParameterSurface` validator to reject TP mult < 2.0 at
    *construction* (defense in depth over Gate-B).
- **Success:** test green; a sub-2:1 entry can never reach "open" state undetected.

### Phase 31 — Re-base evaluation on net pnl% / expectancy$ (fix F1)
- **Goal:** ranking & de-bleed stop trusting distorted `avg_R`.
- **Work:**
  - Add `expectancy_usd` (net of fees) + `net_pnl_pct` to `evaluation.py` and
    `trade_logs` (backfill from `pnl_pct` minus `fees_usd/denom`).
  - `PairExcluder` (T2) ranks on **net expectancy$** (or net pnl%), not R.
  - `evaluation.evaluate()` returns both R and net$; dashboard shows net$.
  - `test_phase31_net_expectancy`: PEPE must rank BELOW its R suggests; de-bleed
    keyed to net$ drops PEPE/WIF correctly.
- **Success:** pair ranking correlates with real $ expectancy; de-bleed no longer
  fooled by tight-SL R inflation.

### Phase 32 — SELL maturity gate (fix F3)
- **Goal:** never conclude or act on SELL until statistically mature.
- **Work:**
  - `SideMaturity`: BUY/SELL tracked separately; a side is "mature" at
    `min_trades` (default 50) AND Wilson CI width < bound.
  - Immature SELL: excluded from promotion math, labeled "IMMATURE" in dashboard,
    does **not** trigger pair exclusion or surface mutation.
  - `test_phase32_side_maturity`: with 12 SELL trades → immature; SideBalancer may
    still enter but Sentinel won't promote on it.
- **Success:** SELL cannot drive a wrong promotion/exclusion until sampled.

---

## P1 — Validity before live capital

### Phase 33 — Walk-forward backtest harness (fix F2 exposure)
- **Goal:** out-of-sample proof, not in-sample optimism.
- **Work:**
  - Time-series CV: rolling train/test split by date (e.g. 60d train / 20d test,
    step). Report **out-of-sample** WR, net expectancy$, max DD, per-regime.
  - Fees already modeled (`backtest.py`); add slippage jitter param.
  - Emit `OOS_REPORT` table; `scripts/run_backtest_walkforward.py`.
  - `test_phase33_walkforward`: deterministic split on seeded data → stable OOS stats.
- **Success:** OOS net expectancy$ > 0 across ≥2 non-overlapping windows.

### Phase 34 — Statistical promotion gate (fix F4)
- **Goal:** Sentinel may only promote when significance holds.
- **Work:**
  - Replace "WR>=X" with **Wilson lower-bound CI** on WR and on net expectancy$.
  - Promotion requires: `n_side >= min_trades` AND `WR_CI_low > break_even` AND
    OOS net$ > 0.
  - `sentinel.promotion_gate()` enforces; `results_log` records CI + n.
  - `test_phase34_promotion_ci`: low-n / wide-CI proposal is rejected; mature
    proposal accepted.
- **Success:** noise promotions blocked; every promotion is statistically defensible.

---

## P2 — Adaptiveness & closed meta-loop

### Phase 35 — Regime-conditioned sizing / vol targeting (fix F2)
- **Goal:** survive chop; size by risk, not fixed notional.
- **Work:**
  - `Sizer`: scale size by ATR-regime + ADX (trend strength); bounded
    [min,max] notional; reversible via Sentinel.
  - Protect break-even: ensure net expectancy$ stays >0 at chosen sizes.
  - `test_phase35_sizing`: chop regime → smaller size; trend → larger (capped).
- **Success:** drawdown in chop regimes reduced vs fixed sizing (OOS).

### Phase 36 — Close the self-improving loop (fix F5)
- **Goal:** make "self-improving" real, safely.
- **Work:**
  - Sentinel: propose bounded param diff → apply in **shadow** → compare composite
    health → **auto-revert** on regression (bounded diff, no human round-trip).
  - `results_log` becomes the loop trail (proposal → shadow Δ → promote/revert).
  - LLM optional, **off by default**; if on, only summarizes, never sets params.
  - `test_phase36_self_loop`: bad diff auto-reverts; good diff promotes; loop trail
    recorded.
- **Success:** params evolve under guardrails; no human-in-loop needed for revert.

### Phase 37 — Live cutover gate (human-gated)
- **Goal:** only go live after P1 passes on OOS.
- **Work:** `orchestrator.safety.promotion_gate()` + explicit human approval
  (Telegram `/go-live`). PAPER→LIVE switch is a single config flag behind approval.
- **Success:** live capital only after OOS + CI gates green.

---

## Phase ↔ test map
| Phase | Test file | Risk |
|---|---|---|
| 30 R:R lock | `test_phase30_rr_floor_lock` | none |
| 31 net expectancy | `test_phase31_net_expectancy` | low |
| 32 SELL maturity | `test_phase32_side_maturity` | none |
| 33 walk-forward | `test_phase33_walkforward` | none |
| 34 promo CI | `test_phase34_promotion_ci` | low |
| 35 sizing | `test_phase35_sizing` | med |
| 36 self-loop | `test_phase36_self_loop` | med |
| 37 cutover | `test_phase37_cutover` | n/a (human) |

## Execution order
1. P0-30 → P0-31 → P0-32 (ship as v0.0.24 block; push, no deploy unless asked).
2. P1-33 → P1-34 (OOS proof; this is the gate for any live talk).
3. P2-35 → P2-36 → P2-37 (adaptiveness + real loop + human cutover).

Each phase: branch → TDD → commit → push → (optional) deploy after your approval.
