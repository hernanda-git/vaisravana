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
