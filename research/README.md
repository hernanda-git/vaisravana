# research/ — brainstorm & research artifacts for the main-bot improvement loop

Permanent archive of every research input that feeds MAIN_LEARNING_LOG.md.
Each iteration's decisions must be traceable back to a document here.

## Index

| File | Source | Date | Feeds |
|---|---|---|---|
| scalping_bot_research.md | Subagent: pro-engine meta techniques (15 ranked) | 2026-07-29 | Iter 1 (v0.0.34 survival layer) |
| redteam_quant_report.md | Subagent: ruthless quant PM red-team of v0.0.34 | 2026-07-29 | Iter 4 (v0.0.35 frequency un-strangle, BE-trail 1.0R, exit policy) |
| alpha_signals_summary.md | Subagent: evidence-ranked free-Binance-endpoint signals | 2026-07-29 | Iter 4 (CVD veto, OI flush veto); iter 5+ backlog (VWAP bands, BTC lead-lag, funding extremes) |
| scalp_entry_signals_report.md | Full version of the alpha research (endpoints live-verified) | 2026-07-29 | Same as above |
| contrarian_microstructure_report.md | Subagent: crowded-bot footprints, anti-consensus rules, $10 compounding math | 2026-07-29 | Iter 4 (risk policy 1-2%/trade); backlog (sweep-reversal, EMA-cross fade, round-number TP trim, liq-flush fade via forceOrder WS) |

## External repos studied

| Repo | Claim | Honest verdict | Adopted |
|---|---|---|---|
| ajidwip/ai-trading-sequence-5m | 66% WR LSTM 5m ADAUSDT | Claim not verifiable (DB has 3 trades, 2 breakeven; SL/TP 20x ATR inflate WR by design; filters commented out; conf floor 0.45 near-random on 3 classes) | Signal-flip exit (AI_REVERSE) -> v0.0.35 FLIP; first-touch labeling idea -> TP calibration backlog |

## Implementation backlog (researched, not yet implemented)

Ranked by evidence strength x effort, from the reports above:
1. TP retune from realized mfe_r percentiles (needs >=30 trades of run-2 data) — iter 5 candidate.
2. VWAP deviation bands as entry-location filter (from klines, zero cost).
3. BTC lead-lag z-score gate (veto alt SELL when BTC 3m z > +1).
4. Regime router: full risk in trending_bear, probe-only in bull, half in chop.
5. Funding-extreme squeeze veto (premiumIndex batched call).
6. Liquidation-flush fade (forceOrder WS — NOTE: WS from sera is 403-blocked,
   REST-only proxies needed; see WAVE_ENGINE_REVIEW.md PART F).
7. Sweep-reversal entry (contrarian rule 2) — needs mfe/mae data to validate.
8. Weekly gate audit: no single gate may block >30% of otherwise-valid
   signals; demote violators from hard gate to score penalty (red-team §2).
