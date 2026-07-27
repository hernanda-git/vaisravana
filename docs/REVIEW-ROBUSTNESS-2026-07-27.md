# Vaisravana — Robustness & Stability Review (2026-07-27)

**Scope:** end-to-end pipeline audit — data → decision → gate → execution →
lifecycle → evaluation → sentinel. Honest read, grounded in source + live DB.
**Mode:** read-only review. No code changed, no deploy.

**Live state at review time:** `v0.0.23`, Fly `sin`, 25 open positions, 157 closed
trades, ~988 decisions/hr. PAPER mode.

---

## 0. Self-corrections (claims walked back after reading code/DB)

| Earlier claim | Reality (verified) |
|---|---|
| "Expectancy negative, R:R 0.89:1" | `win_pct`/`loss_pct` store **rolling win-rate %**, not return. Real expectancy (pnl%/R) is **positive** — 157 closed, avg pnl% +0.052, sum R +1235. |
| "Backtest is fee-blind" | `src/backtest.py` models maker 0.02% (entry/TP) + taker 0.05% (SL/MAXHOLD). Fees are modeled. |
| "SELL side is broken" | SELL only went live **2026-07-27 04:42 UTC** (~12 trades, <3h). It is **immature/under-sampled**, not confirmed broken. |
| "BTC 1m 1.50:1 = live Gate-B hole" | That open trade has since **closed**; current open book is 2.0–2.86 R:R. No standing violation — but the class of bug (sub-2:1 entry) must be regression-locked (see Plan P0-1). |

---

## 1. What is genuinely solid (do not touch)

- **Two-layer safety gate is real, not cosmetic.** `gate.py`: Gate A (idempotency,
  cooldown, liquidity whitelist, spread<5bps, daily-loss) pre-score; Gate B
  (leverage≤2, SL-direction-must-match-side, daily-loss cap) post-score **hard
  clamp**. Sentinel is structurally barred from touching Gate B (`doc 24` guardrail).
- **Full audit trail.** `trade_logs` / `decisions_log` / `results_log` /
  `exec_events` / `system_health`. Per-trade pnl%, R-multiple, close_reason,
  hold_min, MFE/MAE all recorded (`lifecycle.py`).
- **TDD discipline.** ~10.9k LOC, 29 phase test files; every shipped fix was
  TDD'd against the live DB, version-bumped, deployed, and re-verified.
- **Correct controls already in:** R:R≥2:1 floor, pair de-bleed (T2), side-balance
  (T3), HTF direction gate (v0.0.20), ADX/vol-adaptive SL (v0.0.19).
- **Backtest models fees** (see §0).

## 2. Real fragilities (honest)

### F1 — R:R ranking is scale-distorted → bad de-bleed signal
`avg_R` divides by SL distance. Tight-SL pairs inflate R without better pnl:
- `1000PEPEUSDT`: avg_R **+9.99** but avg_pnl% **−0.185**
- `WIFUSDT`: avg_R +12.77 but avg_pnl% +0.002

Pair de-bleed (T2) and ranking score on `avg_R` → they rank on a **distorted**
number. **Fix: rank/exclude on net pnl% or expectancy$ (net of fees), not raw R.**

### F2 — Profit is tail-dependent
`APEUSDT` +25R, `WIFUSDT` +13R carry the book. Winners run via trailing/structure
exits far beyond the 2:1 TP. In a range/chop regime the trend machinery bleeds;
HTF gate helps but there is **no regime-conditioned sizing** yet.

### F3 — SELL is too young to judge
12 trades, live <3h. Do **not** conclude "SELL broken" or "SELL works" yet.
Risk: SideBalancer/T2 could over-react to noise. Dashboard must label SELL
**"immature (n<50)"** and exclude it from promotion/exclusion math until maturity.

### F4 — No statistical significance gate before promotion
`sentinel.py` promotes when "composite health rises" — but **no min-trades + CI
floor**. At 157 trades concentrated in a few pairs/recent regime, WR 47% has a
wide CI. A promotion on noise can slip through.

### F5 — "Self-improving" is aspirational
LLM is **off**. `results_log` is a log, not a mutation loop. Sentinel does propose
bounded diffs (`sentinel.py` propose/promote), but the meta-loop does not yet
*mutate parameters and auto-revert on regression* end-to-end. Be honest about this.

### F6 — Gate-B not regression-locked
No test asserts "no live open trade can have R:R < 2:1". The transient 1.50:1
entry proved the class is possible. Lock it (P0-1).

## 3. Live numbers (measured 2026-07-27)

```
closed=157  WR=47.0% (62W/70L)  avg_pnl%=+0.052  sum_pnl%=+8.18  sum_R=+1235
BUY  avg_R=+8.39 (n=145)
SELL avg_R=+1.49 (n=12, immature)
Per-pair expectancy$ (>=10 closed):
  APEUSDT  n=21  avg_R=+25.41  avg_pnl%=+0.367
  WIFUSDT  n=16  avg_R=+12.77  avg_pnl%=+0.002
  1000PEPE n=20  avg_R=+9.99   avg_pnl%=-0.185   <-- distorted R
  PENGUUSDT n=13 avg_R=+6.17   avg_pnl%=+0.056
  AAVEUSDT n=11  avg_R=+4.85   avg_pnl%=+0.197
  ETHUSDT  n=14  avg_R=+4.72   avg_pnl%=+0.086
  BTCUSDT  n=12  avg_R=+0.57   avg_pnl%=+0.032
Open book: 25 positions, R:R 2.0–2.86 (clean), 1 SELL (INJ).
exclusions.json: live, tracking per-pair W/L (T2 working).
```

## 4. Verdict

Well-engineered, currently **positive in PAPER**, fee-aware, safety-first. But:
**tail-dependent**, **SELL-immature**, **R-distorted ranking**, **no significance
gate**, **meta-loop not closed**. It is a *clever paper bot*, not yet a *robust
system for live capital*. The P0 items below are the gap.

See `docs/PLAN-ROBUSTNESS.md` for the execution plan (phased, TDD, reversible).
