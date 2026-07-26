# Implementation Status — 2026-07-26

All 10 plan phases implemented, tested, and pushed. **105 tests passing** (all mocked/offline; no live calls anywhere in the test suite).

## Phase map → code

| Phase | Deliverable | Module(s) | Tests |
|-------|-------------|-----------|-------|
| 0 | Repo skeleton, ParameterSurface (doc 21 bounds via pydantic), 5-table telemetry schema (doc 30 §4) | `src/config.py`, `src/db.py` | 11 |
| 1–2 | Symbol registry + filters, 9 engines, dual LONG/SHORT scoring, 5W1H reasoning | `src/symbols.py`, `src/engines.py`, `src/scoring.py`, `src/reasoning.py`, `src/marketdata.py`, `src/gate.py` | 30 |
| 3 | Two-layer gate (A cheap pre-check → B hard) + decision orchestrator → `decisions_log` | `src/decision.py` | 10 |
| 4 | Execution: tick/step filter rounding, sizing, validate/repair/resubmit-once, OrderManager no-chase, dual-mechanism SL, 10s position monitor | `src/execution.py`, `src/monitor.py` | 17 |
| 5 | Trade lifecycle (all timestamps), win/loss on EVERY trade, rolling WR per (pair,tf,side), fail-loud telemetry | `src/lifecycle.py`, `src/telemetry.py` | 7 |
| 6 | Evaluation engine: rolling-200 per (pair,tf,SIDE), composite health (anti reward-hack), regime + FP/FN attribution | `src/evaluation.py` | 8 |
| 7 | Sentinel: bounded diffs (±10%/weight, ≤4 changes/cycle, doc-21 bounds, Σweights=1), shadow-gated promote/rollback, `results_log` + chronicle | `src/sentinel.py` | 11 |
| 8 | Kill-switch (daily DD 0.5% / ADL≥4 / frozen feed / losing-streak-5→30m cooldown), doc-30 §6 promotion gate (human-gated), paper orchestrator loop | `src/safety.py`, `src/orchestrator.py` | 12 |
| 9 | Backtest harness (no fabricated outcomes — exits from real bar extremes, SL-first conservative), OOS split, VIP0 fees; **real-data run** | `src/backtest.py`, `scripts/run_backtest_real.py`, `scripts/fetch_klines_via_gateway.py` | 5 |
| 10 | Monitoring dashboard + human alert stream (promotions, rollbacks, kill-switch, incidents) | `src/dashboard.py` | 4 |

## Real-data validation (Phase 9)

- 1,500 real Binance USDⓈ-M klines × 6 series (BTC/ETH/SOL × 5m/15m), fetched
  2026-07-26 via the `binance-gateway` Fly VM (sin) — local Binance access is geo-blocked.
- 1,485 decisions logged per series; entry threshold 0.90 admitted exactly the top
  0.07% of bars (max scores 0.91–0.938) — the selectivity the spec demands.
- Honest outcomes: 4W/2L full-sample, mixed in/out-of-sample. See
  [reports/2026-07-26-backtest-real.md](reports/2026-07-26-backtest-real.md).

## What is deliberately NOT done in code

- **Live trading path**: there is no code path that goes live without
  `safety.promotion_gate(..., human_approved=True)`. That flag is only settable by a human.
- **200-trade ≥85% WR promotion stats**: requires weeks of continuous paper runtime
  per (pair, tf, side) — an *operating* milestone, not a code deliverable. Claiming it
  now would be fabrication.
- **Live Binance client**: `ExchangeClient`/`Exchange` protocols are in place; the real
  wrapper is written at cutover time, after paper stats justify it.

## Runbook

```bash
.venv/Scripts/python -m pytest                       # 105 tests
.venv/Scripts/python scripts/fetch_klines_via_gateway.py BTCUSDT ETHUSDT  # real data (via Fly)
.venv/Scripts/python scripts/run_backtest_real.py    # real-data replay + report
.venv/Scripts/python scripts/run_backtest_demo.py    # synthetic pipeline smoke
```

## Phase 12 — Time-sensitive 1m cadence + MTF context (2026-07-26)
- Decision cadence decoupled from structural timeframe: `DECISION_TF=1m` by default,
  `TFS=5m,15m` are MTF context for `htf_bias`/`mtf_aligned`.
- `build_state_mtf()` builds a 1m decision state and injects higher-TF bias → the
  EXISTING 7-factor engine becomes multi-timeframe WITHOUT engine edits.
- Act on the latest CLOSED 1m bar → "jump immediately" in PAPER. `CYCLE_S=60`.
- Immediacy gate: only act when `mtf_aligned` (don't fight the HTF bias). Entry bar
  stays 0.90; actionability comes from cadence, not a looser threshold.
- 1m real-data backtest + 4 cadence tests added. Live: deciding every minute, tf=1m.
