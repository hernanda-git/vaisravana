# Wave Engine — Run Log (this session, continued)

Continuation of the wave-engine work. All runs are paper mode ($10, 3x lev,
0.04% fee). Recorded DBs in `eval_data/` (wave_run3.db .. wave_run5.db).

## Run 3 (P0+P1+P2 applied, MAX_OPEN_WAVES=8, COOLDOWN=600)
- 9 opens then **stuck**: 9 SELL waves never closed (0 WAVE_BREAK).
- Balance $9.16 after 12 min. Fee $0.84.
- Root cause: no wave timeout → sideways market leaves wave open forever.
- Fix: P3 `MAX_WAVE_AGE_S` (anti-stuck force-close).

## Run 4 (anti-stuck added, MAX_WAVE_AGE_S=1800 = 30m)
- Same stuck pattern for 15 min (anti-stuck not yet triggered at 30m).
- 9 SURFING, 0 WAVE_BREAK. Balance $9.35.
- Confirms anti-stuck needs a shorter window to be observable in testing.

## Run 5 (MAX_WAVE_AGE_S=240s = 4m, quick anti-stuck test)
- **18 opens, 9 closes** — anti-stuck WORKS.
- Close reasons: 6× `anchor_hit`, 3× `max_age`.
- **All closes at r = −1.0x (full 1R loss).** 0 tp_hit, 0 positive conf_collapse.
- Balance $8.96 after 5 min. Fee $0.418 (184 trades cumulative).
- Verdict: bot now trades AND closes (no more stuck), but **win rate is 0%**
  because it is overwhelmingly SELL and the tape is sideways/up → SL (1% above
  entry) gets hit. The engine "surfs" but the directional edge is wrong for
  this tape.

## Honest expert read
- The cascade bugs are FIXED. The bot runs, sizes realistically, takes TP
  logic exists, trailing exists, anti-stuck exists.
- Survival is now limited by **direction**, not bugs: it SELLs a mostly
  sideways/up tape, so every wave hits its 1% SL.
- Next real win-rate gain = **signal direction**: ensure BUY fires on up-tapes
  and SELL only on genuine down-tapes, plus a wider/trailing SL that does not
  get clipped by normal oscillation. See WAVE_IMPROVEMENTS.md P4.

## Settings used
```
VAISRAVANA_PAPER_BALANCE=10.0
VAISRAVANA_PAPER_FEE=0.0004
VAISRAVANA_PAPER_RISK_PCT=0.20
VAISRAVANA_PAPER_MAX=100.0
VAISRAVANA_PAPER_STOP=0.0
VAISRAVANA_MAX_OPEN_WAVES=8   (code default)
COOLDOWN_TICKS=600            (code default)
MAX_WAVE_AGE_S=240            (env override for test; prod default 1800)
```
