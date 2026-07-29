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

## Iter 3 results — brainstorm synthesis (2026-07-29 ~05:45 UTC)

Full reports: /root/.hermes/cache/delegation/subagent-summary-{0,1,2}-*.txt,
/root/scalp_entry_signals_report.md, /root/scalping_bot_research.md.

**Red-team's core verdict (accepted):** v0.0.34 fixed the blowup but strangled
frequency to ~0 with multiplicative hard-AND gates; growth = edge x frequency,
and anything x 0 = 0. The only proven bucket (trending_bear SELL, +$6.92 at
56% WR, ~4.5 trades/h in run 1) was being rate-capped (4/h), session-blocked
(00-05 UTC), ADX-gated (threshold 25 fought the top-chase guard: ADX demands
established trend, top-chase demands pullback, intersection near-empty), and
its profit engine (MAXHOLD grinds) was about to be scratched by the +0.5R
BE-trail. Break-even WR under the run-1 exit structure was ~78% — unwinnable.

**Alpha researcher's top evidence-backed signals (top 2 adopted):**
1. CVD / taker order-flow imbalance — klines idx 9, zero extra REST calls,
   strongest academic backing (SSRN 6938742, Frontiers 2026 OFI).
2. OI-delta x price direction — flush detector; selling into a
   long-liquidation flush = filling at the flush bottom (run-1 SELL failure
   mode). /fapi/v1/openInterest, weight 1, candidates only.
(Deferred: VWAP bands, BTC lead-lag z, funding extremes, forceOrder stream.)

**Contrarian's math (adopted as risk policy):** $10 -> $100 realistically
needs 1,000-2,000 trades at 53-56% WR, 1-2% risk/trade; expect 7-10 loss
streaks; fee-in-R is the dominant term (already gated). 5% risk = ~30%
chance of halving before doubling — stay small. Meta-rules (sweep-reversal,
EMA-cross fade, round-number TP trimming) deferred to a later wave.

**External repo studied (user request): ajidwip/ai-trading-sequence-5m
("66% WR").** Honest read: claim NOT verifiable from the repo — its DB holds
3 trades (two closed at breakeven via AI_REVERSE, pnl 0.0); SL/TP are set at
20x ATR (barely ever hit -> WR inflated by design); EMA/RSI filters are all
commented out; min confidence 0.45 on 3 classes is near-random. BUT two ideas
are genuinely good and stolen: (1) signal-flip exit (AI_REVERSE): exit when
the engine flips to an opposite full signal instead of riding to SL; (2)
first-touch labeling for TP calibration (use later with mfe_r data).

## Iter 4 — v0.0.35 growth wave-1 (deployed 2026-07-29 05:58 UTC)

Changes (all additive/parametric, engine untouched, all env-tunable):
1. **Un-strangle frequency:** hourly cap 4 -> 10; pair spacing 30 -> 15min;
   ADX hard gate 25 -> 15 (demoted to chop-rejector; trend quality already
   in the weighted score); session filter now blocks BUY ONLY — the proven
   SELL side trades all 24h.
2. **Protect the profit engine:** BE-trail arm moved +0.5R -> +1.0R
   (red-team: +0.5R would scratch the oscillating paths that become MAXHOLD
   winners; TP/MAXHOLD retune from real mfe_r data comes next iter).
3. **Signal-flip exit** (close_reason=FLIP): opposite-side full ENTRY signal
   while holding -> exit at market. Cuts avg loser without capping winners.
4. **CVD veto** (compute_cvd_z, klines idx 9, free): don't SELL into
   aggressive buying (z > +1), don't BUY into aggressive selling (z < -1).
5. **OI flush veto** (oi_flush_veto): price down + OI down > 0.3% = long
   liquidation flush -> don't sell the bottom; price up + OI down = squeeze
   pop -> don't buy the top. Fails open on fetch errors.

Verification (container tests): CVD z fires correctly on varied history
(z +9.8 vetoes SELL, z -8.3 vetoes BUY), fails open (None) without taker
data; live SOL cvd_z 0.1 sane; OI flush veto triggers on simulated 1% OI
drop and fails open unprimed; session gate exempts SELL, still blocks BUY;
constants live: ADX_MIN 15, BE arm 1.0R, cap 10/h, spacing 900s, FLIP on.

Success criteria for the KEEP verdict (measure after >=24h / >=30 trades):
- frequency 10-30 trades/day (was 0/day post-v0.0.34, 250/day run 1)
- net expectancy > 0 after fees; balance above $10
- FLIP exits show smaller avg loss than SL exits
- mfe_r/mae_r populated -> feeds TP retune in iter 5

First run-2 trade (2026-07-29 06:00 UTC, ~2min after v0.0.35 deploy):
INJUSDT SELL 15m in trending_bear — exactly the proven bucket. Notional
$5.00 (vs run-1's $956 ETH bomb), lev 3x, SL risk $0.027, RR 2.38, real
spread 2.21 bps recorded. Every structural fix visible in one row.

All research artifacts archived in research/ (see research/README.md for
the index + implementation backlog). Next iteration: pull run-2 trade data
(>=30 closed trades), grade each v0.0.35 change KEEP/REJECT, implement TP
retune from realized mfe_r percentiles, work down the backlog.


