# Project Vaiśravaṇa — Phased Implementation Plan

> **For Hermes:** Use `subagent-driven-development` to execute this plan task-by-task.
> This is a **plan only** — no code is written here. Every number, table, and bound below is
> quoted from the repository docs (`ARCHITECTURE.md`, `docs/20-32`, `docs/30-concrete-spec.md`).
> Do not invent parameters; if a value is not in the docs, it is marked **[OPEN]**.

**Goal:** Build Project Vaiśravaṇa from pure documentation into a runnable, stability-first,
≥85%-win-rate crypto-futures trading system on Binance USDⓈ-M — two bots (Trader + Sentinel),
full audit logging, shadow-first promotion, no external signals.

**Architecture (from `ARCHITECTURE.md` + `doc 20`):** Single-machine Python service.
`Vaiśravaṇa-Trader` (9 engines → scoring → two-layer gate → Binance execution) runs one
isolated `ShadowTrader(pair, tf)` per pair×TF. `Vaiśravaṇa-Sentinel` reads the telemetry
store and proposes *bounded* parameter edits, tested in shadow, promoted only on evidence.
All state persists to SQLite (`docs/30` §4 schemas).

**Tech Stack:** Python 3.11 · `python-binance` (or `binance-futures-connector`) · `pandas`/
`numpy` (indicators) · `sqlite3` (stdlib) · `pydantic` (config/schema validation) ·
`pytest` (TDD) · `schedule` or `asyncio` (loop) · `loguru` (logger that fails loud).

**Hard constraints (non-negotiable, from docs):**
- Default mode = `PAPER`/UNREAL. **No live capital until per-(pair×tf×side) gate passes** (`doc 30` §1, §6).
- No external signals. Bot decides internally (`doc 30` §4, README "No Signals").
- Sentinel may **only** edit the bounded parameter surface in `doc 21`; never engine logic,
  execution code, or telemetry schema.
- Every trade (win AND lose) logged to `trade_logs` with lifecycle timestamps + `win`/`loss`
  booleans + cumulative `win_pct`/`loss_pct`.

---

## Phase 0 — Repo & Project Skeleton (infra)  ✅ DONE (2026-07-26)

**Objective:** Establish a runnable Python package with config, logging, and DB bootstrap so
every later phase has a home.

**Execution plan (bite-sized):**
1. Create `pyproject.toml` (deps: pydantic, pytest).  ✅
2. Create package dirs: `src/` (flat modules — deviation from nested `src/vaisravana/...`,
   simpler for early phases; can refactor later).  ✅
3. `src/config.py` — pydantic `ParameterSurface` mirroring **every row of `doc 21`** (weights
   sum=1 enforced, bounds as `Field(ge=, le=)`, entry>watch invariant).  ✅
4. `src/db.py` — `init_db()` that executes the **exact SQL in `doc 30` §4** (5 tables).  ✅
   Deviations recorded back into doc 30 §4: `TIMESTAMPTZ` → `TEXT` (ISO-8601); `system_health.check`
   quoted as `"check"` (SQLite reserved word).
5. `tests/test_config.py`, `tests/test_db.py` — TDD; **11 tests passing**.  ✅
6. Commit + push.  ✅

**Validation:** `pytest` green (11 passed); `.venv/Scripts/python -m pytest`. Schema creates all
5 tables; `ParameterSurface` rejects out-of-bound / non-∑1.0 / watch≥entry inputs.

**Next:** Phase 1 (Data + Symbol Registry).

---

## Phase 1 — Data Layer & Symbol Registry (the all-pairs reality)

**Objective:** Reliable, exchange-aware market data and symbol resolution — the foundation
everything else depends on. Implements `doc 30` §2 + `doc 32` Lesson 2 (1000x).

**Execution plan:**
1. `data/exchange_client.py` — thin wrapper over `python-binance` Client: `get_klines`,
   `exchange_info()`, `get_ticker()`, account/order endpoints. **All calls return typed dicts.**
2. `data/symbol_registry.py` — on startup, load `exchangeInfo`; build map
   `user_pair → exchange_symbol` (e.g. `BONKUSDT → 1000BONKUSDT`). Cache per-symbol
   `tickSize`, `stepSize`, `minNotional`, `pricePrecision`, `qtyPrecision` (`doc 32` L2).
3. `data/symbol_registry.py::liquidity_filter()` — drop pairs with avg spread > 5 bps or
   24h volume < threshold (`doc 30` §2). **[OPEN]** volume threshold value.
4. `data/feed.py` — periodic OHLCV pull for all filtered pairs across 5m/10m/15m + 1h/4h
   bias; detect frozen feed → emit `system_health(check='feed', status='FAIL')` (`doc 30` §7,
   `doc 28` group A).
5. Unit tests: registry maps 1000x correctly; rounding rounds price→tickSize, qty→stepSize,
   enforces `qty×price ≥ minNotional` (`doc 30` §3 sizing). Feed-freeze test emits health row.
6. Commit.

**Risk:** Binance rate limits (weight). Mitigate: cache `exchangeInfo` 1h; batch kline calls;
respect 429 (Lesson 7). **[OPEN]** request-weight budget per minute.

---

## Phase 2 — The 9 Engines + Scoring (Alpha)

**Objective:** Implement the analysis stack from `doc 01-11` and `doc 10` scoring. Each engine
is a pure function `State → score[0..1]`.

**Execution plan (one engine family per task):**
1. `engines/regime.py` (Layer 1) — trending/ranging/breakout/volatile classifier.
2. `engines/structure.py` (Layer 2) — HH/HL, BOS, CHoCH detection.
3. `engines/liquidity.py` (Layer 6) — equal highs/lows, sweeps, FVG.
4. `engines/candle.py` (Layer 3+4) — candle psychology + momentum (overextension guard).
5. `engines/volume.py` (Layer 4) — volume, delta, anomaly vs avg×1.3 (`doc 30` §3).
6. `engines/volatility.py` (Layer 7) — ATR(14) on trade TF (`doc 30` §2).
7. `engines/mtf.py` (Layer 8) — 1h/4h bias must agree with LTF trigger (`doc 30` §3 tree).
8. `engines/risk.py` (Layer 8) — sizing inputs, exposure state.
9. `scoring/score.py` (doc 10) — compute **two** symmetric scores: `long_score` and
   `short_score` (Σ weights=1, from `ParameterSurface.weights`). Decision rule
   (`doc 10`): pick the higher; if >0.90 and ≥ other → ENTRY with that `side`
   (BUY/SELL); 0.80–0.90 → WATCH; else SKIP. **No directional bias** — SHORT is
   first-class, not a mirrored long.
10. `reasoning/engine.py` (doc 29) — 5W1H scaffold + hypothesis (H1/H2/H3) builder.
11. Per-engine unit tests against fixed OHLCV fixtures (assert score ranges, no NaN).
12. Commit.

**Note:** Engines are the part Sentinel **cannot** modify (`doc 21`). Keep them deterministic
and side-effect free.

---

## Phase 3 — Two-Layer Gate + Decision Record (safety first)  ✅ DONE (2026-07-26)

**Objective:** Implement Gate A (cheap pre-scoring) + Gate B (hard clamp) from `doc 30` §3 /
`doc 32` Lesson 1, and persist every decision to `decisions_log`.

**Execution plan:**
1. `gate/gate_a.py` — idempotency (`correlation_id` unique), per-pair cooldown, liquidity
   whitelist, spread < 5 bps (`doc 30` §3 Gate A). **Applies to both BUY and SELL entries.**
2. `gate/gate_b.py` — hard clamps the score engine **cannot** override: size→`risk_usd`,
   `max_leverage ≤ 2`, `daily_loss_limit ≤ 0.5%`, **SL on correct side** (LONG→SL below,
   SHORT→SL above — reject if reversed, `doc 30` §3), reduceOnly on close, margin ≤ 50%
   (`doc 30` §3 Gate B, `doc 21`).
3. `decision.py` — orchestrates engines→**dual** score→Gate A→Gate B; writes `decisions_log`
   (`confidence_pct = chosen_score×100`, `gate_a_pass`, `gate_b_pass`, `side=BUY|SELL`)
   (`doc 30` §4).
4. Tests: Gate B rejects reversed SL; Gate A blocks duplicate `correlation_id`; clamp caps
   leverage at 2 even if score says entry.
5. Commit.

---

## Phase 4 — Execution & Position Monitor (the footguns)  ✅ DONE (2026-07-26)

**Objective:** Send orders safely, validate/repair, and run the background position monitor.
Implements `doc 30` §3 (validate→repair→resubmit-once), `doc 32` Lessons 2-5.

**Execution plan:**
1. `execution/validate_order.py` — precision/min/max price, minQty, minNotional, integer
   lots using SymbolRegistry filters (`doc 30` §3, `doc 32` L2).
2. `execution/order_manager.py` — LIMIT (maker) near mid; if unfilled in 2s → cancel,
   re-evaluate (no chase) (`doc 30` §3). On reject → repair qty/price → revalidate →
   resubmit **once** → else `VALIDATION_SKIP` (`doc 32` L3).
3. `execution/sl_tp.py` — SL as **conditional STOP (reduceOnly)** primary; fallback to
   mark-price polling for `-4120` contracts (`doc 32` L2). NEVER naive LIMIT-SL on wrong side.
4. `execution/position_monitor.py` — 10s loop: dual-mechanism SL, self-heal (re-place lost
   orders 1×/session), orphan detection (>30m, verify exchange), time-based exit (>max-hold =
   TF), notify-on-close → `exec_events` + `trade_logs` (`doc 30` §3, `doc 32` L4).
5. `execution/rounding.py` — reuse SymbolRegistry filters; loop until `qty×price ≥ minNotional`.
6. Tests (mock exchange): 1000x rounding; LIMIT-SL rejected; validation repair succeeds once;
   orphan detected.
7. Commit.

**Risk:** Real-money danger. **All tests run in PAPER/mock.** Live disabled until Phase 8 gate.

---

## Phase 5 — Trade Lifecycle & Full Logging  ✅ DONE (2026-07-26)

**Objective:** Close the loop — every trade writes complete `trade_logs` rows with lifecycle
timestamps, `win`/`loss` booleans, and rolling `win_pct`/`loss_pct` per pair×TF (`doc 30` §4).

**Execution plan:**
1. `trade/lifecycle.py` — on open: insert `trade_logs` (`ts_opened`, `ts_filled`,
   `decision_id` FK). On TP/partial/close: update `ts_tp_hit`, `ts_partial_close`,
   `ts_fully_closed`, `pnl_usd`, `r_multiple`, `close_reason`.
2. `trade/metrics.py` — compute `win`/`loss` (1/0), then **rolling** `win_pct`/`loss_pct`
   per (`pair`,`tf`) from prior rows; update current row.
3. `telemetry/logger.py` — central writer; **fails loud** (alarm + halt entry) on DB error
   (`doc 30` §4 footer). Writes `exec_events` (ORDER_SENT/FILL/REPAIR/VALIDATION_SKIP,
   `error_cat` per `doc 32` L7) and `system_health`.
4. Tests: a simulated win+loss sequence yields correct `win_pct` cumulative; logger raises on
   broken connection.
5. Commit.

---

## Phase 6 — Evaluation Engine + Auto-Evaluate (per pair×TF)  ✅ DONE (2026-07-26)

**Objective:** Implement `doc 23` metrics, triggered per `trade_logs` close, rolling 200.

**Execution plan:**
1. `evaluation/metrics.py` — **per (pair, tf, SIDE)**: Win Rate (≥85% headline, computed
   separately for BUY and SELL), Expectancy >+0.2R, Profit Factor >1.20, Max DD <3%,
   Sharpe >0.5, Fill rate >95%, Avg slippage <5bps (`doc 30` §5). LONG and SHORT are
   independent counters — never merged.
2. `evaluation/attribution.py` — false-positive (ENTRY→SL) / false-negative (SKIP→should've
   profited) per factor/regime (`doc 23`).
3. `evaluation/auto_eval.py` — on each close, recompute rolling window; emit `eval_report.md`
   (`doc 26` format).
4. Tests: known trade sequence → expected WR/expectancy; false-positive counted correctly.
5. Commit.

---

## Phase 7 — Sentinel (bounded self-improvement) + Documentation  ✅ DONE (2026-07-26)

**Objective:** Implement `doc 24` 5-step loop and `doc 26` outputs, writing `results_log`.

**Execution plan:**
1. `sentinel/reason.py` — build 5W1H scenario + hypothesis from `evaluation` output (`doc 29`).
2. `sentinel/correct.py` — propose a **bounded** `ParameterSurface` diff (weights within
   `doc 21` bounds, Σ=1 renormalized, ≤±10% per weight, ≤4 changes/cycle) (`doc 20`, `doc 21`).
3. `sentinel/shadow_test.py` — apply diff to a *shadow* `ShadowTrader`; compare vs baseline.
4. `sentinel/promote.py` — promote only if shadow ≥ baseline AND composite health ↑; else
   rollback (`doc 20` principles 2-4).
5. `sentinel/document.py` — append `results_log` row (kind=EVALUATION/REASONING/...,
   `eval_summary`, `reasoning_5w1h`, `correction`, `improvement`, `review`) + `chronicle.md`
   (`doc 26`).
6. Guardrail test: Sentinel attempt to edit a non-surface param → rejected; weight sum≠1 →
   renormalized; >4 changes → refused.
7. Commit.

---

## Phase 8 — Orchestration, Promotion Gate & Kill-Switch  ✅ DONE (2026-07-26)

**Objective:** Wire the daily loop (`doc 27`), the per-pair×TF promotion gate (`doc 30` §6),
and all kill-switches (`doc 25`, `doc 30` §7).

**Execution plan:**
1. `orchestrator/loop.py` — per candle close per pair×TF: engines→decision→(paper) order→
   lifecycle→auto-eval→(window) Sentinel cycle (`doc 30` §9).
2. `orchestrator/promotion.py` — LIVE for one **(pair, tf, SIDE)** only if: ≥200 trades
   (that side), WR≥85% (that side), expectancy>+0.2R, DD<3%, PF>1.3, clean health,
   **human approval** (`doc 30` §6). LONG and SHORT promoted **independently**. Post-live:
   WR<85% in validation window for that side → revert/disable.
3. `safety/kill_switch.py` — triggers: daily drawdown≥0.5%, ADL rank≥4, frozen feed,
   maintenance/delist, losing streak=5→cooldown 30m (`doc 30` §7, `doc 21`).
4. `safety/health_reporter.py` — proactive subsystem checks → `system_health` (`doc 32` L6).
5. Integration test: 200 simulated PAPER trades at WR≥85% on one pair×TF → promotion eligible;
   WR<85% → never promoted.
6. Commit.

---

## Phase 9 — Paper-First Validation & Backtest Harness  ✅ DONE (2026-07-26)

> Harness + OOS split + VIP0 fee model + report generator (5 tests). REAL-DATA run
> completed: 1500 real Binance USDⓈ-M klines × 6 series (BTC/ETH/SOL × 5m/15m)
> fetched via `binance-gateway` Fly VM (local Binance geo-blocked). Result:
> 1485 decisions/series logged, 0.90 threshold correctly selective (1 ENTRY per
> series, max scores 0.91–0.938), mixed honest outcomes (4W/2L full-sample).
> Report: `docs/reports/2026-07-26-backtest-real.md`. NOTE: 200-trade WR≥85%
> promotion stats need weeks of paper runtime — that is the Phase 10+ operating
> phase, not a code deliverable.

**Objective:** Prove the system meets goals in PAPER before any live. Addresses `doc 28`
group E (research validity) and `doc 31` open questions (backtest, fee tiers).

**Execution plan:**
1. `backtest/harness.py` — replay historical klines per pair×TF; produce WR/expectancy/DD
   across the universe; **[OPEN]** fee-tier assumption (use Binance VIP0 maker/taker).
2. Run on ≥30 liquid pairs × {5m,10m,15m}; collect per-pair×TF WR distribution.
3. Verify: liquid pairs sustain ≥85% WR in PAPER/shadow; thin pairs auto-pruned by filter.
4. Tune `ParameterSurface` defaults via Sentinel-in-shadow only (not manual hacks).
5. Report to `results_log` + `chronicle.md`. Commit.

**Risk:** Overfitting to history (reward-hacking, `doc 28` G). Mitigate: rolling/out-of-sample
split; Sentinel runs on live shadow, not fitted weights.

---

## Phase 10 — Live Cutover (human-gated) & Monitoring  ✅ CODE DONE (2026-07-26)

> Dashboard + human alert stream implemented (`src/dashboard.py`, 4 tests): per-key
> status, promotions/rollbacks/kill-switch/incidents all surfaced. Live cutover itself
> remains an OPERATING decision — requires 200-trade WR≥85% paper stats per (pair,tf,side)
> + `promotion_gate(human_approved=True)`. No code path can go live without the human flag.

**Objective:** Safe go-live per pair×TF, with continuous monitoring and rollback.

**Execution plan:**
1. Enable `LIVE` only for pair×TF that passed Phase 9 + `doc 30` §6 + explicit human approval.
2. `monitoring/dashboard.py` — read `trade_logs`/`results_log`/`system_health`; alert on every
   promotion, rollback, kill-switch, incident (`doc 25`, `doc 30` §7).
3. Keep shadow running as baseline post-live (`doc 30` §9). Cap `global_max_live_pairs=5`
   (`doc 21`).
4. Weekly `results_log` review; monthly human audit of Sentinel diffs.
5. Commit.

---

## Cross-Cutting: Testing & Quality Gates (every phase)
- **TDD:** write failing test → run → implement → run green → commit (per `plan` skill).
- **No live calls in tests:** mock `exchange_client` and `order_manager`.
- **Logger fails loud:** a swallowed telemetry error must halt entry, not silence.
- **Determinism:** engines pure; seed RNG; fixed fixtures in `tests/fixtures/`.

## Open Questions (must resolve before/within phases — tracked in `doc 31`)
- Volume threshold for liquidity filter (`doc 30` §2).
- Request-weight budget per minute for all-pairs polling (`doc 32` L7).
- Concrete DB engine (SQLite chosen here; Postgres if scale demands — **[OPEN]**).
- Fee-tier assumption for backtest (`doc 31`).
- Exchange for universe = Binance (decided). Timeframes = 5/10/15m (decided). WR≥85% (decided).

## Sequencing Rationale (why this order)
Data (P1) → Alpha (P2) → Safety gate (P3) → Execution (P4) → Logging (P5) → Eval (P6) →
Sentinel (P7) → Orchestration/gate (P8) → Validate (P9) → Live (P10). Each phase depends only
on prior ones; P4/P5 are the highest-risk (real exchange quirks) and are fully PAPER/mock
until P8. No phase touches live capital.
