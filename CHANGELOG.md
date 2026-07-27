# Changelog — Project Vaiśravaṇa

## v0.0.25 (2026-07-27) — Robustness P1+P2: walk-forward + stat gate + vol sizing + self-loop + cutover
Repo-only commit (NO auto-deploy — human-gated cutover per plan).

- **P1-33 walk-forward OOS** (`src/walk_forward.py`): rolling train→test folds over
  a candle series; each fold scores ONLY its test window (train skipped) so the edge
  is proven on data the candidate never saw. Reuses `BacktestHarness` (same fees,
  same SL/TP derivation as production). Demo: `scripts/run_walk_forward.py` (runs on
  real `data/klines/*.json` when present; synth offline otherwise).
- **P1-34 statistical promotion gate** (`src/promotion_gate.py`): the Sentinel now
  promotes ONLY with a sample floor (≥50 OOS trades) AND a significant NET expectancy$
  edge (Wilson-style CI whose lower bound clears baseline + a min economic edge).
  Fixes F4: a candidate can no longer "win" on noise (e.g. the ~12-trade SELL sample).
  Falls back to raw R only when net$ is unmeasured (legacy). Wired into
  `Sentinel.cycle` + `ShadowComparison.statistical_promotable`.
- **P2-35 vol-targeted sizing** (`src/sizing.py`): `regime_leverage()` scales leverage
  DOWN in high-vol regimes / wide-SL setups so a 1-SL move costs a similar fraction of
  equity (fixes F5: thin margin + fixed 2x = tail wipeout). Bot entry path now sizes
  with the vol-targeted leverage and hard-caps SL risk at 5% of equity.
- **P2-36 closed self-improvement loop** (`Sentinel.sanity_check`/`revert`/
  `promote_guarded`): a promoted surface is auto-reverted if it is degenerate (R:R
  floor broken, weight collapsed, weights≠1, leverage out of band) before it can reach
  live trading. Bounded diff (apply_proposal) already guards per-cycle changes.
- **P2-37 human-gated live cutover** (`src/cutover_gate.py`): LIVE deploy is impossible
  without explicit human approval. `CutoverGate` records request→approve→reject in the
  DB; `deploy.py` now refuses `flyctl deploy` unless `can_deploy()` is True (refuses by
  default if the gate is unreadable). PAPER promotion stays autonomous.
- Docs: `REVIEW-ROBUSTNESS-2026-07-27.md`, `PLAN-ROBUSTNESS.md`.
- Tests: phase33 (walk-forward), phase34 (promotion gate), phase35 (sizing),
  phase36 (self-loop/revert), phase37 (cutover + deploy-gate). Full suite **294 passed**.

## v0.0.24 (2026-07-27) — Robustness P0: R:R lock + net-expectancy + SELL maturity
Repo-only commit (NO auto-deploy — human-gated cutover per plan).

- **P0-30 R:R floor lock** (`src/rr_scan.py`): boot self-check scans ALL open
  trades; any with realized R:R < 2:1 is flagged, alerted to Telegram, and the
  offending pair is blocked from NEW entries until repaired (open positions stay).
  `assert_rr_floor` gives a hard fail-loud path. Regression test mirrors the
  2026-07-27 BTCUSDT 1m 1.50:1 transient.
- **P0-31 net-expectancy re-base** (fixes F1 R-distortion): `evaluation.evaluate`
  now computes NET expectancy$ (after fees) and adds a `net_expectancy` pass
  guard; new `net_pair_ranking()` ranks pairs by net$ so tight-SL pairs can no
  longer inflate a naive R-multiple ranking. `PairExcluder` now excludes on NET
  expectancy$ (real money) when a DB is available, keeps the W/L fallback for
  standalone use. `trade_logs.fees_usd` column added via a safe `ALTER TABLE`
  migration; the live bot now persists realistic VIP0 fees (entry 0.02% / exit
  0.05%) on every close so net expectancy is real, not assumed.
- **P0-32 SELL maturity gate** (`src/side_maturity.py`): a side is MATURE only
  after `min_trades` (50) samples AND a stable Wilson 95% CI (half-width < 0.20).
  Immature SELL (only ~12 trades / <3h live) is excluded from promotion /
  exclusion math and labeled IMMATURE — no false "SELL broken/works" conclusions.
- Docs: `REVIEW-ROBUSTNESS-2026-07-27.md`, `PLAN-ROBUSTNESS.md`.
- Tests: `test_phase30_rr_floor_lock.py`, `test_phase31_net_expectancy.py`,
  `test_phase32_side_maturity.py` (+ lifecycle/close fee path). Full suite
  **273 passed**.

## v0.0.23 (2026-07-27) — Honor owner R:R≥2:1 mandate + de-bleed + SELL balance
- **T1 R:R≥2:1 (CRITICAL):** `ParameterSurface` now enforces a HARD floor validator `tp_atr_mult/sl_atr_mult ≥ 2.0`. Active PAPER default 1.5:1 → **2:1** (break-even WR 40%→33.3%). Owner mandate "1 win recovers 2 losses" is now in code, not by hope.
- **T2 pair de-bleed:** new `PairExcluder` skips pairs with rolling WR < 40% over ≥10 trades; re-includes on recovery ≥50%. Persisted to `/data/exclusions.json`. Measured: removes 6 bleed pairs, lifts aggregate WR **46%→58%** with zero logic risk.
- **T3 SELL un-suppression:** new `SideBalancer` tracks BUY/SELL entry share; nudges SELL threshold down (clamped at watch band) when SELL < 25%. Opens the suppressed short half (was 10:1 BUY:SELL).
- Docs: `45-comprehensive-strategy-review.md` (full factor inventory, measured) + `PLAN_v0.0.23.md`.
- 19 new tests (T1/T2/T3), all green.

## v0.0.22 (2026-07-27) — Regime-adaptive weights + Telegram commands + SMC gate
- **Regime-adaptive weights** — ADX-driven factor mix:
  - ADX < 25 (range): trend 30→20%, momentum 20→15%, structure 15→25%, liquidity 10→15%
  - ADX > 40 (trend): trend 30→35%, momentum 20→25%, structure 15→10%, liquidity 10→5%
  - Default: standard 30/20/15/15/10/5/5
- **8 Telegram commands added:** /positions, /pairs, /config, /exclude, /include, /reload
  alongside existing /health /clean /stop — all registered via setMyCommands
- **SMC neutral gate** — in neutral HTF, requires pullback_to_anchor OR liq_sweep before entry
- **Hot-config reload** via /reload command (re-reads surface JSON without restart)
- **adaptive_weights()** in src/engines.py (pure, testable)
- REVIEW_v0.0.21.md with full acceleration plan

## v0.0.21 (2026-07-27) — Profile-specific EMAs + context caching
- **Profile-specific EMA periods** (THE timeframe mismatch fix):
  - Scalp (1m, hold 15m): EMA5/15 → ~15 min signal matches hold time
  - Day (15m, hold 4h): EMA20/50 → 12.5h signal (unchanged)
  - Swing (1h, hold 48h): EMA50/200 → ~200h signal slow enough for swings
  - Each strategy now has its OWN htf_bias from profile-appropriate EMA periods
- **Context caching** — BTC/dominance data refreshed every 5 min (not every 60s).
  Reduces HTTP requests from 270/cycle to ~3/cycle. Makes context actually work.
- **Unified EMA tolerance** — both bot_paper.py and marketcontext.py now use 0.08%.
- **build_context_for() refactored** — split into cached (fast) and raw (fetch) paths.
- +CROSSCHECK_v0.0.20.md documenting 8 blind spots found in deep audit.

## v0.0.20 (2026-07-27) — Hierarchical HTF direction gate (retracement trap fix)
- **Replaced the flat `or` direction gate with a strict 5-layer hierarchy:**
  1. Pair's own HTF (15m EMA20/50) must agree with trade side — PRIMARY signal
  2. Higher TF (1h/4h EMA20/50) must NOT disagree — **prevents the retracement trap**
  3. BTC leader only overrides DOWN (never up)
  4. Risk regime only overrides DOWN (never up)
  5. Neutral HTF requires pullback confirmation
- **Result:** BUY is blocked unless BOTH the pair's 15m AND the 1h/4h trends support it.
  No more "BTC said bullish so BUY passes" — the pair's own trend is the primary gate.
- **ADX moved to structural TF** (15m/1h instead of 1m) — 1m ADX was too noisy.
- **ADX threshold raised to 25** (was 20) — stronger trend required.
- **+16 updated tests** in test_phase25_entry_gate.py covering all 5 layers.
- Root cause analysis in docs/PLAN_v0.0.20.md.
- Fixes retracement trap — BUY blocked unless higher TF context agrees.

## v0.0.19 (2026-07-27) — Full improvement package (ADX, vol-SL, cooldown, trailing stop, per-side threshold)
- **Tier 1: Directional fix deployed** — v0.0.18 entry_allowed gate (BUY blocked in bearish regime, pullback confirmation) live for the first time with SELL dominance.
- **Tighter side-bleed floor** (−0.10R from −0.05R) via `SIDE_EXP_FLOOR_R` — catches directional bleed faster.
- **ADX trend strength filter** — `compute_adx()` + `adx_allowed()` blocks entries when ADX < 20 (weak/choppy trend = MAXHOLD risk). Degenerate data passes through.
- **Volatility-adaptive SL** — `volatility_scale()` widens SL for high-vol pairs (memes), tightens for low-vol pairs (BTC/ETH). Computed as sqrt(pair_ATR% / median_ATR%). Clamped [0.7, 1.5].
- **Per-side entry threshold** — BUY requires +0.03 (configurable `SIDE_THRESHOLD_ADJ`) higher threshold in non-bullish regime; SELL requires +0.03 higher in bullish regime. Auto-rebalances entry bias.
- **Trailing stop at +0.5R** — when a trade reaches +0.5R unrealized, SL is moved to break-even. Converts MAXHOLD expiries into partial wins.
- **Post-SL cooldown** — after an SL hit on (pair, side), skip the next 3 entries (configurable `SL_COOLDOWN_TICKS`). Prevents revenge re-entry into the same losing setup.
- **Pair-level sizing** — `PAIR_WEIGHTS` reduces notional by 50% on weak pairs (SOL, WLD, BONK, ETH) and 40% on below-average pairs (TAO, BTC, PUMP) based on live data. Configurable via `VAISRAVANA_WEAK_PAIRS` / `VAISRAVANA_BELOW_AVG_PAIRS`.
- **+20 tests** (tests/test_phase26_v019.py) — ADX calc, vol scale, per-side gate, cooldown integration → 231 passing.
- Full evaluation v2 in `docs/EVALUATION_v2.md`.

## v0.0.18 (2026-07-26) — Directional + expectancy entry gate (the WR fix)
- **Core win-rate fix** (eval showed 36.7% WR / −1.75R; BUY was 23.7% / −8.78R):
  - New `entry_allowed(state, side, sc, sexp)` gate (pure + TDD, 7 tests):
    1. **Side-bleed block** — a side with ≥20 samples and negative expectancy is blocked
       (keeps the v0.0.16 idea, re-expressed as a single gate).
    2. **Directional regime filter** — BUY only in a bullish regime (htf_bias/btc_bias/
       risk_regime); SELL only when NOT bullish. Kills the long-bias-into-downtrend bleed.
    3. **Pullback confirmation** in a neutral regime — no chasing extremes without a
       `pullback_to_anchor`.
  - Replaces the weaker v0.0.16 side-bleed gate in `_decide_tick`; gated decisions are
    persisted to `decisions_log` as `GATED` (audit trail complete).
- **Evaluation** written to `docs/EVALUATION.md` (full live-DB breakdown + root-cause +
  improvement plan). Bot stopped (machine `78475e3ce4dd58` halted); caretaker cron removed
  itself after committing the eval doc.
- **+7 tests** (tests/test_phase25_entry_gate.py) → 211 passing.

## v0.0.17 (2026-07-26) — Telegram `/stop` + `/health` commands + decisions_log persistence
- **Owner slash commands (owner ask):**
  - `/stop` — graceful halt: sets a control flag, the main loop exits at end of the
    current cycle, sends a 🛑 confirmation card. Durable stop via `flyctl machine stop`.
  - `/health` — full status card: overall WR + expectancy + PnL, by-side / by-tf / by-pair
    breakdown (worst/best pairs), open/closed counts, DB size, and last 8 trades.
  - `/clean` — retained (v0.0.16): wipe DB + clear all cooldown/kill/loss state, fresh start.
  - Dispatched via the existing `TelegramCommandListener` (chat-gated, daemon thread).
- **decisions_log persistence fix:** `_decide_tick` now writes every evaluated decision
  (WATCH/SKIP/SUPPRESSED/ENTRY) to `decisions_log` (the caretaker noted it was empty since
  the v0.0.10 multi-strategy rewrite). `_persist_decisions_log` added; serializes scores
  safely (as_dict / str fallback) so a non-JSON-able sub_scores object can't break the loop.
- **+4 tests** (tests/test_phase24_stop_health.py) → 204 passing.

## v0.0.16 (2026-07-26) — `/clean` slash command (wipe + fresh start)
- **Owner slash command `/clean`** (owner ask). The bot was send-only; added a
  `TelegramCommandListener` (daemon thread, `getUpdates` poll, chat-gated to NOTIFY_CHAT_ID)
  that dispatches `/clean`. On `/clean` the bot:
  - wipes the entire telemetry DB (`db.wipe_db` → DELETE all rows from trade_logs /
    decisions_log / results_log / exec_events / system_health, keeps schema),
  - clears ALL in-memory cooldown/loss/kill state: `KillSwitch` cooldowns+streaks+tripped,
    `realized_loss_today`, `open_trades`, `monitor.positions`, `PaperSimExchange._prices`,
  - removes the caretaker cron state file (`.vaisravana_cron_state.json`) so it may re-tune
    immediately,
  - reloads zero open positions next loop → **blank win rate, true fresh start**.
  Sends a 🧼 confirmation card. Safe: PAPER-only, owner-chat-gated, no live path touched.
- **+6 tests** (tests/test_phase23_clean.py) → 199 passing.

## v0.0.15 (2026-07-26) — losing-side expectancy gate + WATCH spam fix
- **Losing-side gate (owner ask: WR 26% + spam).** `TradeLifecycle.side_expectancy(side)`
  returns rolling ΣR over last-30 closed trades per side. `_decide_tick` now SUPPRESSES
  ENTRY on a side whose recent expectancy is negative (≥20 samples, floor −0.05R). The
  live data showed BUY at 16% WR / −14R while SELL was +1.97R — this stops the bleed
  without an irrational 85% gate. Re-evaluated every tick, so it unblocks when the side
  recovers. Tunable: `VAISRAVANA_SIDE_MIN_SAMPLES` (def 20), `VAISRAVANA_SIDE_EXP_FLOOR` (def −0.05).
- **WATCH spam fixed.** Previously every pair×strategy emitted its own WATCH card
  (~45/min). Now WATCH/SUPPRESS decisions are batched into ONE per-cycle card, and only
  near-threshold rows (within 0.06 of the entry bar) are kept. ENTRY/FILL/CLOSE/PR cards
  are unchanged (they're meaningful).
- **+4 tests** (tests/test_phase22_sidegate.py) → 193 passing.

## v0.0.14 (2026-07-26) — fix loss_book NameError in close handler
- **BUG FIX:** `loss_book → realized_loss_today` in `run()` close handler (line 401-402).
  The close handler referenced `loss_book` which was only a parameter name in `_decide_tick`,
  not defined in `run()` scope → `NameError: name 'loss_book' is not defined` every time
  a trade closed at a loss. Now correctly uses the `realized_loss_today` dict.
- **TEST:** 3 new tests for `_close()` — loss accumulation, win not debited, None-safe.

## v0.0.13 (2026-07-26) — fix CloseEvent missing tf+side (loop error)
- **BUG FIX:** PositionMonitor CloseEvent init was missing `tf` and `side` fields,
  causing a recurring `AttributeError` every time a SL/TP was hit in PAPER mode.
  The rest of the loop expected `ev.tf` and `ev.side` to exist when looking up
  the open_trades key. Fixed by including both in the event.

## v0.0.12 (2026-07-26) — test health_clean coverage
- **COVERAGE:** 5 new unit tests for `health_clean()` — empty list, PASS-only,
  FAIL-only, outside-window, mixed — ensuring the kill-switch auto-reset path is
  regression-safe.

## v0.0.11 (2026-07-26) — decisions_log 1-day auto-prune
- **DB auto-prune (owner ask):** `decisions_log` (the most-spammed table — one row per
  pair×strategy per 60s tick, ~65k rows/day) is now pruned of rows older than 1 day.
  - `db.purge_old_decisions()` deletes via `datetime(ts) < datetime('now','-1 days')`
    (column wrapped in datetime() because the stored ISO `ts` carries a `+00:00` suffix
    that breaks a raw string compare), then VACUUMs to reclaim space.
  - Wired at two points: on **boot** (immediate trim) and at the **UTC-midnight daily roll**
    (with a 🧹 Telegram card reporting rows deleted). Trade/exec logs are kept — they drive
    evaluation + promotion, so only the decision audit trail is pruned.
- **+4 tests** (tests/test_phase21_prune.py) → 180 passing.

## v0.0.10 (2026-07-26) — ACTIVE MULTI-STRATEGY OVERHAUL
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
