# SMC Verification Plan — prove the win-rate lift on real data

> E2E plan to verify [`smc-detector.md`](smc-detector.md) actually raises win rate,
> accuracy, and speed — without affecting any running session. Uses the project's **real**
> harness (`BacktestHarness`, `evaluate`, `decide_ctx`) and the **real** klines already in
> `data/klines/`. Companion to [`smc-wiring.md`](smc-wiring.md).

> **These are acceptance gates to be measured when the plug-in is implemented — not
> measured results.** The docs define the plug-in; running the commands below is the dev's
> verification step (sandbox / reports DB only; no live orders, no surface change).

---

## 1. Unit tests (fast, deterministic) — `tests/test_smc.py`

Synthetic fixtures prove each detector independently. Mirror the style of
`tests/test_phase15_context.py` (pure `MarketState`, no network).

| Test | Fixture | Assert |
|------|---------|--------|
| swing pivots | simple HH/HL ladder | `hh`, `hl` True; `lh`,`ll` False |
| BOS | close above last HH | `bos` True |
| CHoCH | first HL > prior LL after downtrend | `choch` True |
| FVG (decoupled) | 3-candle gap, no BOS | `fvg` True, `bos` False (proves decoupling) |
| EQ-low sweep | wick below EQ-low, close reclaims | `liq_sweep`, `eq_low` True |
| EQ-high sweep | wick above EQ-high, close rejects | `liq_sweep`, `eq_high` True |
| Bullish OB | down-close candle before up-move | `ob_bull` True |
| Bearish OB | up-close candle before down-move | `ob_bear` True |
| Premium/Discount | close in top/bottom third of leg | `premium`/`discount` correct |
| Symmetry | same structure, flipped | LONG and SHORT detectors independent |
| Purity | no network/DB imports in `smc.py` | `import smc` has zero I/O side effects |

Run:
```bash
python -m pytest tests/test_smc.py -q
```
Acceptance: **all green**, and `pytest` overall stays at the project's 105/105 baseline
(`src/sentinel.py` + `decision.py` side=None fixes from doc 40 §6 unchanged).

---

## 2. Backtest A/B — the headline proof

Reuse `scripts/run_backtest_real.py` but run it **twice**: once with the existing factory
(BLUEPRINT/baseline) and once with `detect_smc` wired per `smc-wiring.md` §3 (CANDIDATE).
Both use the **same** `data/klines/{BTC,ETH,SOL}{5m,15m}.json` and the **same** honest
fee/host model from `src/backtest.py` (entry taker 0.05%, TP maker 0.02%, SL/MAXHOLD taker
0.05%; `MAX_HOLD_BARS=60`) — per doc 40 §P1.

```bash
# baseline (current factory)
python scripts/run_backtest_real.py            # writes reports/backtest_report_real.md
mv reports/backtest_report_real.md reports/bt_base.md

# candidate (smc.py wired into state_factory_mtf)
#   — flip the opt-in toggle in run_backtest_real.py: factory uses detect_smc
python scripts/run_backtest_real.py
mv reports/backtest_report_real.md reports/bt_smc.md
```

Compare per `(pair, tf, side)` using `evaluation.evaluate` on each run's DB:
```python
from evaluation import evaluate
for pair,tf,side in [...]:
    base = evaluate(base_conn, pair, tf, side)
    cand = evaluate(cand_conn, pair, tf, side)
    # cand.win_rate_pct >= base.win_rate_pct  (the lift)
    # cand.expectancy_r  >  +0.2R  AND  >= base (doc 40 §2.1: must stay positive post-fee)
    # cand.profit_factor >  base
    # cand.max_dd_pct    <  base (stability-first)
```

### Acceptance gates (all must hold)

| Metric | Gate | Why |
|--------|------|-----|
| Win rate | **candidate ≥ baseline**, and per-key trend toward ≥85% | the core ask |
| Expectancy | **> +0.2R** and **≥ baseline** | doc 40 §2.1 — no fake WR via negative expectancy |
| Profit factor | **> 1.20** (ideally >1.30) | doc 30 §5 |
| Max DD | **< 3%** and ≤ baseline | stability-first (doc 30 §7) |
| False positives | **↓** vs baseline | `evaluation.false_positives` |
| Entries fired | **sparser** (A+ only) | quality over quantity; the 0.90 gate means more |
| Latency | detection adds **< 5 ms** per bar | doc 30 §1 (<200 ms budget) |

> If candidate WR rises but expectancy goes negative → **reject** (doc 40 §2.1). The plug-in
> must improve *both*, which is exactly what entering into OBs/FVG (tighter SL, better R)
> is designed to do (smc-scoring-impact.md §6).

---

## 3. In-sample / out-of-sample split

`src/backtest.py:split` already provides rolling IS/OOS. Report **both**; the OOS column is
the honest one (doc 40 §P1/§P2, group E). Promotion requires OOS to hold the gates above,
not just IS (guards against over-fit detection thresholds).

---

## 4. Relational stacking check

Confirm `decide_ctx` still blocks a high-SMC long that fights BTC's rudder:
```python
# extend tests/test_phase15_context.py
s = MarketState(...); s.btc_bias="bearish"; s.risk_regime="bearish"
# populate SMC slots richly (ob_bull, liq_sweep, choch all True)
ctx_dec = decide_ctx(s, default_surface())
assert ctx_dec.decision in ("WATCH", "SKIP")   # relational hard-gate still wins
```
SMC raises the single-name score; `decide_ctx` still enforces the cross-asset veto. Both
layers intact.

---

## 5. Performance check (the "speed" priority)

Micro-benchmark the detector over a 600-bar window for all 12 `(pair×tf)` contexts:
```python
import time, statistics
from smc import detect_smc, SMCParams
ts = [time.perf_counter() for _ in range(N) for _ in detect_once()]  # N repeats
print(statistics.median(dt)*1000, "ms/bar")   # target < 5 ms
```
Acceptance: **median < 5 ms/bar** (well inside the 200 ms decision budget, doc 30 §1), and
**no** allocation growth across pairs (buffer reuse). Optional numpy path must not regress.

---

## 6. Reporting

Write the A/B result to `reports/smc_ab_report.md` (same 4-file format as doc 26):
- baseline vs candidate per `(pair,tf,side)` table (WR / Exp / PF / MaxDD / FP / entries).
- IS vs OOS columns.
- latency median.
- verdict: PROMOTE (all gates) / ROLLBACK (any gate failed) — mirrors `Sentinel` semantics.

---

## 7. What "done" looks like

- [ ] `tests/test_smc.py` green; full suite still 105/105.
- [ ] A/B backtest shows WR ↑, expectancy > +0.2R, PF ↑, MaxDD ↓, FP ↓, entries sparser.
- [ ] OOS holds the gates (not just IS).
- [ ] `decide_ctx` relational veto still fires on SMC-rich-but-rudder-fighting setups.
- [ ] Detector < 5 ms/bar.
- [ ] Report written; human review → shadow promote per `pair×tf×side` (doc 30 §6).

Only after all seven is the plug-in "far better, not worse" — and only then does it touch a
running session, per `(pair×tf×side)` promotion.
