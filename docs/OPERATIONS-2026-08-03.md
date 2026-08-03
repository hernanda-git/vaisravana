# main bot operations and experiment record — 2026-08-03

## scope

This document records the main `vaisravana` bot only. The wave and alpha bots are separate services and were not changed by this work.

## runtime

- mode: PAPER only
- starting paper balance: `$10.00`
- universe: dynamic ranking; the legacy fixed-pairs list is not the source of active pairs
- decision timeframe: `1m`
- context timeframes: `5m,15m`
- maximum open positions: `2`
- total margin cap: `60%` of current paper equity
- maximum new entries/hour: `3`
- same-pair spacing: `1800s`
- live-order path: disabled; live cutover remains human-gated

## risk and accounting

- maker-style fee is modeled on entry and taker-style fee on close.
- paper equity is calculated from realized net pnl after fees plus unrealized mark-to-market pnl.
- daily drawdown is recalculated from database records, including fees, so a restart cannot erase the drawdown state.
- the kill switch halts new decision processing when the configured daily loss limit is reached.
- partial take-profit is one-shot and persisted via `trade_logs.ts_partial_close`.
- dust partials are rejected; a partial close must be materially larger than 1% of the remaining position.

## telegram event policy

Every full open and full close is posted to the configured main-bot Telegram chat.

Open cards include:

- pair, direction, timeframe
- entry, stop loss, take profit
- size and leverage
- entry fee
- balance, used margin, free margin
- unrealized and realized pnl

Close cards include:

- pair, direction, timeframe
- exit price and exit reason
- R multiple
- net pnl after fees
- close fee
- balance, used margin, free margin
- unrealized and realized pnl
- cumulative win rate and cumulative fees

Partial exits use a separate `PARTIAL` card and show closed size, remaining size, remaining stop, net pnl, and fee. This prevents a partial event from being mistaken for a fully closed trade.

## fresh experiment evidence

The previous paper database was preserved before the fresh experiment. It was not deleted.

The fresh run had reached 18 closed trades at the last verified checkpoint:

- gross pnl: `+$0.2493`
- fees: `-$0.0390`
- net realized pnl: approximately `+$0.2103`
- wins: `15/18`

This is encouraging but not statistically sufficient to claim a durable edge. The next evaluation checkpoint is 50 closed trades, followed by an out-of-sample review.

## non-negotiable evaluation rules

Do not promote based on win rate alone. Review:

1. net balance after fees
2. expectancy after fees
3. profit factor
4. maximum drawdown
5. losing streak
6. pair and side contribution
7. partial-exit and slippage behavior

Any tuning must preserve or improve fee-adjusted out-of-sample performance. If a change reduces net expectancy or increases drawdown, revert it.

## operational commands

From `/opt/bots`:

```bash
docker compose -f docker-compose.yml ps vaisravana
docker logs --since 30m bots-vaisravana
```

The running VPS tree is deployed from `/opt/bots/vaisravana`. The source-of-truth git workspace is `/root/vaisravana-workspace/vaisravana`.

## rollback

The pre-experiment database backups remain under `/opt/bots/vaisravana/data/`. Code rollback is available through git history. Never wipe the paper database as part of routine tuning.

## security

Secrets remain in environment files and are not committed. Telegram tokens, API keys, and private credentials must not be added to source, documentation, or git history.

## monitoring note

This is a paper experiment, not a profit guarantee. A positive short sample is evidence to continue measurement, not evidence to enable live trading.
