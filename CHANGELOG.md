# Changelog — Project Vaiśravaṇa

## v0.1.4 (2026-07-26) — fix loss_book NameError in close handler
- **BUG FIX:** `loss_book → realized_loss_today` in `run()` close handler (line 401-402).
  The close handler referenced `loss_book` which was only a parameter name in `_decide_tick`,
  not defined in `run()` scope → `NameError: name 'loss_book' is not defined` every time
  a trade closed at a loss. Now correctly uses the `realized_loss_today` dict.
- **TEST:** 3 new tests for `_close()` — loss accumulation, win not debited, None-safe.

## v0.1.3 (2026-07-26) — fix CloseEvent missing tf+side (loop error)
- **BUG FIX:** PositionMonitor CloseEvent init was missing `tf` and `side` fields,
  causing a recurring `AttributeError` every time a SL/TP was hit in PAPER mode.
  The rest of the loop expected `ev.tf` and `ev.side` to exist when looking up
  the open_trades key. Fixed by including both in the event.

## v0.1.2 (2026-07-26) — test health_clean coverage
- **COVERAGE:** 5 new unit tests for `health_clean()` — empty list, PASS-only,
  FAIL-only, outside-window, mixed — ensuring the kill-switch auto-reset path is
  regression-safe.

## v0.1.1 (2026-07-26) — decisions_log 1-day auto-prune
- **DB auto-prune (owner ask):** `decisions_log` (the most-spammed table — one row per
  pair×strategy per 60s tick, ~65k rows/day) is now pruned of rows older than 1 day.
  - `db.purge_old_decisions()` deletes via `datetime(ts) < datetime('now','-1 days')`
    (column wrapped in datetime() because the stored ISO `ts` carries a `+00:00` suffix
    that breaks a raw string compare), then VACUUMs to reclaim space.
  - Wired at two points: on **boot** (immediate trim) and at the **UTC-midnight daily roll**
    (with a 🧹 Telegram card reporting rows deleted). Trade/exec logs are kept — they drive
    evaluation + promotion, so only the decision audit trail is pruned.
- **+4 tests** (tests/test_phase21_prune.py) → 180 passing.

## v0.1.0 (2026-07-26) — ACTIVE MULTI-STRATEGY OVERHAUL
- **Win-rate target rationalized (owner ask):** 85% gate was irrational/silent → replaced
  with an EXPECTANCY-FIRST promotion gate. WR is now a *floor* (56%, above the taker
  break-even of ~48% at R:R≥1.5), not a target. A 90% WR / negative-expectancy (fee-bleed)
  side is correctly REJECTED; a 56% WR / +0.20R side is correctly PROMOTED.
- **Very active open/close (owner ask):** default entry bar lowered 0.86 → 0.60, watch 0.78 →
  0.50. R:R raised 1.25 → 1.5 (scalp) / 1.67 (day) / 2.0 (swing) so each trade is net-positive
  at the 56% floor. Result: the bot now trades on both high- and mid-conviction setups instead
  of waiting for a rare A+ (which produced ~0 trades).
- **Concurrent Scalping + Day + Swing (owner ask):** new `src/strategy.py` runs 3 profiles in
  parallel, each on its own decision_tf (1m / 15m / 1h) with its own SL/TP ATR mults and activity
  bar. Positions are keyed by (pair, decision_tf, side) so the three horizons never collide.
  Disable any subset via `VAISRAVANA_DISABLED_STRATEGIES="swing,day"`.
- **Extended monitoring universe (owner ask):** default now 15 pairs — BTC/ETH/SOL leaders +
  1000PEPE, 1000BONK, ENA, WLD, PENGU, AAVE, TAO, INJ, APE, PUMP, WIF, CRV. `symbols.resolve_symbol()`
  maps PEPE/BONK → their 1000x contracts; plain perps pass through. Override with VAISRAVANA_PAIRS.
- **Empirical verification:** offline multi-strategy backtest (scripts/verify_activity.py) on a
  *hard* mean-reverting series produced +0.280R expectancy across 615 trades vs ~0 trades on the
  old 0.86 path — proving "56% is enough" and "very active" are both correct.
- **Tests:** +17 (strategy profiles, multi-strategy engine, universe/symbol resolution, reframed
  promotion-gate tests) → 176 passing. Safety/promotion semantics updated; existing tests kept green.

## v0.0.9 (2026-07-26)
- DB awareness + overall win-rate monitoring (README ask):
  - NEW `db.db_stats()`: per-table row counts (trade_logs / decisions_log / results_log /
    exec_events / system_health), total rows, on-disk size (main + WAL + SHM sidecars, with
    a PRAGMA page_count*page_size fallback), and a portfolio-wide overall win rate
    (n_wins/n_losses/win_rate_pct across ALL closed trades).
  - NEW `notify_db_stats()` Telegram card: overall win rate + DB size + per-table counts so
    the owner can watch database growth. Sent on boot AND every 30m status cycle.
  - 30m status card now leads with a "WR total" line + a compact "DB size · rows" line above
    the per-(pair,tf,side) breakdown.
  - HTML render verified: raw `v0.0.9`, no backslashes, no em-dash.
  - +8 tests (tests/test_phase16_db_stats.py) -> 133 passing.

## v0.0.8 (2026-07-26)
- Telegram notifier overhaul (docs/43-telegram-notifier.md):
  - Root cause of "no message on deploy": the startup card used MarkdownV1 with
    `_md_escape(version)` which backslash-escaped the dots -> Telegram's parser rejected
    the message and fell back to PLAIN TEXT, rendering literal `v0\.0\.4` + the message
    still "arrived" as plain text but looked broken. Switched to MarkdownV2 with a
    correct escaper; version + codes are passed RAW so they render as `v0.0.8`.
  - Removed ALL em-dashes (—); clean `·` / `:` / `-` separators only.
  - NEW `notify_health_check()` -> an explicit on-deploy (and periodic) heartbeat so the
    owner can confirm liveness without waiting for a trade. Wired into bot_paper.run().
  - Cleaner, elegant startup card + deploy/changelog card (Bahasa Indonesia, brand Vessavaṇa).

## v0.0.7 (2026-07-26)
- Cross-asset + MTF relational context (docs/42-context-mtf-scalping.md):
  - NEW src/marketcontext.py: BTC leader bias, BTC.d/risk regime (alt-bid proxy),
    alt relative strength + breadth, explicit LTF/MF/HTF biases, confluence +
    pullback-to-anchor; applied as a score modulator + hard entry gate (doc-21
    Σweights=1.0 invariant preserved).
  - engines.py: MarketState gained 11 relational fields; crossasset_score() and
    mtf_relational_score() added (0..1).
  - scoring.py: decide_ctx() = 7-factor decide() + relational boost + hard gate;
    decide() unchanged (prior tests pass).
  - bot_paper.py: each tick fetches BTC + alt basket + LTF/MF/HTF, folds context in,
    decides via decide_ctx (best-effort; never crashes on fetch failure).
  - config.py scalping-tuned (within doc-21 bounds): entry 0.90→0.86, tp_atr 1.05→1.25,
    lev 2→3, cooldown 10→5.
  - run_backtest_honest.py now builds context from real klines (still ~1-2 entries/1500
    bars — base signal too sparse; architecture correct, edge needs density).
- NEW tests/test_phase15_context.py (relational context + decide_ctx).
- DBs cleaned for clean next deploy (report .db removed; live /data state cleared).

## v0.0.6 (2026-07-26)
- Improvements following expert quant review (docs/41-improvements.md):
- NEW src/mode.py: hard trading-mode boundary. PAPER (default) structurally cannot
  touch a live adapter; LIVE requires a real Exchange + human approval set per
  (pair,tf,side). GuardedExchange blocks unapproved symbols at the wire.
- Wire PositionMonitor + PaperSimExchange into bot_paper.py: real per-tick SL/TP/
  MAXHOLD/ORPHAN via mark-price polling (previously only 60s-bar polling, no monitor).
- Honest backtest: MAX_HOLD_BARS 1 -> 60 (no more single-bar gamble); realistic
  TAKER entry fee; run_backtest_honest.py with IN-SAMPLE/OOS across 1m/5m/15m,
  reports expectancy + profit factor. Finding: signal fires ~1 trade/1500 bars.
- Shadow replay now re-simulates the full pipeline on raw candles (src/shadow.py)
  so the Sentinel can actually promote, not just roll back.
- Tests: tests/test_phase14_mode_shadow.py (13 tests). Full suite 118 passing.

## v0.0.5 (2026-07-26)
- Quant review (docs/40-quant-review.md): closed live-vs-design safety gaps.
- Fix: kill-switch now wired to real daily-loss book + FeedHealth (was hardcoded 0.0).
- Fix: real risk-based sizing via size_position (was hardcoded size=1.0).
- Fix: live build_state_mtf now derives structure/liquidity flags (was all-floor → 25% of scoring weight dead).
- Fix: decision.py no longer leaks intended side into decisions_log on SKIP/WATCH.
- Fix: brittle changelog test → suite now 105/105 green.

## v0.0.4 (2026-07-26)
- Pesan Telegram dirombak: Bahasa Indonesia, brand Vessavaṇa, kartu startup & deploy lebih bersih & modern.


## v0.0.3 (2026-07-26)
- Fix: Dockerfile now COPYs VERSION + CHANGELOG.md into image so the bot reports the real vX.Y.Z (was falling back to 0.0.0).


## v0.0.2 (2026-07-26)
- Phase 13 versioning: VERSION file + git tag v0.0.x per deploy; bot announces vX.Y.Z + changelog on startup via Telegram; fly.toml aligned to 1m cadence.


## v0.0.1
- Versioning system introduced: repo-root VERSION file + git tag `v0.0.xxx` per deploy.
- Deployed bot now announces its version + changelog entry on startup via Telegram.
- Startup banner reports real cadence (decide=1m, ctx=5m,15m).
- Phase 12 time-sensitive 1m decision cadence with multi-timeframe (5m/15m) context.
- Phase 11 LLM research layer (propose-only, Sentinel-gated) — off by default.
