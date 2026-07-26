# Changelog — Project Vaiśravaṇa

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
