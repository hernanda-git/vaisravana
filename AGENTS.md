# agent instructions — vaisravana main bot

## scope and identity

this repository is the vaisravana **main bot** only. do not confuse it with:

- `@wave_vaisravana_bot` — wave bot
- `@xvalarion_bot` — fatty bot
- vaisravana-alpha — separate bot/repository

running vps deployment paths:

- source workspace: `/root/vaisravana-workspace/vaisravana`
- deployed tree: `/opt/bots/vaisravana`
- compose file: `/opt/bots/docker-compose.yml`
- container: `bots-vaisravana`
- active paper db: `/data/vaisravana-ab-no-conf.db` (inside container)
- baseline db: `/opt/bots/vaisravana/data/vaisravana.db.postmortem-20260804T005505Z`

## safety boundary

1. paper mode only. never enable live trading autonomously.
2. never delete or wipe the paper database without explicit user instruction.
3. preserve historical db backups before resets or migrations.
4. do not change alpha or wave while working on main bot.
5. do not claim a deployment, telegram message, github push, or file write without a verifiable result.
6. secrets stay in `.env` files and must never enter source, docs, logs, commits, or final replies.
7. the kill switch is a safety control, not a trading obstacle to bypass.

## truthfulness protocol

separate every report into:

- observed: direct command/tool evidence
- inferred: reasoned interpretation
- unknown: not measured or not verified

never call a small positive sample "profitable" as a durable edge. report gross pnl, fees, net pnl, sample size, drawdown, expectancy, profit factor, and open exposure.

## minimum promotion evidence

- at least 50 out-of-sample trades for a candidate
- positive fee-adjusted expectancy
- profit factor above the configured threshold
- acceptable maximum drawdown
- clean telemetry and no unresolved execution/position-management defects

## current experiment state

active a/b run: `conf_collapse` disabled, isolated database.

baseline results: 25 closed trades, 36.0% WR, -$1.0993 net after fees.

a/b candidate (as of 2026-08-04 ~05:00 utc): 10 closed trades, 70.0% WR, +$0.1325 net after fees. sample too small for conclusions.

next checkpoint: 30 closed trades. evaluate net expectancy, profit factor, drawdown, and losing streak.

## forbidden shortcuts

- no "money hack" or guaranteed-profit claim
- no disabling risk gates just to create trades
- no silent db wipe
- no unverified "pushed successfully" claim
- no bulk repository changes without showing scope
- no strategy regression disguised as a documentation change

## final response style

use concise lowercase mixed indonesian/english when replying to the owner. include exact numbers and status. avoid guarantees, hype, and unsupported claims.

## source of truth

when documents conflict with runtime, runtime evidence wins for current status; git history wins for committed source; explicitly explain discrepancies.

last reviewed: 2026-08-04
safety model: paper-only, fee-aware, evidence-first
