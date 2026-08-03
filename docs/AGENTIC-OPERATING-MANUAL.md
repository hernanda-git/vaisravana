# agentic operating manual — vaisravana main bot

## purpose

this manual defines how an autonomous coding/research agent should work on the main bot without hallucinating runtime state, silently regressing performance, or confusing repositories.

## evidence hierarchy

1. direct runtime evidence: docker inspect, docker logs, sqlite queries, verified telegram/http responses
2. deployed source: `/opt/bots/vaisravana`
3. committed source: `/root/vaisravana-workspace/vaisravana`
4. git history and changelog
5. agent memory and prior reports
6. assumptions

memory is context, not proof of current runtime state.

## report format

for each claim, label it mentally as:

- observed: exact command output supports it
- derived: calculated from observed data; show formula
- hypothesis: plausible but unconfirmed
- remaining: action still required

example:

```text
observed: 21 closed trades, gross pnl 0.0672, fees 0.0464
computed: net pnl = 0.0672 - 0.0464 = 0.0208
not proven: durable profitability; sample is too small
```

## performance evaluation

always calculate:

- closed trades and open trades
- wins, losses, win rate
- gross pnl
- total fees
- net pnl after fees
- balance relative to starting balance
- profit factor: gross positive pnl / absolute gross negative pnl
- expectancy per closed trade
- maximum drawdown and losing streak
- side, pair, and exit-reason breakdown

never substitute win rate for profitability. partial exits must be accounted for exactly once and must not be double-counted as full trades.

## autonomous loop

### observe

inspect the relevant bot only. record container status, image/source version, environment risk values without exposing secrets, db counts, latest timestamps, and recent errors.

### diagnose

reproduce the issue with the smallest direct query or test. distinguish a real failure from an old log, stale table, wrong database path, or another bot's output.

### change

make the smallest safe change. do not modify strategy weights or thresholds while diagnosing telemetry. preserve current paper db and record rollback path.

### verify

compile, run targeted tests, run full tests if present, deploy only when needed, verify startup, verify recent activity, and compare deployed files with source files.

### record

update changelog and relevant docs with what changed, why, evidence, limitations, and rollback. commit focused changes. push only after remote authentication is verified.

## telegram verification

an http 200 from `sendMessage` proves the telegram api accepted the request, not that a human saw the intended card content. notification tests must render the message and inspect that it contains:

- open: direction, pair, entry, sl, tp, fee, balance, margin, pnl
- close: direction, pair, exit, reason, r, gross/net pnl, fee, balance
- partial: explicit partial label, closed size, remaining size, remaining sl

## git workflow

```bash
git status --short --branch
git diff --check
python3 -m compileall -q src scripts/bot_paper.py
python3 -m pytest -q
git add <reviewed-files>
git commit -m "<focused message>"
git push origin main
```

if push fails due to missing credentials, leave the commit intact and report:

- commit hash
- branch and ahead/behind state
- remote url
- exact authentication failure
- no claim of successful push

## monitoring interpretation

universe refresh proves market data/ranking activity. decisions-log freshness proves decision audit persistence. exec-events freshness proves simulated execution events. system-health freshness proves health telemetry. these are separate signals and must not be conflated.

if one table becomes stale while another advances:

1. inspect the database file and wal/shm timestamps
2. query the stale table directly
3. inspect the exact write function and exception handling
4. check logs at debug/error level
5. test a write in a temporary database
6. only then patch production code

## remaining main-bot work

Standalone research signals are feature-flagged and paper-only. CVD divergence is
implemented as a pure candidate helper in `src/alpha_signals.py`; regime-adaptive
TP is enabled only with `VAISRAVANA_REGIME_ADAPTIVE_TP=1`. These helpers do not
place orders and the default behavior remains unchanged until an A/B sample proves
fee-adjusted improvement.

1. expose `_persist_decisions_log` failures at warning level with a rate limit and error category. (warning-level rate limiting is now implemented; freshness metrics remain.)
2. add a telemetry freshness check for each table.
3. synchronize source workspace and deployed tree through an explicit build/deploy command.
4. push the latest standalone research commit after github auth is restored.
5. collect at least 50 clean paper trades before strategy tuning.
6. compare fee-adjusted net expectancy against the preserved baseline.
7. do not enable live mode based on this sample.

## autonomous guardrails

- no destructive commands without explicit confirmation unless the user explicitly delegated autonomy for that exact scope
- no real-money trading
- no credential extraction or logging
- no cross-bot edits
- no fabricated test counts or deployment claims
- no “guaranteed growth” language

last updated: 2026-08-03
