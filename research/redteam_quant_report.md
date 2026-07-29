# Red-Team Report: $10 USDT-Perp Paper Scalper (v0.0.34)

*Ruthless quant PM review. All numbers derived from the run-1 evidence and stated parameters.*

---

## 0. The math this account must beat (read this first)

- **Fee floor:** 0.06% round trip. EV gate forces 1R ≥ 0.24% move, so **fees = 0.25R per trade, win or lose.**
- **Sizing:** notional clamp 2× equity → ~$20 max. 1R ≈ 0.24% × $20 = **$0.048**. Fee/trade ≈ $0.012.
- **Run-1 realized edge (SELL side, the good half):** +$6.92 net / 71 trades at implied avg notional ~$132 (fees $8.40/106 = $0.079/trade ÷ 0.06%). That's **+0.073% of notional net per trade** (~+0.30R net). Real, but thin.
- **Translated to post-fix sizing:** 2× leverage × 0.073% = **+0.146% equity per trade** ≈ **$0.015/trade** on $10.
- **Growth requirement:** to double in 30 days you need ~2.3%/day → **~15 trades/day of SELL-bucket quality**. To double in 90 days, ~5/day.
- **Observed post-fix frequency: 0 trades/hour.** Growth rate = edge × frequency. Anything × 0 = 0. The account cannot grow; it can only sit flat or bleed on the occasional pass-through loser.

**Verdict:** the edge (bear-regime SELLs, ~+0.3R net) is *mathematically sufficient* to compound a $10 account at meaningful rates — **if and only if** it fires 10–30×/day. The v0.0.34 gate stack has driven realized frequency to ~zero and simultaneously points the exit logic at the wrong target. As configured: expected path is flatline.

---

## 1. Top 5 reasons it will STILL fail post-fix

**1. Frequency strangulation by hard-AND gate stacking (the #1 killer).**
In the 1h sample: 53 blocked by per-side threshold, ~50 by ADX, 28 by top-chase, 5h/day session-blocked, 30min/pair spacing, 4/h global cap, loss-streak cooldowns. These are *multiplicative* filters — empirical pass rate <1%. The 4/h cap alone is damning: the **only profitable bucket in run 1 (trending_bear SELL) ran at ~4.5 trades/hour by itself** (45 trades/10h). Your cap would have clipped the winner. You've built a machine whose best-case throughput is below its own break-even frequency.

**2. Exit stack is calibrated to a fantasy and the new BE-trail attacks the real profit engine.**
TP at 2.44R produced **$0.05 total**. MAXHOLD time-exits produced **$8.03** — that's the entire edge. Realized winners are ~0.3–0.7R grinds, not 2.44R runners. Given fees = 0.25R, if avg realized win ≈ 0.6R and avg loss ≈ 1R, **break-even WR ≈ 78%** — impossible. Worse: the new BE-trail at +0.5R will scratch exactly the oscillating 1m paths that used to mature into MAXHOLD winners, converting the +$8.03 bucket into a −0.25R-per-scratch fee bleeder. This "fix" is untested and aimed at your only proven profit source.

**3. BUY side is still enabled.**
25% WR, −$7.04 over 36 trades — a proven money furnace. The top-chase guard is a band-aid; the 4-way HTF alignment gate *will* still pass "everything-agrees-bull" BUYs, and run-1 evidence says those are precisely the trades that lose (alignment on 1m lags → you buy exhaustion). Every BUY that passes is negative-expectancy inventory.

**4. Per-trade P&L is at fee/granularity noise level.**
$20 notional × 0.073% net edge = **$0.015/trade**. Meanwhile every downstream module (pair excluder by rolling expectancy, per-side threshold adjustment, side-bleed suppression) is estimating expectancy from cents-scale P&L over tiny samples (n<10 per pair given 30min spacing). These adaptive layers are **fitting noise** and will randomly exclude good pairs / suppress the good side after 2–3 coin-flip losses. Self-inflicted regime instability.

**5. Regime dependence with no regime router + crippled universe.**
The entire edge lives in `trending_bear + SELL`. In bull/chop weeks the bot has *no* proven positive bucket — it either idles (gates) or bleeds (BUYs, chop SELLs). Meanwhile 3 of 15 pairs (BTC/AAVE/TAO) are structurally untradeable at $10, and nothing reallocates that capacity. You have a one-regime strategy running 24/5 pretending to be all-weather, minus the hours (00–05 UTC) when bear moves often actually happen — a filter that appears unmeasured (no per-session P&L cited).

---

## 2. Over-filtering analysis: which gates destroy more edge than they protect

| Gate | Verdict | Evidence / reasoning |
|---|---|---|
| **ADX≥25 hard gate (1m)** | 🔴 **Destroys edge.** | Blocks ~50 signals/h. 1m ADX is noise + lag; it selects *late* trend (which top-chase then blocks — the gates fight each other: ADX demands established trend, top-chase demands pullback, intersection ≈ ∅). Trend quality is already a weighted sub-score AND in the threshold. Triple taxation. |
| **Global 4 entries/hour cap** | 🔴 **Destroys edge.** | The winning bucket alone ran 4.5/h in run 1. This caps your winner, not your loser (losers were BUYs, a *side* problem, not a *rate* problem). |
| **4-way HTF alignment (pair HTF + higher TF + BTC + risk regime)** | 🔴 **Mostly destroys.** | AND of 4 lagging conditions on a 1m strategy → entries at exhaustion (explains 25% BUY WR at tops) and late/blocked SELLs at regime turns, exactly when trending_bear edge is richest. |
| **Session filter 00–05 UTC** | 🟠 **Probably destroys.** | 21% of hours removed with no cited per-session P&L. For a frequency-starved bot, unmeasured hour-blocking is pure throughput loss. |
| **Per-side threshold adj + side-bleed suppression** | 🟠 **Redundant/noisy.** | 53 blocks/h stacked on top of ADX+HTF+base threshold; adaptive on cents-scale samples → noise-fitting. The side problem needs one deterministic rule (see §3.1), not three adaptive ones. |
| **Pair excluder (rolling expectancy)** | 🟠 **Noisy at this scale.** | n per pair is tiny (30min spacing); will exclude good pairs on variance. |
| **BE-trail +0.5R** | 🔴 **Actively harmful (new).** | Directly cannibalizes the MAXHOLD profit engine (+$8.03). See §1.2. |
| **Top-chase BUY guard** | 🟢 **Protects.** | 28 blocks/h on a side with 25% WR — statistically excellent. (Better still: don't BUY at all.) |
| **Fee-EV gate, spread gate 5bps, big-candle skip, notional clamp, loss-streak cooldown** | 🟢 **Keep.** | Cheap, correct, evidence-neutral. Clamp is the actual fix for the run-1 blowup. |

**Structural point:** hard-AND stacking of correlated filters has multiplicative pass rates. Institute a rule: **no single gate may block >30% of otherwise-valid signals**; audit per-gate block counts weekly and demote violators from hard gate → score penalty.

---

## 3. Top 5 highest-EV changes, ranked (all parameter-level or additive; no engine rewrite)

**1. Kill the BUY side (parameter).** Set BUY entry threshold to 0.99 (or side=SELL_ONLY) except when regime = confirmed trending_bull *with* pullback. Run-1 counterfactual: removes −$7.04, keeps +$6.92 — swings 10h net from ~$0 to +$7 (at run-1 sizing) with **one config line**. Largest, most evidence-backed EV change available. Retire side-bleed suppression and per-side adaptive thresholds; this rule replaces them deterministically.

**2. Recalibrate exits to realized MFE (parameters).** TP 2.44R → **~1.2R**, then re-fit weekly to p60–p70 of the freshly recorded `mfe_r`. Move BE-trail arm from +0.5R → **+1.0R** (or disable until mfe/mae data proves it). Keep 45m max-hold — it's the proven exit. This drops required break-even WR from ~78% (current realized structure) to ~48–52%; SELL side already runs 56%.

**3. Un-strangle frequency (parameters).** Global cap 4→**10/h**; per-pair spacing 30→**15min**; ADX hard gate → drop to 15 or demote to a score weight; session filter **off for SELLs** (re-enable only if per-session stats prove negative). Target: **15–30 trades/day**. Without this, changes 1–2 compound nothing — the math in §0 requires ~15/day for meaningful growth.

**4. Additive regime router module.** One small module upstream of sizing: `trending_bear` → full risk, threshold −0.04, cap 10/h; `trending_bull` → SELL off, tiny probe BUYs only; `chop/uncertain` → half size or stand down. Concentrates capital in the one proven bucket, keeps cheap "exploration" flow elsewhere for data. This is how a one-regime edge survives as a live book.

**5. Universe + sizing hygiene (parameters).** Delist any pair with min-notional > 1.5× equity (BTC/AAVE/TAO out; replace with liquid low-priced alts). Raise notional clamp 2×→**3× equity for the proven bucket only** (risk/trade ≈ 3 × 0.3% ≈ 0.9% equity — sane, and lifts per-trade P&L above fee/cent granularity to ~$0.022+). Pair excluder: require **n≥20 trades over ≥3 days** before exclusion.

**Projected post-change math:** 15 SELL-bucket trades/day × +0.22% equity/trade (3× lev × 0.073%) ≈ **+3.3%/day in bear regimes**, flat in others → doubling plausible in 1–2 favorable months. Without changes 1–3, projected growth: **~$0/day, forever.**

---

## 4. One-line verdict

The blowup is fixed but the business model isn't: v0.0.34 is a fee-aware, well-clamped machine for doing **nothing**, whose only proven profit engine (bear-regime SELLs exiting on time-stops) is simultaneously rate-capped by the 4/h limit, gated out by ADX/HTF stacking, and about to be scratched to death by the new BE-trail. Flip to SELL-only, aim the TP at reality (~1.2R), and triple the throughput — or accept that $10 stays $10.

---

**Summary of subagent work:** Pure analysis task — no repo inspection required or referenced. Derived per-trade economics from the provided run data (avg notional ~$132 implied by fee totals; SELL edge ≈ +0.073% of notional net ≈ +0.30R), computed break-even WR under the realized exit distribution (~78% — fatal), quantified the frequency requirement for compounding (~15 trades/day), and produced the ranked report above. No files created; no issues encountered.