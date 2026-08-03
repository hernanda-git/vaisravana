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
- paper db: `/opt/bots/vaisravana/data/vaisravana.db`

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

never call a small positive sample “profitable” as a durable edge. report gross pnl, fees, net pnl, sample size, drawdown, expectancy, profit factor, and open exposure.

## change protocol

before edits:

1. inspect git status, branch, remote, current deployment, and db state.
2. identify whether the requested change affects strategy, risk, execution simulation, telemetry, notifications, docs, or deployment.
3. snapshot relevant data before destructive operations.

after edits:

1. run `git diff --check`.
2. run `python3 -m compileall -q src scripts/bot_paper.py`.
3. run targeted tests, then the full suite when available.
4. rebuild/redeploy only when necessary; verify container status and recent logs.
5. verify the deployed tree matches the committed source when deploying from a separate tree.
6. commit with a focused message.
7. push only if authentication succeeds; otherwise report commit id and exact push failure.

## performance preservation

strategy changes require before/after evidence. prefer additive observability and bug fixes over unvalidated signal tuning. never optimize win rate alone. fee-adjusted net expectancy is primary.

minimum promotion evidence:

- at least 50 out-of-sample trades for a candidate
- positive fee-adjusted expectancy
- profit factor above the configured threshold
- acceptable maximum drawdown
- clean telemetry and no unresolved execution/position-management defects

## telegram contract

full open and close events must be posted to the configured main-bot chat. cards must include valid prices, fees, balance, used/free margin, unrealized pnl, realized pnl, and exit reason. partial exits must be clearly marked as partial and must not be represented as a full close.

## monitoring

check:

```bash
docker compose -f /opt/bots/docker-compose.yml ps vaisravana
docker logs --since 30m bots-vaisravana
```

for db metrics, use sqlite inside the container or the mounted db. if `decisions_log` stops while health/universe logs continue, treat telemetry as degraded and investigate before tuning strategy.

## remaining known work

- make decision-log write failures visible instead of silently debug-only.
- fix/verify the source/deployed-tree synchronization workflow.
- push commit `3504a8f` when github authentication is available.
- collect the next statistically meaningful paper sample.
- only then evaluate fee reduction, entry quality, side imbalance, and exit tuning.

## final response style

use concise lowercase mixed indonesian/english when replying to the owner. include exact numbers and status. avoid guarantees, hype, and unsupported claims.

## forbidden shortcuts

- no “money hack” or guaranteed-profit claim
- no disabling risk gates just to create trades
- no silent db wipe
- no unverified “pushed successfully” claim
- no bulk repository changes without showing scope
- no strategy regression disguised as a documentation change

## source of truth

when documents conflict with runtime, runtime evidence wins for current status; git history wins for committed source; explicitly explain discrepancies.

last reviewed: 2026-08-03
safety model: paper-only, fee-aware, evidence-first
