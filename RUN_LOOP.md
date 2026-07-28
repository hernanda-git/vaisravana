# Wave Engine — Autonomous Improvement Loop (RUN_LOOP)

This file is the standing operating procedure for the self-improving loop.
The loop runs autonomously (cron) on sera, iterating the wave trading engine
toward: **maximize long-term risk-adjusted balance growth, minimize
catastrophic loss.** Source of truth = recorded metrics, not opinion.

## Where things live (sera)
- Build context (live code): `/opt/bots/vaisravana-wave/`
- Git working copy (commit from here): `/opt/bots/vw_commit/`  (branch `vaisravana-wave`, remote `hernanda-git/vaisravana`)
- Eval DBs + wallet: container volume `bots_data` at `/data/`; copied to `/root/wave_eval_data/wave_runN.db`
- Engine source: `src/wave/*.py`  (bias, gate, manager, models, engine, db, feed, paper_wallet, scanner, structure, smczones, risk, telemetry)
- Router / Telegram commands: `scripts/bot_paper.py`

## One iteration (do ALL of these, in order)
1. **OBSERVE** — read `WAVE_LEARNING_LOG.md` (last iter + standing questions).
   Pull latest: `cd /opt/bots/vw_commit && git pull --rebase origin vaisravana-wave`.
2. **ANALYZE** — pick ONE standing question / hypothesis from the log.
   Prefer the highest-leverage, lowest-risk change. Never two big changes at once
   (can't attribute effect). Examples carried: directional balance (BUY must
   fire on up-tapes), TP/SL R-ratio, ATR TP validation, live bias distribution.
3. **IMPROVE** — edit the code in `/opt/bots/vaisravana-wave/src/wave/`.
   Keep changes minimal + explained. Re-sync to working copy:
   `rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' /opt/bots/vaisravana-wave/src/wave/ /opt/bots/vw_commit/src/wave/`
   `cp /opt/bots/vaisravana-wave/scripts/bot_paper.py /opt/bots/vw_commit/scripts/`
4. **DEPLOY + VALIDATE** — rebuild + run FRESH (must reset wallet+DB so the run
   is clean and comparable):
   ```
   cd /opt/bots
   docker compose stop vaisravana-wave
   docker compose run --rm --entrypoint sh vaisravana-wave -c "rm -f /data/paper_wallet.json /data/vaisravana-wave.db"
   docker compose build --no-cache vaisravana-wave
   docker compose up -d --force-recreate vaisravana-wave
   ```
   Let it run ~10-15 min, then capture:
   ```
   docker cp bots-vaisravana-wave:/data/vaisravana-wave.db /root/wave_eval_data/wave_runN.db
   docker logs --since 900s bots-vaisravana-wave | grep -ciE "WAVE OPEN"
   docker logs --since 900s bots-vaisravana-wave | grep -ciE "WAVE CLOSE"
   docker logs --since 900s bots-vaisravana-wave | grep -oE "reason=[a-z_0-9]+" | sort | uniq -c
   docker exec bots-vaisravana-wave cat /data/paper_wallet.json
   ```
   Increment N (run8, run9, ...). Record to `eval_data/`.
5. **COMPARE** — baseline vs new on: fee drag ($/min), opens/min, close-reason
   mix (want tp_hit + reversal > anchor_hit + max_age), win rate, avg R, final
   balance. A change is KEPT only if risk-adjusted outcome is not worse.
6. **LEARN + DOCUMENT** — append an `## ITER-N` block to `WAVE_LEARNING_LOG.md`
   with Hypothesis / Change / Test / Evidence / Verdict. Update standing
   questions.
7. **COMMIT + PUSH** (correct creds, every change):
   ```
   cd /opt/bots/vw_commit
   git add src/wave/ scripts/bot_paper.py WAVE_LEARNING_LOG.md
   git add -f eval_data/wave_runN.db
   git -c user.name="hernanda" -c user.email="hernanda@users.noreply.github.com" \
     commit -m "iter-N: <what>"
   git pull --rebase origin vaisravana-wave   # resolve if remote moved
   git push origin vaisravana-wave
   ```
8. **REPEAT** — never finished. Stop the bot only if balance hits 0 or you are
   about to make a risky change you want to gate; otherwise leave it running
   and let the next cron tick continue.

## Hard rules
- Always `build --no-cache` + `up --force-recreate`. A plain restart DOES NOT
  pick up code changes (cost hours once).
- Always reset wallet+DB before a measured run; never compare a fresh run to a
  stale wallet.
- Never commit `.env` tokens. `.env` is gitignored; only `.env.example` is safe.
- Creds for commit/push: user.name=hernanda, user.email=hernanda@users.noreply.github.com.
- If a change CRASHES the bot (no WAVE OPEN in 60s, or stack trace in logs),
  revert it, note the failure in the log, and try a smaller variant.
- Capital preservation first. If a run loses >30% of the $10 in <10 min, the
  change is rejected regardless of other metrics.

## Current standing questions (iter-3+)
1. Confirm MAX_WAVE_AGE_S=900 fires (default now 900; env override suspected
   not loaded). Observe close-reason mix.
2. Direction: are BUYs firing on up-tapes? Log live `bias.direction` per pair
   (add a periodic diagnostic line if needed) — verify the bot is not 88% SELL
   due to stale ema_15m.
3. TP quality: when a wave closes at tp_hit, does it pay >1R? Tune TP/SL ratio
   (currently SL=max(1%,1.8ATR), TP=max(1%,2ATR) floored at 1.2x risk).
4. Fee drag is now ~10x lower (iter-2) — survival is expectancy-limited, so the
   lever is direction + TP, not frequency.
