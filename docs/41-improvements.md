# doc 41 — Improvements Implemented (v0.0.6)

This document records the concrete fixes applied after the expert quant review
(`doc 40-quant-review.md`). Each item maps to a finding in doc 40.

## 1. Hard trading-mode boundary (doc 40 §6 / §7 — P0)

**Problem:** nothing in code prevented a live order; the only thing stopping real
fills was a comment ("There is no live order path"). `ModeGuard` did not exist.

**Fix:** `src/mode.py`
- `ModeGuard(mode)`: in `paper` it refuses any live adapter; in `live` it requires a
  real `Exchange` **and** a non-empty human-approval set.
- `assert_entry_allowed(pair, tf, side)` — raises `ModeBoundaryError` for any
  unapproved (pair,tf,side) in LIVE mode.
- `ModeGuard.exchange_for(live_exchange)` returns a `PaperSimExchange` in paper
  (no network) and a `GuardedExchange` in live (defense-in-depth: refuses any order
  on a symbol outside the approved set).
- `PaperSimExchange` satisfies the `execution.Exchange` protocol so the SAME
  `PositionMonitor` code path drives stops in paper and live.

**Wired in:** `scripts/bot_paper.py` reads `VAISRAVANA_MODE` (default `paper`), builds
`ModeGuard` + exchange + `PositionMonitor` at boot, and calls
`guard.assert_entry_allowed(...)` before every open.

## 2. Real per-tick stop protection (doc 40 §3 — P0)

**Problem:** the live loop only polled the 1m bar high/low vs SL/TP every ~60s and
never instantiated `PositionMonitor` or placed a stop via `execution.py`.

**Fix:** `bot_paper.py` now, every cycle:
- pushes the latest price into `PaperSimExchange`,
- drives `monitor.tick()` and closes any position the monitor exits
  (SL / TP / MAXHOLD / ORPHAN) — all reduceOnly.
- on open, calls `place_stop_loss` and hands the position to `PositionMonitor`
  (`sl_on_exchange=False` in paper so the monitor polls mark price; the sim exchange
  does not fill stops on its own).

## 3. Honest backtest (doc 40 §2 — P1)

**Problem:** `MAX_HOLD_BARS=1` turned every trade into a single next-bar gamble, and
the harness assumed a maker entry (0.02%) for the 1m "jump" cadence which is really a
taker.

**Fix:** `src/backtest.py`
- `MAX_HOLD_BARS = 60` default (≈1h on 1m), configurable per run.
- `BacktestHarness` now takes `surface`, `max_hold_bars`, and `fees=(entry,tp,exit)`;
  entry defaults to TAKER (realistic for the jump cadence), TP maker, SL/MAXHOLD taker.
- `scripts/run_backtest_honest.py` runs IN-SAMPLE vs OUT-OF-SAMPLE across 1m/5m/15m
  with HTF context and reports EXPECTANCY + PROFIT FACTOR (not just WR).

**Result (real klines, 1500 bars/series):** the strategy fires ~1 trade per 1500 bars
on every TF — a near-dead signal. This is the evidence that the "85% WR" story is
unvalidated (see doc 40 §2.2). The backtest is now honest; the strategy needs far more
history and a denser entry logic before promotion is meaningful.

## 4. Shadow replay that can actually improve (doc 40 §2.3 — P1)

**Problem:** `bot_paper._shadow_comparison` re-weighted *stored* sub-scores; re-weighting
cannot change a trade's win/loss, so shadow expectancy could never beat baseline → the
Sentinel's promote branch was unreachable.

**Fix:** `src/shadow.py` + `bot_paper.research_loop` now call `shadow.shadow_compare`
which re-simulates the FULL pipeline on raw candles (`BacktestHarness`) with each
candidate `ParameterSurface`. Shadow can now genuinely beat baseline, so promote/rollback
is a real decision.

## 5. Decision attribution leak (doc 40 §3 — P2)

`src/decision.py`: `decide()` now returns `side=None` on non-ENTRY decisions (was leaking
the scoring side onto SKIP/WATCH), preventing corrupted trade attribution.

## Tests added

`tests/test_phase14_mode_shadow.py` (13 tests, all green) covering:
- mode boundary (paper refuses live adapter; live requires approval+adapter; invalid mode),
- `PositionMonitor` + `PaperSimExchange` (SL/TP/maxhold fire on mark price; position marked closed),
- `place_stop_loss` returns a valid `StopLossState`,
- honest shadow replay runs and returns a comparison,
- `MAX_HOLD_BARS == 60`.

Full suite: 118 tests passing.

## What is deliberately NOT done (still human-gated)

- **Going live.** `ModeGuard` makes it structurally impossible without a real `Exchange`
  adapter + human approval set. No live adapter is shipped — by design.
- **Validating the edge.** The honest backtest shows the signal is near-dead on real data.
  Promotion logic exists but should not be exercised until a denser, OOS-stable edge exists.
