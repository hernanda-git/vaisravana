# SMC Plug-in — Phase-by-Phase Execution Plan

> **Goal:** plug the SMC detector ([`smc-detector.md`](smc-detector.md)) into Vaiśravaṇa to
> raise win rate, accuracy, and speed — **without ever touching a running live session**
> and **without changing the `ParameterSurface`** the Sentinel owns. Every phase is
> shadow/PAPER-first, reversible per `(pair×tf×side)`.
>
> **Hard constraints (from the code, not opinion):**
> - `src/sentinel.py` may only emit a `ParameterSurface`; engine logic is out of reach → the
>   detector is a **new pure module** that *feeds* existing inputs, never rewrites them.
> - The bot is PAPER-only by design (`scripts/bot_paper.py` `ModeGuard`); there is no live
>   order path we can accidentally trip.
> - doc 40 §1.4: structure(15%)+liquidity(10%) were "starved" live — this plan fixes exactly
>   that, honestly, with a backtest==live code path.

---

## Dependency / sequencing map

```
Phase 0  Scaffold src/smc.py + tests/test_smc.py        (pure, no wiring)
   │
Phase 1  Wire into run_backtest_real.py → A/B on REAL klines   (prove lift, no risk)
   │
Phase 2  Wire into bot_paper.build_state_mtf + perf check       (live PATH, still PAPER)
   │
Phase 3  Relational stacking check (decide_ctx veto intact)
   │
Phase 4  [OPTIONAL] Enrich structure/liquidity_score with ob_*/premium/discount
   │        → behind its OWN shadow A/B (human-gated engine edit)
   │
Phase 5  Surface tuning: push structure/liquidity weights + thresholds via Sentinel
   │        (already legal; verify promotion gate)
   │
Phase 6  Shadow-promote per (pair×tf×side) + human review + OOS monitoring
   │
Phase 7  Docs finalize (glossary, changelog, smc.md cross-links)
```

Phases 0–3 are **mandatory** for the core lift. Phase 4 is the "far better" upside.
Phases 5–7 are operations/rollout.

---

## Phase 0 — Scaffold the detector (pure module + unit tests)

**Objective:** implement `src/smc.py` exactly as specified in [`smc-detector.md`](smc-detector.md).
No imports from `bot_paper`/exchange/DB. No wiring yet (dark).

**Files:** `src/smc.py` (new), `tests/test_smc.py` (new).

**Steps:**
1. Add `SMCParams`, `SMCSnapshot` dataclasses (§2 of detector spec).
2. Implement `_swing_highs_lows` (rolling pivot, `swing_window`), `_structure` (BOS/CHoCH/
   HH/HL/LH/LL), `_fvg` (**decoupled** from BOS — the doc 40 §1.4 fix), `_eq_pools`,
   `_sweep` (wick-through + reclaim + optional displacement filter), `_order_blocks`
   (OB + breaker + mitigation), `_premium_discount`, `_displacement`.
3. Implement `detect_smc(candles, i, params)` → `SMCSnapshot` and `apply_smc(state, snap)`.
4. Write `tests/test_smc.py` mirroring `tests/test_phase15_context.py` style: synthetic
   fixtures for each detector (see [`smc-verification.md` §1](smc-verification.md)).

**Verification:**
```bash
python -m pytest tests/test_smc.py -q
python -m pytest -q            # full suite must stay green (baseline 105/105)
```
**Acceptance gate:** `test_smc.py` green; full suite still 105/105; `import smc` has zero
network/DB side effects (assert by importing in isolation). **No running session affected**
(the module is never imported by the bot yet).

**Rollback:** delete `src/smc.py` + `tests/test_smc.py`. Zero impact.

---

## Phase 1 — Honest A/B on REAL data (backtest, no live)

**Objective:** prove the win-rate lift using the project's **real** harness + real klines,
with honest fees/hold (doc 40 §P1). This is the headline acceptance step.

**Files:** `scripts/run_backtest_real.py` (modify factory only), `reports/bt_base.md`,
`reports/bt_smc.md`, `reports/smc_ab_report.md`.

**Steps:**
1. In `run_backtest_real.py:state_factory_mtf`, add an **opt-in toggle** (env
   `VAISRAVANA_SMC=0|1`). When `0` → current inline heuristic (baseline). When `1` →
   `detect_smc` (candidate), per [`smc-wiring.md` §3](smc-wiring.md).
2. Run baseline: `VAISRAVANA_SMC=0 python scripts/run_backtest_real.py` → `bt_base.md`.
3. Run candidate: `VAISRAVANA_SMC=1 python scripts/run_backtest_real.py` → `bt_smc.md`.
4. Compute `evaluate()` per `(pair,tf,side)` on each run's DB; build `smc_ab_report.md`
   (IS/OOS columns, per [`smc-verification.md` §2/§3](smc-verification.md)).

**Verification:** same commands as steps 2–4; inspect `reports/smc_ab_report.md`.

**Acceptance gate (ALL must hold):**
- WR: candidate ≥ baseline, trending toward ≥85% per key.
- **Expectancy > +0.2R AND ≥ baseline** (reject if WR↑ but expectancy negative — doc 40 §2.1).
- Profit factor > 1.20 (target >1.30).
- Max DD < 3% and ≤ baseline.
- False positives ↓; entries sparser (A+ only).

**Rollback:** keep `VAISRAVANA_SMC=0` default. Candidate never reached a running session.
If gates fail → stay on baseline, revisit `SMCParams` behind tests.

---

## Phase 2 — Wire into the live factory + performance

**Objective:** make the **live path** use the same detector (closes the test/vs-prod
divergence, doc 40 §1.4). Bot stays PAPER.

**Files:** `scripts/bot_paper.py` (`build_state_mtf` only).

**Steps:**
1. In `build_state_mtf` (`bot_paper.py` ~L150), replace the inline `hh/hl/.../fvg=sweep`
   block with `detect_smc(window, len(window)-1)` + `apply_smc(st, snap)`, keeping
   `htf_bias`/`mtf_aligned` from the existing EMA-cross logic (per [`smc-wiring.md` §2](smc-wiring.md)).
2. `dec_candles` is already held by the loop — **no new fetch**, no new network cost.
3. Performance micro-benchmark (per [`smc-verification.md` §5](smc-verification.md)):
   median detect time over 600-bar × 12 contexts.

**Verification:**
```bash
python -m pytest tests/test_phase15_context.py -q   # relational tests still pass
python -c "from smc import detect_smc,SMCParams; ..."   # < 5 ms/bar median
```
Optionally run the bot briefly in PAPER against `data/klines/` or a sandbox DB to confirm
`decisions_log` now carries populated SMC slots (spot-check a few rows).

**Acceptance gate:** relational tests green; detector **< 5 ms/bar**; `decisions_log`
SMC columns non-floor for bars where structure exists. **Still PAPER — no live orders.**

**Rollback:** revert `build_state_mtf` to the heuristic block (git checkout). The bot
already falls back to heuristic if `smc` import fails (wrap in try/except → safe degrade).

---

## Phase 3 — Relational stacking check

**Objective:** confirm SMC raises the *single-name* score while `decide_ctx` still enforces
the cross-asset veto (BTC rudder + MTF stack). Both layers must stay intact.

**Files:** extend `tests/test_phase15_context.py` (or `tests/test_smc.py`).

**Steps:**
1. Build a `MarketState` with rich SMC slots (ob_bull, liq_sweep, choch all True) **and**
   `btc_bias="bearish"`, `risk_regime="bearish"`.
2. Assert `decide_ctx(s).decision in ("WATCH","SKIP")` — the relational hard-gate wins.

**Verification:** `python -m pytest tests/test_phase15_context.py -q`.

**Acceptance gate:** test passes. SMC + `decide_ctx` compose correctly (micro + macro).

**Rollback:** n/a (test-only addition).

---

## Phase 4 — [OPTIONAL] Enrich the engines (human-gated)

**Objective:** capture the extra lift from `ob_*`/`breaker`/`mitigation`/`premium`/`discount`
by adding small additive terms inside `structure_score`/`liquidity_score`
([`smc-scoring-impact.md` §4](smc-scoring-impact.md)).

**Why it is a SEPARATE phase:** this **edits engine source** → it is *not* Sentinel-tunable
and must go through human review + its own shadow A/B (the Sentinel cannot introduce it).

**Files:** `src/engines.py` (`structure_score`, `liquidity_score`/`_bear`), new shadow A/B.

**Steps:**
1. Add the capped additive terms (≤ existing 15%/10% ceilings; Σ-weights stays 1.0).
2. Run the Phase 1 A/B again with the enrichment on; compare to Phase 1 candidate.
3. Only promote if WR↑ **and** expectancy↑ **and** MaxDD↓.

**Acceptance gate:** strictly better than Phase 1 candidate on all gates; full suite green.

**Rollback:** revert `src/engines.py` (git checkout). Core lift from Phases 0–3 stands
without this.

---

## Phase 5 — Surface tuning via the Sentinel (legal, bounded)

**Objective:** let the autonomous loop nudge *weights/thresholds* (which it legally owns) to
favor SMC now that SMC inputs are real. Nothing here is new code — it uses existing knobs.

**Knobs (doc 21, already on `ParameterSurface`):** `weights.structure` (0.05–0.25),
`weights.liquidity` (0.00–0.20), `entry_threshold` (0.85–0.92), `watch_threshold`
(0.78–0.85), `sl_atr_mult`/`tp_atr_mult` (affect SMC-entry R:R).

**Steps:**
1. The Sentinel proposes Δ ≤ ±10%, ≤4 changes/cycle, Σ=1.0 → `shadow_compare` on raw
   candles (`src/shadow.py`) → promote only if shadow ≥ baseline & health ↑
   (`src/sentinel.py:ShadowComparison`).
2. Watch that it does **not** lower `entry_threshold` to fake a WR lift — the lift must
   come from separation (smc-scoring-impact.md §2), validated by expectancy.

**Acceptance gate:** any promoted surface still satisfies Phase 1 gates on OOS.

**Rollback:** `Sentinel.cycle` auto-rolls-back on non-promotion; `surface.json` reverts.

---

## Phase 6 — Shadow-promote per (pair×tf×side) + monitor

**Objective:** turn the plug-in on for **specific keys only**, behind the doc 30 §6 gate,
with OOS decay monitoring (doc 40 §P1/P2).

**Steps:**
1. Enable `VAISRAVANA_SMC=1` for a few `(pair,tf,side)` in shadow (e.g. BTCUSDT/5m LONG).
2. Evaluate per key (WR ≥85%, expectancy >+0.2R, PF >1.3, MaxDD <3%) over ≥200 trades.
3. Human review the `eval_report` → promote those keys; leave others on baseline.
4. Monitor OOS decay; if a key's WR <85% post-promotion → Sentinel reverts/disable that key.

**Acceptance gate:** promoted keys pass doc 30 §6; no key promoted without human approval;
global kill-switch (`daily_loss≥0.5%`, ADL≥4, feed frozen) still wired (doc 40 §1.2).

**Rollback:** per-key disable in `build_state_mtf`/surface; never global.

---

## Phase 7 — Docs finalize

**Objective:** close the loop in the knowledge base + project docs.

**Steps:**
1. Update `docs/31-glossary.md`: add `SMC detector`, `OB`, `FVG (decoupled)`, `sweep`.
2. Add a CHANGELOG entry (matches `CHANGELOG.md` convention) referencing the phase set.
3. Cross-link `smc.md` ↔ `06-liquidity.md` ↔ `01-market-structure.md` ↔ `08-multi-timeframe.md`.
4. Mark this plan's phases DONE as each ships.

**Acceptance gate:** glossary + changelog updated; `smc-index.md` reading order consistent.

---

## Phase → artifact traceability

| Phase | New/changed file | Touches running session? |
|-------|------------------|--------------------------|
| 0 | `src/smc.py`, `tests/test_smc.py` | No (not imported by bot) |
| 1 | `scripts/run_backtest_real.py` (toggle), `reports/*` | No (backtest only) |
| 2 | `scripts/bot_paper.py` (`build_state_mtf`) | No (PAPER path) |
| 3 | `tests/test_phase15_context.py` | No (test only) |
| 4 | `src/engines.py` | No (needs shadow A/B first) |
| 5 | `surface.json` (Sentinel-owned) | No (bounded, auto-rollback) |
| 6 | per-key enable + eval_report | No (shadow→human→per-key) |
| 7 | `docs/31-glossary.md`, `CHANGELOG.md` | No (docs) |

**Every phase is reversible and never affects a live order.** The plan is complete through
promotion; the only human decision points are Phase 4 (enrich?) and Phase 6 (which keys?).
