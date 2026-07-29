# MAIN BOT LEARNING LOG (vaisravana main, paper $10 survival runs)

Improvement loop for the MAIN bot (`scripts/bot_paper.py`, @vaisravana_bot).
Method per iteration: measure (DB evidence) -> hypothesize -> change (additive
gates / ParameterSurface only, engine untouched) -> deploy -> observe -> verdict
KEEP or REJECT with evidence. Sibling of WAVE_LEARNING_LOG.md (wave engine).

Goal: **a growing balance**, not activity. Paper: $10 start, maker 0.02% open,
taker 0.04% close, runs until $0.

---

## Run 1 — 2026-07-28, v0.0.33 (baseline, FAILED: $10 -> $1.49 in ~10h)

Evidence (DB, 106 closed trades):
- WR 45% (48W/58L), gross ~breakeven, **fees $8.40 = the whole loss**
- Sizing scale bug: equity read from env default **$1000**, not live $10
  -> ETHUSDT 0.5 ETH = $956 notional on a $10 account; one SL = **-$6.22**;
  ETH alone paid $7.65 of the $8.40 fees. Meanwhile BONK/PEPE/PENGU entries
  were $0.00-$0.01 dust blocking position slots.
- Side asymmetry: SELL 71 trades WR 56% **+$6.92**; BUY 36 trades WR 25%
  **-$7.04**; worst bucket trending_bull+BUY -$6.47 (top-chasing).
- Exit mix: MAXHOLD exits +$8.03 (64 trades) vs TP exits +$0.05 (9 trades).
  TP at avg 2.44R was statistically unreachable inside a 15min 1m max-hold.
- Instrumentation lies: mfe_r/mae_r NULL on all 112 rows; spread_bps
  hardcoded 1.0.

Verdict: the account was killed by (1) broken sizing, (2) fee bleed from
churn, (3) BUY-side top-chasing. The signal core itself was ~breakeven gross
and clearly positive on SELL-in-bear.

## Iter 1 — v0.0.34 survival-mode risk layer (commit d25d269)

Changes (all additive, env-tunable):
1. Live equity from paper_stats() every cycle (kills the $1000 ghost).
2. survival_gates(): notional clamp 2x live equity, $5 min notional floor;
   fee-aware EV gates (round-trip fee <= 25% of 1R; TP move >= 0.24%);
   hourly throttle 4 entries/h global + 30min per-pair spacing; session
   filter 00-05 UTC; loss-streak cooldown (3 losses -> 30min); big-candle
   skip (bar range > 3x ATR).
3. Maker/taker fee model: post-only LIMIT open 0.02% + taker close 0.04%
   (was 2x taker) -> ~25% round-trip fee cut.
4. Instrumentation: mfe_r/mae_r recorded via EXCURSIONS tracker; real
   book-ticker spread_bps + 5bps spread gate (was hardcoded 1.0).
5. TP reachability: 1m max-hold 15 -> 45min; BE-trail at +0.5R bounds risk.
6. Top-chase guard: trending_bull BUY requires pullback (bar close below
   short EMA or mid-bar) — targets the -$6.47 bucket directly.

Deploy: fresh DB wipe (143 trades purged), $10 restart 2026-07-29 04:16 UTC.

Verified live in first hour: session filter held all entries in the 04-05
UTC dead window (95+ vetoes); top-chase guard blocked 28 BUYs in a bull
tape; margin cap structurally excludes BTC/AAVE/TAO on a $10 account
(min-notional > 50% margin cap) — correct behavior, universe is effectively
the cheap/mid pairs.

## Iter 2 — v0.0.34b veto-note dedup (commit ec519e2)

Problem: repetitive vetoes wrote one GATED row per pair per tick ->
20k stale decisions_log rows, log spam. Fix: _veto_should_note() records
each (pair, veto-class) at most once/hour. Verified: 3 session rows/2.5min
-> vs ~25 before. decisions_log stays purged daily (+VACUUM) by design.

## Run 2 — started 2026-07-29 04:16 UTC, v0.0.34b (IN PROGRESS)

Baseline to beat: survive longer than 10h AND end above $10.
Watch items for the next verdict:
- Do entries flow at 06:00+ UTC at a sane pace (<=4/h)?
- Are notionals $5-20 with correct 5% SL risk?
- Does mfe_r/mae_r data land in trade_logs? (feeds TP tuning next iter)
- Does the SELL-side edge persist at correct size?
- Is BUY still bleeding after the top-chase guard?

## Iter 3 — (planned) agentic brainstorm wave

3 parallel research agents dispatched 2026-07-29 ~05:20 UTC:
- Red-team quant PM: why the bot still fails; over-filtering analysis;
  required expectancy math for a $10 account.
- Alpha researcher: free-Binance-endpoint signals (funding, OI delta,
  taker ratio, CVD, VWAP reversion, liq cascades) with evidence + wiring.
- Contrarian microstructure: crowded-bot footprints, stop-hunt/liquidity
  sweep fades, anti-consensus rules, compounding math to $20/$50/$100.

Synthesis + ranked implementation -> this file, then wave-1 implementation.
