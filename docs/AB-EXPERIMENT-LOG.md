# main bot a/b experiment log

## experiment design

| field | baseline (conf_collapse on) | a/b (conf_collapse off) |
|---|---|---|
| database | `vaisravana.db` | `vaisravana-ab-no-conf.db` |
| started | 2026-08-03 16:04 utc | 2026-08-04 01:01 utc |
| conf_collapse | enabled (default) | disabled |
| adaptive tp | enabled | enabled |
| cvd mode | shadow | shadow |
| max positions | 2 | 2 |
| margin cap | 60% | 60% |
| entries/hour | 3 | 3 |
| pair spacing | 30 min | 30 min |
| paper after kill | yes | yes |
| mode | paper | paper |

## hypothesis

disabling conf_collapse (6 exits, -$0.46 in baseline) will improve net pnl after fees by removing a consistent loss source.

## current results (2026-08-04 ~05:00 utc)

### baseline

- closed trades: 25
- wins: 9
- win rate: 36.0%
- gross pnl: -$1.0350
- fees: -$0.0644
- net pnl: **-$1.0993**
- exit reasons: sl=16, conf_collapse=6, flip=1, tp=2
- buy side: 10 trades, -$0.23
- sell side: 15 trades, -$0.87

### a/b candidate

- closed trades: 10
- wins: 7
- win rate: **70.0%**
- gross pnl: +$0.1537
- fees: -$0.0212
- net pnl: **+$0.1325**
- exit reasons: sl=9, tp=1, conf_collapse=0
- sell side only: 10 trades, +$0.13
- no kill switch warnings

## early signal

- disabling conf_collapse removed 6 losing exits
- sl frequency remains high (9/10) but winners compensate
- sample size is small (10 trades)
- no buy-side data yet

## required evidence before promotion

- at least 30 closed trades
- positive net expectancy after fees
- profit factor > 1.0
- maximum drawdown acceptable
- losing streak analyzed

## preserved evidence

- baseline db: `/opt/bots/vaisravana/data/vaisravana.db.postmortem-20260804T005505Z`
- a/b db: `/data/vaisravana-ab-no-conf.db` (inside container)
- docs: `POSTMORTEM-2026-08-04.md`

## next actions

1. do not change configuration
2. let the a/b run collect data
3. evaluate after 30 closed trades
4. if negative, redesign sell/entry logic
5. if positive, evaluate further improvements
6. never enable live trading without full evidence
