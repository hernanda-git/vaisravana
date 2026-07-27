# Plan — v0.0.23: Honor the Owner Mandate (R:R ≥ 2:1 + De-bleed + SELL Balance)

> **Mandate:** "1 win recovers 2 losses is OK, but I don't want to lose money."
> → **R:R ≥ 2:1 (breakeven WR 33.3%) must be enforced in code.**
> → **Never lose money** → live WR must clear 33.3% with margin.
> All metrics below are from the live v0.0.22 DB (121 trades, 901 decisions).

## Why this version (root causes, measured)
1. **Active profile R:R = 1.5:1** (`sl=1.0, tp=1.5`) → below the 2:1 floor. Breakeven WR 40%; thin margin over live 46.3%.
2. **6 bleed pairs** (PEPE/WLD/INJ/TAO/WIF/PUMP) = 47 trades @ 27.7% WR. Dropping them → 58.1% WR, zero logic risk.
3. **SELL suppression:** 110 BUY vs 11 SELL (10:1). Engine favors BUY; SELL half of market untapped.

## Scope (v0.0.23 = T1+T2+T3 from review §7)
| T | Change | Risk | Measured lift |
|---|--------|------|---------------|
| **T1** | Enforce R:R ≥ 2:1 in config + validator | none | mandate in code; breakeven 40%→33.3% |
| **T2** | Auto-exclude pair if rolling WR<40% (≥10 trades); re-include >50% | none | +12pp (46%→58%) |
| **T3** | Per-side SELL offset + min 25% SELL share | low | opens suppressed half |

T4 (GATED short-circuit), T5 (TP/SL rebalance), T6 (Sentinel) = follow-up deploys.

## Execution Steps (TDD, commit per step, bump patch, push, deploy)

### Step 1 — T1: R:R floor (config.py)
- [ ] Change active profile: `tp_atr_mult = 2.0 * sl_atr_mult` (keep `sl_atr_mult=1.0` → tp=2.0).
- [ ] Add validator in `ParameterSurface`: reject if `tp_atr_mult / sl_atr_mult < 2.0` (HardFloorError).
- [ ] Test `tests/test_surface_floor.py`: (a) valid 2:1 passes; (b) 1.5:1 raises; (c) backtest expectancy positive at 46% WR, 2:1.
- [ ] Commit `feat(v0.0.23/T1): enforce R:R ≥ 2:1 — honor owner 2-loss recovery mandate`.

### Step 2 — T2: auto pair-exclusion (bot_paper.py + lifecycle)
- [ ] `pair_exclusions` dict persisted to `data/exclusions.json` (Fly volume).
- [ ] After each close: rolling WR per pair (last ≥10). If <40% → exclude + Telegram notify. If excluded & recovers >50% over next 10 → re-include + notify.
- [ ] `decide_tick`: skip excluded pairs (log SKIP_EXCL).
- [ ] Test `tests/test_pair_exclusion.py`: simulate PEPE-like bleed → excluded; recovery → re-included; json persists.
- [ ] Commit `feat(v0.0.23/T2): auto-exclude pairs with rolling WR<40% (data-driven, zero logic risk)`.

### Step 3 — T3: SELL un-suppression (scoring.py + gate)
- [ ] Per-side score offset: `sell_score_adj` so SELL isn't structurally < BUY.
- [ ] Enforce min SELL share ≥25% over trailing 40 entries; if below, lower SELL `entry_threshold` by 0.03.
- [ ] SELL-specific gate layer (marginal SELL blocked unless score ≥ BUY − 0.02).
- [ ] Test `tests/test_sell_balance.py`: 100 sim trades → SELL share ∈ [25%,50%]; SELL WR not degraded vs BUY.
- [ ] Commit `feat(v0.0.23/T3): un-suppress SELL — per-side offset + min 25% share`.

### Step 4 — Deploy v0.0.23
- [ ] Bump VERSION 0.0.22 → 0.0.23; add CHANGELOG entry.
- [ ] Full suite green (`pytest`).
- [ ] `git commit -am 'v0.0.23: R:R≥2:1 + pair de-bleed + SELL balance'`; `git push`; `flyctl deploy`.
- [ ] Verify live: startup card shows v0.0.23; DB snapshot after 30m → WR, SELL share, exclusions.

## Verification Gates (each must pass before next)
- [ ] T1 tests green + backtest expectancy > 0 at 46% WR / 2:1.
- [ ] T2 tests green + exclusion file round-trips.
- [ ] T3 tests green + SELL share in band, no WR degradation.
- [ ] Live: `decisions_log` shows SKIP_EXCL for bleed pairs; SELL entry count rises.

## Honest Caveats
- SELL n=11 too small to trust its 36% WR; re-measure after T3 on ≥30 SELL trades.
- Do NOT quote +9.99R mean expectancy (outlier artifact). Repeatable edge = 2:1 design at 46–58% WR.
- Kill-switch uses seed $1000, not live balance. Wire real balance before any LIVE mode.
