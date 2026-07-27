# Vaiśravaṇa — Trading Performance Evaluation

**Date:** 2026-07-26 · **Mode:** PAPER (Binance USDT-M futures, sim fill) · **Version evaluated:** v0.1.5–v0.1.7 live
**Sample:** 60 closed trades pulled from the live Fly DB (`/data/vaisravana.db`) after the v0.1.6 fresh start.
Live DB path on Fly: `/data/vaisravana.db`, machine `78475e3ce4dd58` (sin).

---

## 1. Headline — the win rate IS terrible

| Metric | Value |
|---|---|
| Closed trades | 60 |
| Win rate | **36.7%** |
| Expectancy | **−1.751 R / trade** |
| Net PnL (paper) | **−$226.86** |
| Open positions at snapshot | 0 (bot stopped) |

Below break-even. At R:R ≥ 1.5 the break-even WR is ~48%, so 36.7% is structurally unprofitable.

---

## 2. Breakdown — the bleed is entirely directional

| Side | Trades | WR | Exp(R) |
|---|---|---|---|
| **BUY** | 38 | **23.7%** | **−8.781** |
| SELL | 22 | 59.1% | **+7.030** |

The bot trades both sides on the *same* score threshold, but the market has been in a
downtrend, so **every long is fighting the trend** while shorts ride it. SELL is already a
profitable strategy (+59% WR); BUY is the entire problem.

| Decision TF | Trades | WR | Exp(R) |
|---|---|---|---|
| 15m ("Day") | 17 | 23.5% | −2.265 |
| 1h ("Swing") | 16 | 37.5% | −0.210 |
| 1m ("Scalp") | 27 | 44.4% | +0.724 |

The 15m Day strategy is the worst performer — it holds longer and gets stopped in the trend.

### By pair (expectancy, worst → best)

| Pair | n | WR | Exp(R) |
|---|---|---|---|
| 1000BONKUSDT | 3 | 0% | −1.719 |
| ETHUSDT | 3 | 0% | −1.633 |
| SOLUSDT | 3 | 0% | −1.574 |
| BTCUSDT | 5 | 20% | −1.215 |
| WLDUSDT | 3 | 0% | −1.210 |
| TAOUSDT | 5 | 20% | −1.026 |
| 1000PEPEUSDT | 1 | 0% | −0.290 |
| PUMPUSDT | 2 | 0% | −0.124 |
| WIFUSDT | 9 | 22% | +0.724 |
| PENGUUSDT | 2 | 50% | +0.336 |
| INJUSDT | 8 | 63% | +0.086 |
| APEUSDT | 6 | 50% | +1.223 |
| CRVUSDT | 4 | 75% | +1.236 |
| AAVEUSDT | 3 | 100% | +1.619 |
| ENAUSDT | 3 | 100% | +1.816 |

The majors (BTC/ETH/SOL) and the high-beta alts (BONK/PEPE/WLD) are 0% WR. The few
profitable pairs (AAVE/ENA/CRV/APE) are small-sample but consistently +EV.

---

## 3. Exit-quality — the stop-loss is broken

| Close reason | Trades | Wins |
|---|---|---|
| MAXHOLD (time exit) | 39 | 14 (36%) |
| SL (stop hit) | 13 | **0 (0%)** |
| TP (target hit) | 8 | 8 (100%) |

**Every single stop-loss is a loss.** With R:R 1.5 a trade only needs >40% TP wins to be
profitable, but TP fires only 8 times while SL fires 13 times — meaning entries are filled
at bad prices (chasing extremes) and the market reverses through the stop before reaching
target. The MAXHOLD exit is a coin-flip (36% win), so the "let it run to time limit"
default is just bleeding.

---

## 4. Root-cause analysis

1. **Directional asymmetry not handled.** `evaluate_strategy` scores BUY and SELL
   identically. In a downtrend, symmetrical scoring → BUY bleeds. The v0.1.6 side-gate
   only *suppresses* a side AFTER it has already lost 20 trades (floor −0.05R); it does
   not *prevent* blind BUY entry on a fresh/neutral side. Net: BUY traded 38 times at
   23.7% before the gate could engage.
2. **No regime filter on entry.** Entries ignore `htf_bias` / `btc_bias` / `risk_regime`.
   A BUY in a bearish regime is doomed; the bot takes it anyway.
3. **Entries chase extremes.** `SL = 0% win` means fills are at swing highs/lows, then
   mean-revert through the stop. No pullback-to-anchor confirmation on entry.
4. **MAXHOLD is a losing default.** 39 trades exited on time, only 36% winners — the
   time-stop is too long / has no trailing capture for winners.

---

## 5. Improvement plan (v0.1.8)

Target: lift portfolio WR toward the 56% floor and turn expectancy positive — **without**
an arbitrary 85% gate (rejected earlier; it produced ~0 trades). All changes are
expectancy-first and TDD-guarded.

| # | Change | Attacks | Expected effect |
|---|---|---|---|
| A | **Directional entry gate**: BUY only when regime bullish (`htf_bias`/`btc_bias` > 0); SELL only when bearish. | Root cause #1, #2 | Kills blind BUY-into-downtrend; aligns entries with trend. Portfolio WR should jump toward SELL's 59%. |
| B | **Stronger side-expectancy gate**: a side trades only if proven +EV (≥10 samples, expR > 0) OR direction-aligned & unproven. Unproven BUY in flat regime → SKIP. | #1 | Stops blind BUY from the first trade; no more 20-trade bleed-in. |
| C | **Pullback-entry confirmation**: require `pullback_to_anchor` true for ENTRY (no chasing extremes). | #3 | Fewer SL hits; more TP fills → higher WR. |
| D | **Tighten MAXHOLD + winner trail**: shorter time-stop; trail winners so TP fires more often. | #4 | Converts MAXHOLD from coin-flip to net-positive. |

A + B + C alone should flip the portfolio from −1.75R to roughly SELL-only behaviour
(+7R historical), because SELL is already +59% WR and BUY will only trade in confirmed
uptrends. D is a secondary WR lift.

**Guardrails (non-negotiable):**
- PAPER-only. No live path touched.
- Promotion gate (human approval) unchanged.
- Every change has a TDD test proving the gate fires and the bot still trades the
  profitable side.
- Backtest harness (`scripts/verify_activity.py`) re-run to confirm net expectancy
  improves on a mean-reverting + trending series.

---

## 6. Comprehensive review notes

- The bot is **resilient and observable**: auto-pruned `decisions_log`, `/clean` `/stop`
  `/health` commands, caretaker cron (paused during this work). Good operational hygiene.
- **decisions_log was empty** before v0.1.7 (the multi-strategy rewrite bypassed the
  single-strategy persist). Now persisted — needed for this evaluation to be possible.
- **Caretaker autonomy caused corruption**: it edited `bot_paper.py` concurrently with
  manual work, leaving undefined functions + a syntax error. Lesson: the caretaker must
  not edit the same files mid-session; it is paused. Future: caretaker operates on a
  branch / PR, not the live tree.
- **Win rate is a floor, not a target.** 56% is the promotion floor; expectancy > +0.10R
  and PF > 1.2 are the real gates. Chasing WR alone is a trap (the old 85% gate proved it).

---

*Generated by the owner-requested full evaluation (2026-07-26). Bot stopped; improvements
in v0.1.8 (see CHANGELOG).*
