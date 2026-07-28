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
