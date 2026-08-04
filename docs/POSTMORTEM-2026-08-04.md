# main bot paper-run postmortem — 2026-08-04

## scope

this postmortem covers the fresh main-bot paper run only. alpha and wave were not modified.

## run state

- mode: paper
- run stopped: 2026-08-04 00:55 utc
- database backup: `/opt/bots/vaisravana/data/vaisravana.db.postmortem-20260804T005505Z`
- database integrity: ok
- closed trades: 25
- open trades at stop: 2
- total trade rows: 27

## performance

- starting balance: $10.00
- gross pnl: -$1.03497
- fees: -$0.06436
- net realized pnl: -$1.09933
- estimated realized balance: $8.90067
- wins: 9
- losses: 16
- win rate: 36.0%
- daily drawdown alert: 13.99% versus 2.0% configured threshold

net pnl formula: gross pnl minus recorded fees.

## open positions preserved at stop

- AIOTUSDT SELL, size 122, entry 0.04123, SL 0.04203775002, TP 0.0390357795
- RIFUSDT SELL, size 67, entry 0.07545, SL 0.07756575, TP 0.0686596553

these positions remain paper records. they were not silently deleted or rewritten.

## exit analysis

| reason | count | net pnl |
|---|---:|---:|
| SL | 16 | -$0.71890 |
| CONF_COLLAPSE | 6 | -$0.46093 |
| FLIP | 1 | -$0.00911 |
| TP | 2 | +$0.08961 |

sl and confidence-collapse exits account for essentially all realized losses. tp frequency was low.

## side analysis

| side | trades | wins | net pnl |
|---|---:|---:|---:|
| BUY | 10 | 5 | -$0.23182 |
| SELL | 15 | 4 | -$0.86751 |

sell is the dominant loss source in this sample.

## conclusion

the run failed its fee-adjusted balance-growth objective. the kill switch correctly detected excessive drawdown, but paper collection mode intentionally continued to gather evidence. this mode must not be used for live trading.

## next engineering gates

1. do not reset or delete this evidence.
2. evaluate confidence-collapse logic separately; its net result was negative.
3. validate sell-side suppression or redesign with out-of-sample data.
4. test adaptive TP against the preserved baseline, not against win rate alone.
5. add mark-to-market closing/reporting for positions open at a manual stop.
6. run a new paper candidate only after the above changes are documented and tested.
7. no live promotion.

## redesign started

- `CONF_COLLAPSE` is now feature-flagged with
  `VAISRAVANA_CONF_COLLAPSE_ENABLED`; the next paper experiment disables it so
  its six losing exits can be evaluated without deleting the evidence.
- Default behavior remains enabled unless the paper deployment explicitly sets
  the flag to `0`.

## source evidence

all figures were queried directly from `/opt/bots/vaisravana/data/vaisravana.db` at stop time. the backup was copied before further changes.

## rollback

restore only with explicit authorization. the backup is evidence, not a new active database.
