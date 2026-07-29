# Architecture: The Best Viable Bot (Vaiśravaṇa Fleet)

**Status:** Target-state design + phased build plan
**Audience:** Engineers/agents extending the Vaiśravaṇa fleet
**Companion docs:** `00-goals.md` (mandate), `run1-postmortem.md` (failure taxonomy), `/root/scalping_bot_research.md` (15 prioritized techniques)
**Hard constraints (from ops memory — treat as law):**
- Deployment is **local-only** via docker-compose stack `bots` on `sera`. **Never** `fly deploy`/`flyctl`.
- **Sentinel constraint:** only the **ParameterSurface** (weights/surface) may be mutated; never the engine or `StrategyProfile`.
- Paper mode: fake **$10** start, runs to $0, **0.04% taker on both open and close** (see fee-model note below).

---

## 0. What "best viable" means here

Not "most trades" or "highest paper PnL in one lucky run." Per `00-goals.md` the objective is:

> **Maximize long-term risk-adjusted balance growth while minimizing the probability of catastrophic loss**, via an autonomous, self-improving loop.

The single biggest empirical lesson (run-1: **$10 → $1.49**, 106 trades, 45% WR, **fees −$8.40**) is that this bot currently has **~zero net edge per trade** and **trades ~10× too often**. So the architecture's #1 job is *cost discipline + selection quality + honest measurement*, then *new alpha*, then *automation of the improvement loop itself*.

Everything below is buildable on the **existing** repo — it reuses `scripts/bot_paper.py`, `src/monitor.py`, `src/db.py`, `src/pair_excluder.py`, `src/telegram_bot.py`, `src/config.py`, `src/wave/*`, `scripts/deploy.py`, `scripts/eval_honest.py`, and the `tests/test_phase*.py` harness.

---

## 1. System context (current fleet)

| Bot | Alias | Branch | Role | DB |
|---|---|---|---|---|
| fatty | `@xvalarion_bot` | `listener-local` | Listens to `@fattyfatclub`/UNKNOWN TRADERS channel → signal feed | (own) |
| main | `@vaisravana_bot` | `main` | Primary scalping engine (1m perps, 15 pairs) | `/data/vaisravana.db` |
| wave | `@wave_vaisravana_bot` | `vaisravana-wave` | Wave/SMC strategy engine | `/data/vaisravana-wave.db` |

Stack: `docker compose` stack **`bots`** (containers `bots-vaisravana`, `bots-vaisravana-wave`). Source in container at `/app/src`, `/app/scripts`. King Midas (Node `ws`) dashboard observes all three.

**Two-DB rule:** diagnose each bot against *its own* DB. "No trades" on main ≠ wave broken.

---

## 2. Target architecture (layered)

```
┌──────────────────────────────────────────────────────────────────────┐
│                         OBSERVABILITY & CONTROL                        │
│   telegram_bot.py (fills/closes/ops)  ·  King Midas ws dashboard       │
│   health/heartbeat  ·  decisions_log audit  ·  /api/control (restart/  │
│   stop/start/clean)  ·  alerting (freeze, no-trades, drawdown breach)  │
└──────────────────────────────────────────────────────────────────────┘
                                   ▲ state/logs
┌──────────────────────────────────────────────────────────────────────┐
│                  CONTINUOUS-EVOLUTION ORCHESTRATOR (CEO)               │
│   observe → analyze → research → generate → validate → compare →       │
│   deploy(gated) → learn                                                │
│   Promotion gates: walk-forward + Monte Carlo + OOS + sensitivity.     │
│   Clobber-guard: protects bot_paper.py paper layer from wave-loop.     │
└──────────────────────────────────────────────────────────────────────┘
                                   ▲ candidates (ParameterSurface diffs)
┌──────────────────────────────────────────────────────────────────────┐
│                         EVALUATION / RESEARCH LAYER                    │
│   eval_honest.py · walk_forward · monte_carlo · net_expectancy         │
│   scoreboard (per-pair, per-regime, per-side, per-close_reason) ·      │
│   A/B harness (baseline vs candidate) · ablation                        │
└──────────────────────────────────────────────────────────────────────┘
        ▲ metrics                ▲ paper stats / excursions
┌──────────────────────────────────────────────────────────────────────┐
│   DECISION LAYER              │   RISK / SIZING LAYER                   │
│   strategy/SignalGenerator    │   survival_gates()  (ADDITIVE)          │
│   ParameterSurface (mutable)  │   fractional-Kelly + vol-target sizing │
│   regime_detector (ATR pct)   │   notional cap = 2× live equity, $5 fl │
│   session filter (UTC)        │   loss-streak / daily-loss cooldown     │
│   fee-aware EV gate           │   fee model (maker open / taker close)  │
│   spread/liquidity gate       │                                         │
│   OFI order-book imbalance    │                                         │
└───────────────────┬──────────┴─────────────────────────────────────────┘
                    │ StrategyEntry (side, conf, entry, sl, tp, tf)
┌──────────────────────────────────────────────────────────────────────┐
│                         EXECUTION LAYER                                │
│   exchange_adapter (post-only maker entry @ touch, taker SL, maker TP) │
│   order lifecycle (fill → BE-trail @ +0.5R → partial TP → TP/SL/maxhold)│
│   funding-aware skip (don't hold through funding on paying side)        │
└──────────────────────────────────────────────────────────────────────┘
                    │
┌──────────────────────────────────────────────────────────────────────┐
│   PORTFOLIO / STATE LAYER      │   DATA / FEED LAYER                    │
│   paper_wallet / db.py         │   klines ws (httpx, timeout+retry)     │
│   trade_logs (full instrument) │   depth/bookTicker ws (spread, OFI)    │
│   decisions_log (audit)        │   funding ws (8h)                      │
│   EXCURSIONS (mfe_r/mae_r)     │   frozen-fetch guard (NO urllib)       │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.1 Layer responsibilities (mapped to real files)

| Layer | Owned by (existing) | Key interfaces |
|---|---|---|
| **Feed** | `bot_paper.fetch_klines`, new `feed/` (depth+funding) | `get_klines(pair,tf)`, `get_spread_bps(pair)`, `get_ofi(pair)`, `get_funding(pair)` |
| **State** | `src/db.py`, `src/wave/paper_wallet.py` | `paper_stats()`, `paper_equity()`, `lc.open/close(fees_usd=...)`, `EXCURSIONS` |
| **Decision** | `bot_paper` signal path, `src/wave/engine.py`, `ParameterSurface` | emit `StrategyEntry` |
| **Risk/Sizing** | `survival_gates()` in `scripts/bot_paper.py`, `src/config.py` | env-tunable gates; returns `(allow, reason)` |
| **Execution** | new `execution/adapter.py` | `submit(entry)`, `cancel()`, `update_sl/tp()` |
| **Eval** | `scripts/eval_honest.py`, new `research/` | `scorecard(db)`, `walk_forward()`, `monte_carlo()` |
| **CEO** | new `evolution/orchestrator.py` | `propose()`, `validate()`, `promote()` |
| **Obs/Control** | `src/telegram_bot.py`, King Midas, `docker compose` | notify, health, control endpoints |

### 2.2 Decision record: `StrategyEntry`

A single typed object flows decision→risk→execution so the layers stay decoupled and testable:

```python
@dataclass
class StrategyEntry:
    pair: str
    side: str            # BUY | SELL
    tf: str              # 1m | 3m | 5m
    confidence: float    # 0..1 (from ParameterSurface)
    entry_price: float
    sl_price: float
    tp_price: float      # MFE-percentile based, NOT fixed R fantasy
    hold_s_max: int      # from MAX_HOLD_BY_TF
    expected_move_bps: float   # for fee-aware EV gate
    ofi: float = None    # order-flow imbalance if available
```

### 2.3 DB instrumentation contract (kill the lying metrics)

`trade_logs` **must** carry, non-NULL, per row: `entry_price, sl_price, tp_price, size, fees_usd, close_reason, mfe_r, mae_r, spread_bps, regime, side, hold_s`. The post-mortem proved `mfe_r/mae_r` were NULL and `spread_bps` hardcoded 1.0 — that makes *all* exit science impossible. This is a **blocking prerequisite** for the Eval layer.

---

## 3. How the architecture fixes the known failure modes

| Failure (post-mortem / ops) | Architectural fix | Where |
|---|---|---|
| **Decision-loop freeze** (urllib SSL body read hangs forever) | Replace `urllib` with **httpx** (timeout + retry). No network call without an explicit timeout. | `fetch_klines`, new `feed/` |
| **Fee bleed** (−$8.40 of −$8.51) | Fee-aware EV gate (E[move] ≥ 2–3× round-trip cost) + 4 trades/h throttle + per-pair 30min spacing + session block 00–05 UTC. | `survival_gates()` |
| **Oversized entries** (ETH $956 notional on $10) | Refresh equity from `paper_stats()` each cycle; notional cap = 2× live equity, $5 floor; dust-pair (BONK/PEPE…) size floor. | `run()` loop, `survival_gates()` |
| **Broken TP geometry** (TP hit 9/106; MAXHOLD-dominant) | TP at ~60–70th pct of historical **MFE**; BE-trail at +0.5R trailing ~1 ATR; max-hold 15→45min. | `src/monitor.py`, `MAX_HOLD_BY_TF` |
| **Side asymmetry** (BUY 25% vs SELL 56% WR) | Top-chase guard (trending_bull BUY requires pullback) + per-side net-expectancy scoreboard. | `entry_allowed()`, `pair_excluder`→`net_expectancy` |
| **No-trades via excluder** (quarantines whole universe) | Per-pair **net-expectancy** scoreboard (not WR-only); prefer DB *reset* over permanently lowering floor. | `pair_excluder.py` |
| **Wave-loop clobber** (rsync reverts main paper layer) | Clobber-guard in CEO: `git log --oneline HEAD..origin/<b>` before adopt; restore paper layer on top. | `evolution/orchestrator.py` |
| **No edge measurement** | Honest scorecard (per-pair/side/regime/close_reason/hour) + walk-forward + Monte Carlo before any promotion. | `eval_honest.py`, `research/` |
| **Host test failure** (`pydantic` missing) | All tests run **in-container** (`/app/src` + `/app/scripts` on `sys.path`). CI = `docker compose run` pytest. | `tests/`, deploy pipeline |

---

## 4. Configuration model

**Two config classes, by the Sentinel constraint:**
1. **`ParameterSurface`** — *mutable*, weights/thresholds only. Lives in `src/config.py` (or DB-backed). Tuned by CEO. Example keys: `signal_weights`, `tp_mfe_pct`, `ev_gate_k`, `ofi_threshold`, `session_whitelist`.
2. **Engine / `StrategyProfile`** — *immutable* by agents. Structural code only.

**Environment (per-bot, in `deploy/vps/docker-compose.yml`):**
```
VAISRAVANA_EQUITY_USD   # OVERRIDDEN each cycle by paper_stats() — never trust static
VAISRAVANA_MAX_HOLD_1M_S=2700   # 45 min
FEE_RATE_MAKER=0.0002           # open (post-only)
FEE_RATE_TAKER=0.0004           # close (SL/TP taker)
TRADES_PER_HOUR_CAP=4
PAIR_SPACING_MIN=30
SESSION_BLOCK_UTC=00-05
LOSS_STREAK_COOLDOWN=3→30min
SPREAD_GATE_BPS=5
```

---

## 5. Continuous-Evolution Orchestrator (the differentiator)

This is what makes it "best viable" rather than "one more strategy." It operationalizes `00-goals.md`'s loop as code, not vibes.

```
observe  → read trade_logs + decisions_log + excursions + market feeds
analyze  → scorecard(): which pairs/sides/regimes/close_reasons lose? edge decay?
research → pull from scalping_bot_research.md queue; generate ParameterSurface diffs
validate → walk_forward + Monte Carlo + OOS + sensitivity on HISTORICAL (no leak)
compare  → A/B vs live baseline; promote ONLY if risk-adj return beats baseline
deploy   → write new ParameterSurface (NEVER engine); clobber-guard the commit
learn    → append to WAVE_LEARNING_LOG / lossbook; reject hypotheses recorded
```

**Promotion gate (non-negotiable):** candidate must beat baseline on **all** of:
- Net expectancy/trade (fee-inclusive) ↑
- Sharpe / risk-adjusted return ↑
- Max drawdown ≤ baseline
- Walk-forward stability (no single-window heroics)
- Sensitivity: stable across ±20% parameter perturbation

A candidate that fails *any* gate is rejected and logged — overfitting is the enemy.

---

## 6. Phased build plan

Each phase is **independently shippable**, has concrete files, and a **hard exit criterion** (verified, not assumed). Phases build on the existing micro-phase tests where present.

### Phase R1 — Measurement honesty (prerequisite, ~1–2 days)
**Goal:** make every later decision evidence-based.
- **Build:** non-NULL enforcement on `trade_logs` (`mfe_r, mae_r, spread_bps, regime, close_reason, hold_s`); `fetch_spread_bps()` already exists — wire it into every row; `EXCURSIONS` flush on both close paths (already partially done — verify).
- **Tests:** `tests/test_phase_instrumentation.py` asserts 0 NULL excursion rows on a replayed run.
- **Exit:** a 10h paper replay produces a complete `run1-postmortem.md` query pack with **no NULLs**.

### Phase R2 — Kill the freeze & the bleed (survival hardening, ~2–3 days)
**Goal:** bot never silently dies; fees stop dominating.
- **Build:** httpx replacement for `fetch_klines` (timeout+retry); confirm `survival_gates()` has EV gate, throttle, spacing, session block, loss-streak, big-candle skip, spread gate (most exist in v0.0.34 — **verify each is wired**, not just defined).
- **Tests:** `tests/test_phase_freeze.py` (inject a hanging socket → assert loop advances); `tests/test_phase_feebleed.py` (assert veto rate ≥ 75% on run-1 replay).
- **Exit:** 10h paper run with **fees ≤ $2** and `decisions_log` ts advancing every minute under simulated network stall.

### Phase R3 — Exit geometry & sizing (turn timeouts into winners, ~2 days)
**Goal:** TP reachable; sizes sane.
- **Build:** MFE-percentile TP calibration (`tp_mfe_pct` in `ParameterSurface`); BE-trail at +0.5R trailing 1 ATR in `src/monitor.py`; live-equity notional cap + dust floor in `survival_gates()`; top-chase guard already in `entry_allowed()` — verify.
- **Tests:** `tests/test_phase_tp.py` (TP hit-rate >30% on replay); `tests/test_phase_sizing.py` (max notional ≤ 2× equity; no $0 notional opens).
- **Exit:** replay shows TP/SL/MAXHOLD mix with TP contributing >25% of gross winners; 0 oversized entries.

### Phase R4 — Selection quality (net-expectancy scoreboard, ~2 days)
**Goal:** trade fewer, better pairs/sides.
- **Build:** upgrade `pair_excluder.py` to rank by **net expectancy/trade** (gross − fees − spread) and MFE-capture rate, top-N of 15; per-side expectancy gating; reset-vs-lower-floor guidance codified.
- **Tests:** `tests/test_phase_netexp.py` (excluded set ≠ full universe after a losing run; top-N selector picks highest net-exp pairs).
- **Exit:** on a losing-run replay, bot keeps ≥3 tradeable pairs (no starvation) and concentrates on net-positive pairs.

### Phase R5 — New alpha: maker entries + order-flow (real edge, ~3–4 days)
**Goal:** add the highest-ROI *new* signals from research doc (#1, #13).
- **Build:** `execution/adapter.py` post-only maker entry at touch (2–5s TIF, cancel-if-unfilled); depth/bookTicker websocket → `get_ofi()`; OFI confirmation gate (ρ>±0.2); funding-aware skip. Keep SL taker (safety > fee).
- **Tests:** `tests/test_phase_maker.py` (entry rests, cancels on runaway); `tests/test_phase_ofi.py` (OFI gate filters adverse-selected fills).
- **Exit:** maker-entry share >50% of opens; round-trip cost ≤ ~4 bps; no adverse-selection blowups.

### Phase R6 — Evaluation harness + CEO v1 (automation, ~4–5 days)
**Goal:** the loop runs itself, safely.
- **Build:** `research/scorecard.py`, `research/walk_forward.py`, `research/monte_carlo.py`; `evolution/orchestrator.py` with promotion gate (§5); clobber-guard; A/B vs live baseline.
- **Tests:** `tests/test_phase_promote.py` (a known-bad candidate is REJECTED; a known-good one promoted); `tests/test_phase_clobber.py` (wave-loop revert detected + restored).
- **Exit:** orchestrator proposes, validates, and either promotes or rejects a ParameterSurface diff **with zero engine changes**, fully logged.

### Phase R7 — Observability & control hardening (polish, ~2 days)
**Goal:** humans + dashboards trust it.
- **Build:** freeze/no-trades/drawdown **alerts** in `telegram_bot.py`; King Midas Phase-2 real adapter (reads both DBs + health); real `Stop` (SIGTERM verify no heartbeat); auth token before any non-localhost exposure.
- **Tests:** `tests/test_phase_alerts.py`; dashboard e2e (mock→real swap, client unchanged).
- **Exit:** a freeze and a no-trades condition each trigger a Telegram alert within 1 cycle; dashboard shows live state for all 3 bots.

**Cumulative exit (definition of "best viable" v1):** a 10h paper run that (a) never freezes, (b) fees ≤ $2, (c) TP contributes >25% of winners, (d) 0 oversized/dust entries, (e) net expectancy/trade ≥ 0, (f) an automated CEO has promoted ≥1 improvement with full audit trail, (g) alerts fire on anomaly.

---

## 7. Build/runtime discipline (so it stays buildable)

- **Tests in-container.** Host lacks `pydantic`. CI = `docker compose -f deploy/vps/docker-compose.yml run --rm vaisravana pytest` with `sys.path` = `/app/src` + `/app/scripts`.
- **Edits persist.** A `docker cp` hotfix is lost on `--build`. Always also commit to repo. Use the clean re-apply trick (`git reset --hard origin/<b>` then `git checkout <sha> -- <files>`) to survive force-updated remote.
- **Deploy local only.** `scripts/deploy.py` step 4 = `docker compose ... up -d --build vaisravana`. No Fly.io. Run `docker compose config` before rebuild to avoid build-context mismatch.
- **Destructive guard.** Any `DELETE FROM trade_logs` / DB wipe is blocked until explicit human "yes, wipe".

---

## 8. Risks & open questions

1. **Maker-entry adverse selection** (arXiv 2502.18625): passive fills get run over. Mitigated by OFI gate + spread/depth filter, but needs paper A/B before trust.
2. **ParameterSurface-only constraint** may cap how much edge we can add without engine changes. If R5/R6 hit the ceiling, *propose* (don't silently do) an engine change to the human.
3. **Wave vs main divergence:** two engines, two DBs, two branches. CEO must treat them as independent candidates; never let one's loop clobber the other (clobber-guard).
4. **Overfitting in auto-promotion:** walk-forward + sensitivity gates are the only defense; keep Monte Carlo drawdown checks strict.
5. **Funding/regime data latency:** depth+funding websockets add infra; ensure they don't reintroduce the freeze class of bug (all sockets timeout-guarded).

---

## 9. One-line summary for the parent

> Build the **Vaiśravaṇa fleet** as a 9-layer system (Feed → State → Decision → Risk/Sizing → Execution → Eval → CEO → Obs/Control → Deploy) on the existing repo, where the **Continuous-Evolution Orchestrator** safely tunes only the `ParameterSurface` behind strict walk-forward/Monte-Carlo promotion gates, and ship it in **7 phases (R1–R7)** that first make measurement honest and stop the fee bleed (R1–R2), then fix exit geometry and selection (R3–R4), then add real alpha via maker entries + order-flow (R5), then automate the improvement loop (R6) and harden observability (R7).
