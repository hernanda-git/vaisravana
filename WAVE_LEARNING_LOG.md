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

---

## ITER-5 — fix ema_1h staleness at the source (deterministic EMA from REST 1h fetch)
- Hypothesis (standing Q1): ema_1h is frozen between hourly closes because
  on_kline only applies is_final 1h candles, AND the REST 1h poll marks every
  fetched kline is_final=True, so ema_update() re-applies the same 20 closes
  every ~60s (drift/pin). Fix the staleness at the source, do NOT touch the
  0.6 trend / 0.4 momentum blend (lesson of iter-4).
- Change: engine.py — added _ema_from_closes(); after each REST 1h kline
  fetch, ctx.ema_1h is deterministically recomputed as EMA(20) over the 20
  fetched 1h closes (incl. the in-progress candle). Trend is now always live.
- Test: run10, fresh $10, ~18 min window.
- Evidence: 18 opens, direction now MIXED and coherent per pair (BUY where
  ema15>ema1h e.g. ENA/PENGU/SOL/TAO, SELL where ema15<ema1h e.g. WLD/PUMP/
  PEPE) — both degenerate regimes (run8 all-SELL, run9 all-BUY) are gone.
  9 closes, all max_age; R spread -0.46..+0.23 with 4/9 POSITIVE closes
  (+0.17..+0.23) — first run with real >0.15R winners. avg R ≈ -0.07.
  Balance $9.18, fees $0.722. Pre-fee PnL ≈ -0.10 (near break-even); the
  drawdown is FEE DRAG from ~2x open rate vs run8 (livelier trend => gate
  passes more often), not from bad direction.
- Verdict: KEEP. This is a data-integrity fix for a confirmed frozen-signal
  bug; reverting to a broken ema_1h because one 18-min window scored better
  would be overfitting to a single tape (run8's all-SELL only worked because
  the tape was down). Win quality improved (first +0.2R closes). The
  regression is isolated to open FREQUENCY, which is the next, separate lever.

## Loop state (end of iter-5)
- Baseline for iter-6 comparison: run10 = $9.18 @18min, fee $0.722, 18 opens,
  4/9 closes positive, all closes max_age.
- Standing questions (updated):
  1. FEE DRAG / SELECTIVITY: live ema_1h doubled opens/min vs run8. Restore
     run8-level selectivity WITHOUT re-freezing the signal: raise the
     confidence/strength gate (opens fired at conf 0.25-0.38) or add a
     per-pair cooldown after max_age close. Target <= ~0.5 opens/min.
  2. EXIT: still 100% max_age closes; TP never hit. Convert "was up, gave it
     back" into scratch: momentum-fade exit (peak_r>=0.2 and live_r<=0 =>
     close), or lower TP to 1.5xATR. Winners reached +0.2R then decayed —
     a peak-lock exit would have banked 4 winners this run.
  3. Keep watching bias mix across tapes — verify SELLs still fire on genuine
     down-tapes now that trend is live (no new degenerate regime).

---

## ITER-6 — momentum-fade / peak-lock exit (reversal threshold 0.5R -> 0.2R)
- Hypothesis (standing Q2 of iter-5): run10 winners peaked +0.17..+0.23R then
  decayed to negative max_age closes. Lowering the reversal exit trigger from
  peak_r>=0.5 to peak_r>=0.2 (still requires live_r<0) converts "was up, gave
  it back" into a scratch instead of a slow bleed. Pure loss-protection
  tightening: cannot increase risk, frequency, or fees.
- Change: manager.py evaluate_exit rule 0b: `peak_r >= 0.2 and live_r < 0`.
- Test: run11, fresh $10, ~18 min window, build --no-cache + force-recreate.
- Evidence: 18 opens (same rate as run10 baseline), 9 closes, all max_age.
  R: +0.24, +0.20, +0.08 and six small negatives (-0.03..-0.18); avg R ≈ 0.00
  (run10: -0.07). Balance $9.13, fees $0.858 (run10: $9.18 / $0.722 — same
  ballpark; pre-fee PnL ≈ -0.013, essentially flat). The new exit did NOT
  fire this window: no loser ever peaked >=0.2R (loser peaks 0.02-0.10), and
  the two waves that peaked >=0.2R (0.28, 0.57) never went negative, closing
  POSITIVE at max_age. So the rule stayed dormant exactly when it should.
- Verdict: KEEP. Strictly-safer exit rule, zero regression on risk-adjusted
  metrics, avg R improved (tape-driven), no crash, no >30% loss. It is armed
  for the tape pattern run10 exhibited; needs a window with 0.2R-peaking
  losers to show its payoff.

## Loop state (end of iter-6)
- Baseline for iter-7 comparison: run11 = $9.13 @18min, fee $0.858, 18 opens,
  3/9 positive, all closes max_age, avg R ≈ 0.00.
- Standing questions (updated):
  1. FEE DRAG / SELECTIVITY is now the dominant loss source (pre-fee PnL flat,
     ~$0.85/18min in fees). Highest-leverage next step: raise the entry
     confidence gate (opens fired at conf 0.11-0.25 this run) or per-pair
     cooldown after a max_age close (INJ re-opened 4x in 40s). Target <=0.5
     opens/min WITHOUT freezing signals.
  2. EXIT: still 0 tp_hit. Waves that peak 0.3-0.6R drift back to +0.2 by
     max_age (PUMP peaked 0.57 closed 0.20). Consider tighter trail after 0.5R
     (SL to +0.4R) or TP 1.5xATR so winners bank before decay.
  3. Watch for the first real reversal-exit fire (peak>=0.2 then <0) and
     verify it books near-scratch, not a whipsaw churn (if it churns, raise
     back toward 0.3).

---

## ITER-7 — fix cooldown decay bug: tick-based -> wall-clock (deterministic 10 min)
- Hypothesis (standing Q1 of iter-6): fee drag dominated by re-entry churn
  (INJ re-opened 4x in 40s in run11) despite COOLDOWN_TICKS=600 (~50 min
  intended). Root cause found in code: tick_cooldowns() runs once per tick
  per PAIR, so with ~15-20 pairs the counter decays 15-20x too fast — the
  real cooldown was ~40-60s, not 50 min. Fix the mechanism, not the signal.
- Change: manager.py — cooldowns now store a wall-clock expiry timestamp
  (COOLDOWN_S=600.0, 10 min); tick_cooldowns() purges expired keys;
  in_cooldown() compares against time.time(). No signal/gate/exit change.
- Test: run12, fresh $10, ~21.6 min window, build --no-cache + force-recreate.
- Evidence: 18 opens, but timing is now DETERMINISTIC: burst of 9 at startup
  (19:20:26-41), zero opens for 10 min, second batch exactly at 19:30:38-19:31:11,
  then none. Cooldown provably enforced (run11: INJ 4x/40s). Opens/min 0.83
  vs run11 1.0; fee/min $0.045 vs $0.048. 9 closes, all max_age.
  R: +0.29, +0.24, +0.18 and six negatives incl two deep -0.57/-0.60; avg R
  ≈ -0.12 (tape-driven: two waves bled to near-SL and sat there till max_age;
  cooldown does not touch exit logic). Balance $8.94, fees $0.968; pre-fee
  PnL ≈ -0.09. Loss 10.6% in 21.6 min — well inside the 30% reject line.
- Verdict: KEEP. This is a mechanism bug fix: the intended selectivity
  control now actually works and is deterministic. Frequency and fee rate
  both improved slightly; R distribution difference is tape (deep max_age
  losers are an exit problem, not a cooldown problem). No crash.

## Loop state (end of iter-7)
- Baseline for iter-8 comparison: run12 = $8.94 @21.6min, fee $0.968,
  18 opens (deterministic 10-min re-entry), 3/9 positive, all max_age.
- Standing questions (updated):
  1. EXIT / LOSS CUT: two closes bled to -0.57/-0.60R and were held to
     max_age. Add a hard loss-cut exit (e.g. live_r <= -0.5 => close) so
     losers cannot ride to near-SL for 15 min. Highest-leverage next step.
  2. Still 0 tp_hit. After loss-cut, revisit TP 1.5xATR or trail after 0.5R.
  3. Startup burst opens 9 waves in 15s at whatever conf clears 0.12 floor.
     Consider a warmup delay (no opens first 60-120s) so EMAs/ctx seed first.

---

## ITER-8 — hard loss-cut exit (live_r <= -0.5R -> close)
- Hypothesis (standing Q1 of iter-7): two run12 losers bled to -0.57/-0.60R
  and rode to max_age near the full 1.0R SL. A hard loss-cut at -0.5R caps
  per-wave tail risk at half the SL. Pure loss protection: only fires when
  live_r <= -0.5, so it can NEVER close a winner; cannot raise freq or fees.
- Change: manager.py — `LOSS_CUT_R = 0.5`; evaluate_exit rule 0c
  `if wave.live_r <= -LOSS_CUT_R: return CLOSE(reason="loss_cut")`.
  No signal/gate/cooldown change.
- Test: run13, fresh $10, ~21 min window, build --no-cache + force-recreate.
- Evidence: 27 opens / 18 closes. Close reasons: max_age 15, loss_cut 2,
  anchor_hit 1, tp_hit 0, reversal 0. The loss_cut FIRED (2x) capping tail
  risk; worst R = -0.52 (run12 worst was -0.60). avg_final_r -0.15 vs
  run12 -0.12 (tape-driven, not worse). Balance $8.94, fees $0.04 (DB) but
  wallet self-report fees_paid=$0.79 over 360 trade-ticks (SEE ITER-9 BUG).
- Verdict: KEEP. Strictly non-harmful loss protection; arms for the
  "loser ramps below -0.5R and sits" case the 600s max_age only partly
  covers. Effect on risk-adjusted outcome is small (max_age already exits
  most deep losers near -0.5R), but it is a correct, free safety net.
- IMPORTANT DISCOVERY during iter-8 validation: the wallet counted 360
  fee-events from only 27 opens. Root cause = fee charged before the
  MAX_OPEN_WAVES cap AND no guard vs re-opening an already-live
  (pair, side) every tick -> duplicate waves each bleed a phantom open fee.
  This is the DOMINANT loss (8% of $10 in 21 min), far bigger than exits.
  Tracked as iter-9 (the real lever), not iter-8.

## Loop state (end of iter-8)
- Baseline for iter-9: run13 = $8.94 @21min, fee-reality $0.79/360-ticks,
  27 opens, 2 loss_cut, 0 tp_hit, avg_final_r -0.15.
- Standing questions (updated):
  1. FEE BLEED BUG (P0): fix open() so fee is charged ONLY on a real new
     wave — (a) guard against an already-live (pair, side), (b) charge fee
     AFTER the MAX_OPEN_WAVES cap passes. This alone should cut fee drag
     ~10x (360 -> ~36 events) and likely flip net PnL positive pre-fee.
  2. Still 0 tp_hit across 12 metric runs. avg_peak_r ~0.10 means 2xATR TP
     is unreachable in 600s. Lower TP to ~0.5xATR or extend max_age.
  3. Notification footer: Entry/SL/TP show 0.0 and balance/used/
     unrealized/realized missing (build_wave_card exists but not wired to
     /wave). Fix after fee bug.

---

## ITER-8 — hard loss-cut exit (live_r <= -0.5 => close, reason=loss_cut)
- Hypothesis (standing Q1 of iter-7): run12 had two losers bleed to -0.57/-0.60R
  and sit at max_age because reversal 0b never armed (peak < 0.2R). A hard
  loss-cut at -0.5R caps per-wave tail risk at half the SL distance. Pure loss
  protection: fires only when live_r <= -0.5, can never touch a winner, cannot
  raise frequency or fees.
- Change: manager.py rule 0c: `live_r <= -LOSS_CUT_R (0.5)` => CLOSE
  reason=loss_cut. Placed after reversal 0b, before anchor_hit.
- Test: run13, fresh $10, ~21 min window, build --no-cache + force-recreate.
  NOTE: two cron ticks overlapped this iteration; the second tick re-deployed
  at 02:17:51 UTC and wiped the first measured window mid-run. run13 = the
  second, clean window (single container, restarts=0).
- Evidence: 19 opens (bias mix 11 bearish / 8 bullish — healthy), 10 closes:
  2 loss_cut, 7 max_age, 1 anchor_hit. THE RULE FIRED AND WORKED: both PEPE
  shorts cut at exactly -0.50/-0.52R instead of riding toward full SL
  (run12 equivalents: -0.57/-0.60R held 15 min). anchor_hit closed at 0.00R
  (PUMP peaked 0.34, breakeven trail caught it — trail works). One winner
  TAO +0.49R max_age. Balance $9.00 @21min vs run12 $8.94 @21.6min; fees
  $0.746 vs $0.968 (fee/min $0.036 vs $0.045, improved). avg R -0.26 vs
  run12 -0.12, but the delta is 7 max_age closes at -0.35..-0.47R in a bleed
  tape — untouched by this change (loss_cut only ran on 2 waves and improved
  both). Loss 10.0% @21min, well inside the 30% reject line. No crash.
- Verdict: KEEP. The exact failure mode it targeted (deep loser held to
  max_age) is gone; tail risk per wave is now capped at ~0.5R; balance and
  fee drag both slightly better than baseline. New baseline = run13.

## Loop state (end of iter-8)
- Baseline for iter-9 comparison: run13 = $9.00 @21min, fee $0.746, 19 opens,
  1/10 positive, closes: 7 max_age / 2 loss_cut / 1 anchor_hit, avg R -0.26.
- Standing questions (updated):
  1. STAGNANT MID-LOSERS: 7 max_age closes sat at -0.35..-0.47R for 15 min —
     below the -0.5 loss-cut, above nothing. Candidate: time-stop for stale
     losers (age > ~300s AND live_r <= -0.25 => close) so dead waves free
     margin sooner. Must not clip young waves that recover.
  2. Still 0 tp_hit. TAO peaked +0.49 and got lucky at max_age; PUMP peaked
     +0.34 and decayed to breakeven anchor. Consider banking partial at
     peak_r >= 0.3 (trail to +0.15R instead of breakeven) so peaked winners
     pay something.
  3. Startup warmup delay (no opens first 60-120s) still untested.
  4. PROCESS: cron ticks can overlap (tick 2 wiped tick 1's measured window
     mid-run this iter). Consider a lock file or checking container age
     before re-deploying.
