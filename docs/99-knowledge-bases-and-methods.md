# Vaiśravaṇa — Knowledge Bases & Methods (consolidated reference)

> Single source of truth for *what knowledge the system encodes* and *what
> methods it uses to evaluate, correct, and improve itself*.
> Authored 2026-07-30. Covers the main bot (`vaisravana`), the wave engine
> (`vaisravana-wave`), and the alpha/exit engine (`vaisravana-alpha`).

---

## 0. Repository map

| Repo | Remote | Role | Workspace on sera |
|------|--------|------|-------------------|
| `vaisravana` | hernanda-git/vaisravana | Main 9-engine bidirectional futures bot + Sentinel | `~/vaisravana-workspace/vaisravana` |
| `vaisravana-wave` | hernanda-git/vaisravana-wave | Tick-driven wave "surfing" engine | build `/opt/bots/vaisravana-wave`, working copy `/opt/bots/vw_commit` |
| `vaisravana-alpha` | hernanda-git/vaisravana-alpha | Real-time exit engine (merged exit logic for all 15 pairs) | `/root/vaisravana-alpha` |

The three were split into separate repos for safety (a broken change in one
can never reach another). The Sentinel constraint — *only the ParameterSurface
may be changed by the autonomous loop, never engine/StrategyProfile code* —
applies to all three.

---

## 1. The knowledge bases

### 1.1 SMC Knowledge Base (`docs/knowledge/`) — main bot

Smart Money Concepts (SMC) is an **opt-in plug-in layer** that feeds the
existing 9-engine dual-score stack. It is *not* a separate strategy — it is the
microstructure input layer that makes the `structure_score` (15%) and
`liquidity_score`/`_bear` (10%) factors **real instead of floor-defaulted**.

| File | Audience | What it answers |
|------|----------|-----------------|
| `smc-index.md` | everyone | Map of the KB + design invariants |
| `smc.md` | everyone | Doctrine re-anchored to the actual engines & dual-score |
| `smc-detector.md` | dev | `src/smc.py` interface, data model, O(n) algorithms |
| `smc-scoring-impact.md` | quant | Exact math: detected structure → 7 factors → win-rate lever |
| `smc-wiring.md` | dev/ops | Integration points + Sentinel constraint + guardrails |
| `smc-verification.md` | quant/QA | E2E plan: pytest + real-data backtest + acceptance gates |
| `smc-quickref.md` | ops | Cheat sheet + knobs the Sentinel *can* tune |
| `smc-execution-plan.md` | dev/lead | Phase-by-phase build, shadow-first, reversible |

**Key facts verified against code (not assumed):**
- `MarketState` already exposes SMC slots: `hh, hl, lh, ll, bos, choch,
  liq_sweep, eq_high, eq_low, fvg`.
- The dual-score path (`src/scoring.py:decide`, `score_side`) is first-class
  bidirectional — a SHORT is NOT a mirrored long; detectors must populate SMC
  slots **symmetrically** for both sides.
- The live factory `build_state_mtf` (`scripts/bot_paper.py`) only feeds a rough
  heuristic; doc 40 §1.4 calls structure + liquidity "starved" live. SMC fixes
  exactly that, honestly, with a backtest==live code path.
- The detector is a **new pure module** that *feeds* engine inputs — it never
  rewrites `structure_score`/`liquidity_score` source. That keeps the Sentinel's
  safety envelope intact.

**Design invariants (must hold for every file):**
1. Pure & side-effect free — `src/smc.py`: input `list[Candle]`, output a
   dataclass. No I/O, network, or DB.
2. Additive, non-breaking — detectors set slots on a `MarketState` that already
   has safe defaults; existing tests keep passing.
3. Symmetric — every detector yields LONG- and SHORT-usable facts.
4. Performance-first — O(n) single pass, incremental pivot cache. Must not
   dominate the <200 ms decision budget.
5. Honest flags — every boolean traces to OHLCV arithmetic; no invented
   liquidity.

**The 25% lever (what SMC actually moves):**

| Factor | Weight | SMC slot fed | Engine |
|--------|--------|--------------|--------|
| Structure | 15% | `hh hl lh ll bos choch` (+ `ob_* breaker mitigation`) | `structure_score` |
| Liquidity | 10% | `liq_sweep eq_high eq_low fvg` (+ `premium discount`) | `liquidity_score`/`_bear` |

The other 5 factors (trend 30 / momentum 20 / volume 15 / atr 5 / funding 5)
are **not** SMC.

### 1.2 Multi-Layer Evaluation KB (`vaisravana-alpha/docs/knowledge-base/evaluation-kb.md`)

The alpha repo carries the canonical evaluation doctrine. Single success metric:
**growing balance** — not activity, not win rate, not Sharpe.

Six layers, each can veto promotion independently; L0 runs first and
short-circuits everything on failure:

| Layer | Name | Question |
|-------|------|----------|
| L0 | Integrity | Can we trust the numbers? (fee consistency, accounting identity, ts order, dup IDs, zero-notional) |
| L1 | Execution | Did the machine behave correctly? (feed liveness, warmup-aware rejection, lifecycle, crash) |
| L2 | Statistical | Is this distinguishable from luck? (Deflated Sharpe Ratio) |
| L3 | Economic | Does it make money after ALL costs? (net PnL, expectancy, fee burden) |
| L4 | Robustness | Would it survive out of sample? (first-half vs second-half, single-trade/pair dependence) |
| L5 | Risk | Can it ruin the account? (ruin, drawdown >50%, single-trade catastrophe) |

Promotion requires L0–L3 PASS and no layer FAIL. INSUFFICIENT is never a pass.

### 1.3 Real-Time Exit KB (`vaisravana-alpha/docs/knowledge-base/realtime-exit-kb.md`)

Exit when balance growth is at risk. Per-tick (100–500 ms) monitoring across 5
factor categories:

1. **Structural** (1–10 s): EMA slope cascade, VWAP deviation, structure-break
   rejection, volume spike on rejection.
2. **Momentum** (10–60 s): RSI(3) divergence, ROC(5) acceleration, volume
   profile shift, tick-volume imbalance.
3. **Order-flow proxy** (1–10 s): spread widening, imbalance ratio, price
   congestion, delta proxy.
4. **Volatility regime**: ATR percentile, realized-vol shift, Keltner position.
5. **Liquidity-zone awareness** (SMC): order-block proximity, liquidity sweep,
   depth proxy.

Exit-confidence model: `exit_conf = w1·f_struct + w2·f_mom + w3·f_flow +
w4·f_vol + w5·f_liq`, weights adapt by regime / asset / historical accuracy.
Thresholds: >0.85 close 100%, >0.70 close 50% + trail, 0.30–0.70 hold,
<0.15 consider flipping bias. Always fee-aware: an exit must clear
`close_fee = notional × 0.0004` or it pays to lose.

### 1.4 Wave engine knowledge (lives in `WAVE_*.md`, `docs/reports`, `eval_data/`)

The wave repo documents its own engine findings in `WAVE_ENGINE_REPORT.md`,
`WAVE_EVALUATION.md`, `WAVE_IMPROVEMENTS.md`, `WAVE_LEARNING_LOG.md`, and the
per-iteration soak verdicts persisted to `WAVE_LEARNING_LOG.md` + `LOOP_STATUS.md`.

---

## 2. The methods

### 2.1 Trading method (main bot) — 9-engine dual-score

- 9 pure-function engines (`src/engines.py`) produce factors: trend 30%,
  momentum 20%, volume 15%, structure 15%, liquidity 10%, atr 5%, funding 5%.
- `src/scoring.py:decide` / `score_side` compute a per-side confluence score;
  entry clears `entry_threshold` (default 0.90).
- Bidirectional: LONG and SHORT scored independently → two separate counters
  per (pair × tf × side).
- Cross-asset + MTF relational context (`src/marketcontext.py`, `decide_ctx`)
  is a separate modulator stacked on top.
- Risk: 2× leverage, 0.25% risk, kill-switches (`src/safety.py`).
- Mode: PAPER / UNREAL by default (`src/mode.py`, `ModeGuard`).

### 2.2 Evaluation method — Deflated Sharpe + CSCV (wave `evaluator/`)

The autonomous evaluator is kept fully separate from `src/wave/` (Sentinel
compliance + it can be improved on its own — "the evaluator is itself
evaluated").

Modules (`evaluator/`):
- `metrics.py` — load trades from DB, build equity, per-trade Sharpe.
- `deflated_sharpe.py` — **Deflated Sharpe Ratio** (Bailey & López de Prado
  2014). Corrects the observed Sharpe for multiple-testing / selection bias
  (the loop picks the best of many trials) and non-Normal PnL (skew + kurtosis).
  Returns a *probability* the true Sharpe is positive.
- `cscv.py` — **Combinatorial Cross-Validation** + **Probability of Backtest
  Overfitting** (López de Prado). Splits the per-trade PnL series into N
  contiguous, time-ordered blocks; trains on the rest; PBO = fraction of
  combinations where the top train-ranked candidate has negative test Sharpe.
  High PBO ⇒ selection is noise. Done by *time block*, never naive random
  shuffle (which would leak future into past).
- `archive.py` — DGM-style lineage node store (JSONL) — every candidate keeps
  its ancestry.
- `cli.py` — `python -m evaluator.cli <db> [--n-trials N] [--archive]`.

**Verdict logic:** `n < 20` → INCONCLUSIVE (soak more, anti-overfit floor);
`CSCV PBO >= 0.5` → REJECT; `Deflated Sharpe p < 0.95` → REJECT;
`worstR <= -3R` → REJECT; else KEEP.

**Design rules:** CLEAN (no engine code imported, no side effects on the bot),
STRUCTURED (one concern per module, pure math), NO MIXING (candidate DBs in
`/root/wave_eval_data/`, archive separate), REPRODUCIBLE (every number
re-derivable from the DB alone).

### 2.3 Self-improvement method — bounded Sentinel loop

**Main bot:** the two-bot system (doc 20) — `Vaiśravaṇa-Trader` (active) +
`Vaiśravaṇa-Sentinel` (correction/review). Four phases: auto-evaluate →
auto-review → auto-correct (propose to SHADOW only) → auto-improve (promote if
shadow beats baseline). Safety: Sentinel only emits a `ParameterSurface`; per-weight
Δ ≤ ±10%, ≤4 changes/cycle, weights renormalized to 1.0; automatic rollback if
shadow/live worsens; human-approval gate for large changes.

**Wave bot (`RUN_LOOP.md` SOP):** cron-driven, ~30 min cadence with a **tick
lease** overlap guard (`/opt/bots/vw_commit/.tick_lease`, 75-min TTL) so a
concurrent deploy never voids a sibling soak window. Each iteration:
STATE → OBSERVE → ANALYZE (one hypothesis, one change at a time) → IMPROVE
(edit `src/wave/`) → DEPLOY + VALIDATE (`docker compose build --no-cache` +
`up --force-recreate`, wallet+DB reset for a clean run) → COMPARE with
`scripts/loop_eval.py` → LEARN + DOCUMENT (`WAVE_LEARNING_LOG.md` +
`LOOP_STATUS.md`) → COMMIT + PUSH (`valarion` creds) → REPEAT forever.

Anti-overfit rule: never KEEP/REJECT on pooled `n < 20` (MIN_N). Soak the same
candidate across ticks until n is sufficient.

**Wave LLM research loop (Phase 11, `scripts/bot_paper.py`):**
- `wave_research_loop()` — daemon thread, propose-only Sentinel for the wave
  engine. Gathers real eval data from `wave_log`, builds `EvalReport` objects +
  FP/FN cases via `_wave_shadow_replay()`, calls `LLMResearcher.propose`, applies
  a **bounds-checked** proposal, persists to disk. Never auto-trades.
- `research_loop()` (main bot) — same pattern against `trade_logs`; rolls back
  to shadow if shadow is not better.

### 2.4 Fee model (used everywhere)

```
open_fee  = notional × 0.0002   (2 bps maker)
close_fee = notional × 0.0004   (4 bps taker)
net       = gross - open_fee - close_fee
```

Survival gate: a trade is only taken if `expected_move_bps >= open_fee +
close_fee + safety_margin`. L0 integrity check: total fees must be within
[0.3×, 3×] of `notional × 0.0006`. The accounting identity `net == gross -
(open_fee + close_fee)` is recomputed once at write time and stored.

### 2.5 Deployment method (all repos)

Local-to-**sera** only (no Fly.io). Docker-compose `bots` stack:
- main: container `bots-vaisravana`, DB `/data/vaisravana.db`.
- wave: container `bots-vaisravana-wave`, built from `/opt/bots/vaisravana-wave`.
- alpha: container `bots-vaisravana-alpha`, workspace `/root/vaisravana-alpha`.

Rebuild rule that has bitten us repeatedly: a plain `restart` DOES NOT pick up
code changes — must `build --no-cache` + `up --force-recreate`. Stop the bot
before changes; explicit confirmation for destructive ops (wipe DB). Remove
`/data/alpha_stop.flag` after restarting alpha.

---

## 3. How to read the docs

- New to the project? Start with `docs/00-goals.md`, then `ARCHITECTURE.md`,
  then `docs/20-meta-system-overview.md`.
- Want the win-rate lever? `docs/knowledge/smc.md` + `smc-scoring-impact.md`.
- Want the evaluation math? `evaluator/README.md` + `deflated_sharpe.py` +
  `cscv.py` + `vaisravana-alpha/docs/knowledge-base/evaluation-kb.md`.
- Want to run the loop? `vaisravana-wave` `RUN_LOOP.md`.
- Want the exit doctrine? `vaisravana-alpha/docs/knowledge-base/realtime-exit-kb.md`.
