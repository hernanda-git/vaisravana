# Project Vaiśravaṇa 🔱

> PAPER-mode crypto-futures trading bot (Binance USDT-M) — multi-strategy, expectancy-first,
> owner-controlled. Named for the Buddhist deity of wealth (and the northern guardian-king
> who *listens* — fitting, since this bot is driven by owner Telegram commands).

**Status (2026-07-26):** v0.0.18 — bot **stopped** (machine halted) while improvements land.
211 tests green. Live eval showed a 36.7% WR / −1.75R; the v0.0.18 directional+expectancy
gate is the fix (see `docs/EVALUATION.md`).

---

## ⚠️ Safety boundary (non-negotiable)
- **PAPER ONLY.** Fills are simulated by `PaperSimExchange`. There is **no live order path**
  except behind `LiveGuard.assert_entry_allowed()`, which *raises* unless a human has
  explicitly approved LIVE mode. Never set `VAISRAVANA_LIVE=1` without that approval.
- All owner commands are **chat-gated** to `NOTIFY_CHAT_ID` (the bot ignores other chats).
- The promotion gate (surface → live) is **human-approved** by design.

---

## Architecture

```
scripts/bot_paper.py        main loop: boot, multi-strategy tick, Telegram listener, /stop control
src/engines.py              MarketState (MTF bias, regime, pullback) + build_state_mtf
src/strategy.py             StrategyEntry + evaluate_strategy() (scores BUY & SELL per profile)
src/lifecycle.py            TradeLifecycle: open/close, win%, rolling side_expectancy()
src/safety.py               KillSwitch (daily-loss + feed-health, cooldowns/streaks)
src/db.py                   SQLite: trade_logs / decisions_log / results_log / exec_events
src/telegram_bot.py        TelegramNotifier (cards) + TelegramCommandListener (getUpdates poll)
src/config.py               StrategyProfile (entry bar, SL/TP mults) + ParameterSurface
src/symbols.py              DEFAULT_UNIVERSE (15 pairs) + resolve_symbol()
```

### Strategies (concurrent, keyed by `(pair, decision_tf, side)`)
| Profile | Decision TF | Hold | Style |
|---|---|---|---|
| Scalping | 1m | ≤15m | momentum/pullback on 1m, 5m+15m context |
| Day | 15m | ≤4h | structural bias, 1h+4h context |
| Swing | 1h | ≤2d | trend, 4h+1d context |

### Entry gate (v0.0.18 — the WR fix)
`entry_allowed(state, side, sc, sexp)` must pass for any ENTRY:
1. **Side not bleeding** — ≥20 samples & negative expectancy ⇒ blocked.
2. **Directional regime filter** — BUY only in bullish regime; SELL only when not bullish.
3. **Pullback confirmation** in neutral regime — no chasing extremes.

### Decision persistence
Every evaluated decision (WATCH / SKIP / GATED / ENTRY) is written to `decisions_log`
(auto-pruned >1 day). `trade_logs` is kept for evaluation.

---

## Owner Telegram commands (chat-gated)
Send these to the bot from the owner chat (`NOTIFY_CHAT_ID`):

| Command | Effect |
|---|---|
| `/stop` | Graceful halt — loop exits at end of cycle, 🛑 card sent. Durable stop via `flyctl machine stop`. |
| `/health` | Full status: overall WR + expectancy + PnL, by-side/by-tf/by-pair breakdown, open/closed counts, last 8 trades. |
| `/clean` | Wipe DB + clear all cooldown/kill/loss state → fresh start (blank WR, no positions). |

Unknown commands are ignored. Non-owner chats are ignored.

---

## Local dev
```bash
cd /c/Workspace/vaisravana
.venv/Scripts/python -m pytest          # full suite (expect 211 passed)
flyctl deploy --app vaisravana          # deploy to Fly (PAPER)
flyctl machine stop 78475e3ce4dd58 --app vaisravana   # durable stop
```
Env (Fly secrets): `VAISRAVANA_PAPER=1`, `NOTIFY_CHAT_ID`, `TELEGRAM_BOT_TOKEN`,
`VAISRAVANA_PAIRS` (15), plus tunables `VAISRAVANA_SIDE_MIN_SAMPLES` (20) /
`VAISRAVANA_SIDE_EXP_FLOOR` (−0.05).

---

## Evaluation & docs
- `docs/EVALUATION.md` — full live-DB performance breakdown, root-cause, improvement plan.
- `docs/REVIEW-ROBUSTNESS-2026-07-27.md` — honest end-to-end robustness audit (what's solid, real fragilities, live numbers).
- `docs/PLAN-ROBUSTNESS.md` — phased TDD plan: P0 correctness/robustness → P1 validity (walk-forward + CI promotion gate) → P2 adaptiveness + closed self-loop.
- `CHANGELOG.md` — version history.
- `scripts/verify_activity.py` — empirical backtest harness (OLD vs NEW expectancy).

## Guardrails recap
- Win rate **56% is a FLOOR, not a target**. Real gates: expectancy > +0.10R, PF > 1.2, WR ≥ 56%.
- The old 85% WR gate was irrational (produced ~0 trades at R:R 1.5). Rejected.
- Caretaker cron (`vaisravana-overnight-careaker`) is **paused/removed** during eval work to
  avoid concurrent edits to the live tree.
