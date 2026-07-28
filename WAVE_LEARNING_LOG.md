# Wave Engine — Learning Log (autonomous improvement loop)

Directive: maximize long-term risk-adjusted growth, minimize catastrophic loss.
Loop: observe -> analyze -> research -> improve -> validate -> deploy -> repeat.
Every change recorded with hypothesis, evidence, verdict. Metrics are the source
of truth; no change is kept unless it beats the prior baseline on risk-adjusted
survival + win quality (not raw trade count).

Baseline (pre-loop, run5): 18 opens / 9 closes. All closes r = -1.0 (full SL).
Win rate 0%. Cause: 88% SELL on sideways/up tape, fixed 1% SL clipped by noise.
Balance $8.96 after 5 min. Fee $0.418.

---

## ITER-1 (P4a) — ATR stop + reversal exit
- Hypothesis: a wider, volatility-scaled SL stops normal oscillation from
  clipping every SELL; a "winner became loser" reversal exit locks small loss
  instead of full SL.
- Change: `_atr_pct()` helper; SL = max(1%, 1.8xATR); add `reversal` exit
  (peak_r>=0.5 and live_r<0 -> close).
- Test: run6, MAX_WAVE_AGE_S=300, fresh $10.
- Evidence: 15 opens / 7 closes (all max_age). Balance $9.33 after 6 min.
  Fee $0.572. No SL clips, no reversal triggers yet (waves expire before
  reversal condition met in this tape).
- Verdict: ATR SL is safer (no -1.0R SL clips in 7 closes), survival better
  ($9.33 vs $8.96 baseline at similar trade count). KEEP. Reversal exit not
  yet exercised — keep, will validate in noisier tape.
- Note: max_age=300 means waves expire fast; in prod use 1800. The fact that
  closes are max_age (not SL) confirms ATR SL is now wide enough.

---

## Loop standing questions (carried forward)
1. Direction: bot is still ~88% SELL. Need bullish tapes to actually fire BUY.
   Is `read_bias` returning bearish too often, or is the tape genuinely bearish
   and the bot is right but the SL/TP math loses? Validate by logging live
   bias.direction distribution per pair.
2. TP never hit (1.5R). Either TP too far for the realized volatility, or the
   wave expires (max_age) before price travels 1.5R. Shorten TP to ~1.0R or
   scale TP with ATR (e.g. 2xATR target).
3. Fee drag: at ~$0.57 / 6min the $10 account dies in ~100 min of constant
   trading. Must cut frequency further OR raise expectancy per trade. P0 cap=8
   helps; consider raising cooldown or requiring stronger conviction.

Next iteration targets: (a) ATR-scaled TP (2xATR) so target is reachable,
(b) verify BUY fires on up-tapes (directional balance), (c) log live bias
distribution for evidence.

---

## ITER-2 — robust bias (trend+momentum) + ATR-scaled TP
- Hypothesis: `read_bias` used `ema_15m vs price` which is laggy — ema_15m
  stayed above price during up-moves, so the bot SELLed into rallies (all
  closes were losses in iter-0/1). Fix: mtf_ema = 0.6*trend(ema_15m vs
  ema_1h) + 0.4*momentum(price vs ema_15m). And TP should be volatility-scaled
  (2xATR, floor 1.2x risk) so winners are reachable, not a fixed 1.5R the tape
  never travels.
- Change: bias.py mtf_ema blend; manager.open TP = max(1%, 2xATR) scaled.
- Test: run7, fresh $10, MAX_WAVE_AGE_S=600 (env; default now 900).
- Evidence: 9 opens / 20 trades in 7min, fee only **$0.05** (vs $0.57/6min
  baseline run6, $0.418/5min run5). Bot is now highly selective — fee drag
  dropped ~10x. 0 closes in the 11min window because MAX_WAVE_AGE_S did not
  trigger (env-not-loaded suspicion; default lowered to 900 for next run).
- Verdict: KEEP. Selectivity + fee efficiency are the single biggest survival
  win so far. ATR TP not yet exercised (no closes) — validate in iter-3.

## Loop state (end of iter-2)
- Baseline win rate still 0%, but fee drag is now tiny, so survival is no
  longer fee-limited — it is expectancy-limited. The lever is now direction
  + TP quality, not frequency.
- Next iter (3): confirm MAX_WAVE_AGE_S fires (default 900), observe close
  reasons + live bias.direction distribution (are BUYs firing on up-tapes?),
  and tune TP/SL R-ratio so a hit winner pays >1R consistently.

---

## ITER-3 — directional diagnostic (ema15/ema1h on every open)
- Hypothesis: the bot is ~88-100% SELL. Either the tape is genuinely bearish,
  or ema_15m/ema_1h feed is stale and biases every wave to SELL. Need evidence.
- Change: log `bias.direction(strength)` + `ema15` + `ema1h` on every WAVE OPEN.
- Test: run8, fresh $10, MAX_WAVE_AGE_S=900 (default).
- Evidence: 9 opens ALL `bias=bearish`. On opens, ema_1h is FROZEN
  (e.g. INJUSDT ema1h=4.68687 constant across 9 ticks) while ema_15m tracks
  price (4.639xx). So `trend = ema_15m < ema_1h` => ALWAYS bearish between
  hourly candles => 100% SELL. That is the laggy-bearish bug.
  Closes: 9× max_age (anti-stuck fires correctly at 15m). R now near-zero
  (-0.04 .. +0.08) — ATR SL stopped the -1.0R clips. Several closed +R
  (0.02-0.08). Balance $9.76 after 16min, fee $0.246. Break-even per wave
  before fees = real progress.
- Verdict: diagnostic KEEP (log stays). Root cause found: stale ema_1h forces
  bearish. Fix in iter-4.

## Loop state (end of iter-3)
- The engine no longer loses big per wave (R near 0, some +R). Fee drag is
  controlled (~$0.25/16min). Survival is now governed by DIRECTION: it SELLs
  everything because ema_1h is frozen-bearish. Fixing direction = the win-rate
  lever.
- iter-4 target: fix directional bias — stop using stale ema_1h for trend; use
  (price vs ema_15m) momentum as primary and only use ema_1h trend when it has
  updated within ~1h, OR bump ema_1h update frequency. Expect BUYs to start
  firing on up-tapes. Also: consider shorter max_age (e.g. 600) so trades don't
  sit 15m collecting only fee.

---

## ITER-4 — directional fix (live momentum primary)
- Hypothesis (from iter-3 root cause): ema_1h is frozen between hourly candles, so
  the trend term forced a constant bearish bias => 100% SELL. Fix: make live
  MOMENTUM (price vs ema_15m) the PRIMARY signal (always current), demote the
  stale ema_1h trend to 0.2 weight so it cannot dominate.
- Change: bias.read_bias mtf_ema = 0.8*momentum + 0.2*trend.
- Test: run9, fresh $10, MAX_WAVE_AGE_S=900.
- Evidence: 9/9 opens are **BUY, bias=bullish 0.57-0.67** (was 100% SELL).
  Direction is FIXED — the bot now buys up-tapes. BUT all 9 closes are max_age
  at NEGATIVE R (-0.02 .. -0.22), balance $9.04 after 25min, fee $0.838.
  The tape did not rise enough in 15min for TP, and waves expired near entry.
- Verdict: KEEP the directional fix (real progress: SELL-everything bug gone).
  But exit is too slow — 15min max_age lets small losses accumulate. The new
  lever is EXIT SPEED, not direction.

## Loop state (end of iter-4)
- Trajectory: run5 all -1.0R SL clips -> run6/7 ATR SL (R near 0) -> run8
  100% SELL (frozen ema_1h) -> run9 100% BUY (fixed) but exits too slow.
- The engine now (a) survives (no -1.0R clips), (b) is directionally correct.
  Remaining gap = EXIT TIMING: waves should either hit TP (1.2-2R) or cut fast
  when momentum fades, not sit 15min to a small loss.
- iter-5 target: faster exit. Options (pick ONE, test, compare):
  (a) lower MAX_WAVE_AGE_S 900->420 (7min) so stalls cut sooner;
  (b) add a momentum-fade exit: if peak_r>=0.2 then live_r<0 -> close
      (lock the round-trip immediately, don't wait for max_age);
  (c) raise TP reachability: TP = 1.5xATR (from 2xATR) so winners hit sooner.
  Prefer (b) — it directly converts "was up, gave it back" into a smaller loss
  or scratch, which is the expert rule already partially present (reversal at
  peak>=0.5). Lower the reversal threshold to peak>=0.2.

---

## ITER-4 — momentum-primary bias (0.8 momentum / 0.2 trend) — REJECTED, reverted
- Hypothesis: iter-3 found ema_1h frozen between hourly candles => trend
  (ema_15m vs ema_1h) constantly bearish => 100% SELL. Fix attempted: make live
  momentum (price vs ema_15m) primary at 0.8 weight, demote trend to 0.2.
- Change: bias.py `mtf_ema = 0.8*momentum + 0.2*trend` (commit 73202fd).
- Test: run9, fresh $10, ~16 min measured window.
- Evidence: 18 opens (2x baseline rate), 100% bias=bullish — the bot flipped
  from all-SELL to all-BUY, chasing per-tick noise. 9 closes, all max_age,
  R range -0.22..0.00, ZERO positive R. Balance $8.92, fees $0.964 (~4x the
  $0.246 of run8 baseline which finished $9.76 in the same window). Momentum
  vs ema_15m is a noise follower: price sits above a lagging fast EMA during
  micro-pumps, so every pair looks bullish, entries are late, and the wave
  mean-reverts before max_age.
- Verdict: REJECT. Worse on every risk-adjusted metric (balance, fee drag,
  R distribution, selectivity). Reverted bias.py to iter-3 formula
  (0.6*trend + 0.4*momentum). Post-revert sanity run shows mixed direction
  again (BUY AAVE where ema15>ema1h, SELLs elsewhere) — trend is not
  permanently-bearish, it only pins bearish when ema_1h is stale ABOVE price.
- Lesson: do not demote the slow signal to fix staleness; fix the staleness.
  Raising momentum weight trades one degenerate regime (all-SELL) for a worse
  one (all-BUY + 2x churn + 4x fees).

## Loop state (end of iter-4)
- Baseline remains iter-3 code: run8 = $9.76 @16min, fee $0.246, R -0.04..+0.08.
- Standing questions (updated):
  1. FIX EMA_1H STALENESS AT THE SOURCE (next iter, small + safe): update
     ema_1h from the live 15m closes (e.g. maintain a rolling 1h EMA computed
     from 15m candle closes with the equivalent alpha), or refresh ema_1h via
     REST kline poll every 15m instead of hourly. Then trend flips correctly
     without touching the 0.6/0.4 blend.
  2. TP still never hit (all closes max_age). After direction is fixed,
     evaluate whether 2xATR TP is reachable within 900s, or scale max_age
     with ATR/timeframe.
  3. Keep fee drag at ~run8 levels; any change that doubles opens/min is
     suspect regardless of direction.
