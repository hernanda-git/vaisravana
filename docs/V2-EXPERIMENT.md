# v2 tightened experiment

## changes from v1 (a/b no-conf)

| parameter | v1 | v2 |
|---|---:|---:|
| entry threshold | 0.45 | 0.75 |
| watch threshold | 0.40 | 0.65 |
| sl (scalp) | 1.125x ATR | 2.5x ATR |
| tp (scalp) | 2.25x ATR | 2.5x ATR |
| sl (day) | 1.5x ATR | 2.5x ATR |
| tp (day) | 2.5x ATR | 3.0x ATR |
| sl (swing) | 2.0x ATR | 2.5x ATR |
| tp (swing) | 4.0x ATR | 4.0x ATR |
| min tp move | 0.24% | 0.50% |
| max entries/hour | 10 | 3 |
| pullback guard | buy only | buy + sell |
| conf_collapse | enabled | disabled |
| adaptive tp | enabled | enabled |
| cvd | shadow | shadow |

## rationale

v1 problems identified from 31-trade evaluation:
- entry threshold 0.45 was too low — generated too many mediocre entries
- sl 1.125x ATR was too tight — 28/31 exits were SL
- min tp move 0.24% barely covered fees
- buy side was a net loss
- 10 entries/hour was too frequent for a $10 account

v2 fixes:
- entry threshold 0.75 means only very strong setups enter
- sl 2.5x ATR gives trades room to survive 1m noise
- min tp move 0.50% ensures minimum expected move covers fees
- pullback guard requires price to have retraced before entry
- max 3 entries/hour reduces fee burn

## expected behavior

- fewer trades (quality over quantity)
- larger SL means fewer SL exits
- higher entry bar means only strong setups
- pullback guard prevents chasing
- net positive expectancy after fees

## monitoring

cron job `v2 main bot monitor` runs every 2 hours and reports:
- trade count, win rate, net pnl
- exit reason breakdown
- side performance
- health status
- comparison with baseline

## evidence

- baseline: 25 trades, -$1.0993 net (conf_collapse enabled)
- v1 a/b: 31 trades, -$0.0202 net (conf_collapse disabled)
- v2: fresh start, 0 trades, collecting

## next evaluation

- 30 closed trades
- if still negative, redesign again
- never enable live trading
