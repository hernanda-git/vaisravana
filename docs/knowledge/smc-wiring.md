# SMC Wiring & Guardrails — where the plug-in lives

> Integration points for [`smc-detector.md`](smc-detector.md), the Sentinel constraint that
> shapes the design, and the guardrails that keep it safe. Companion to
> [`smc.md`](smc.md) and [`smc-verification.md`](smc-verification.md).

---

## 1. The Sentinel constraint (why a new module, not an engine edit)

`src/sentinel.py` is explicitly bounded (doc 20/21/24):
- Only the **`ParameterSurface`** may change.
- Engine logic, execution code, telemetry schema are **structurally out of reach** — any
  non-surface proposal path raises `SentinelViolation`.
- Per-weight Δ ≤ ±10%, ≤4 changes/cycle, Σ weights renormalized to 1.0.

**Consequence for the plug-in:** `src/smc.py` is a *new* module that **feeds** existing
engine inputs. It does not alter `structure_score`/`liquidity_score` source code. Therefore:
- The Sentinel's safety envelope is **unaffected**.
- The plug-in is opt-in: `detect_smc` is called only where the factory chooses to call it.
- Turning it on/off is a **code toggle**, not a surface change — safe to ship dark (compute
  but don't apply) and flip per `pair×tf` in shadow (doc 30 §8).

> If the team later adopts the §4 enrichment of `smc-scoring-impact.md`, that *is* an engine
> edit and must go through **human review + tests + shadow** — never the autonomous Sentinel.

---

## 2. Integration point A — live factory (`scripts/bot_paper.py`)

`build_state_mtf` currently derives structure/liquidity heuristically (doc 40 §1.4). Replace
that block with the detector:

```python
# scripts/bot_paper.py — inside build_state_mtf, after htf_bias is known
from smc import detect_smc, SMCParams
# build the full candle window for the DECISION_TF + structural contexts
window = dec_candles[max(0, i - SMCParams().liquidity_pool_window): i + 1]
snap = detect_smc(window, len(window) - 1, SMCParams())
st = build_state(pair, DECISION_TF, dec_candles, i)
state = apply_smc(st, snap)
state.htf_bias = htf_bias
state.mtf_aligned = mtf_aligned
# keep existing cross-asset/MTF relational fill (unchanged)
```

Notes:
- `dec_candles` is the 1m (`DECISION_TF`) series the loop already holds — no extra fetch.
- Structural-context bias (`htf_bias`) is still supplied by the existing EMA-cross logic;
  SMC operates on the same window, so no new network cost.
- `apply_smc` only overwrites the SMC slots; everything else (`regime`, `vol_z`, `atr_pct`,
  `spread_bps`, cross-asset fields) is untouched.

---

## 3. Integration point B — backtest factory (`scripts/run_backtest_real.py`)

`state_factory_mtf` is where honest detection matters most for validation. Swap its inline
`hh/hl/.../fvg` block for `detect_smc` so the **backtest == live** (closes the doc 40 §1.4
test/vs-production divergence):

```python
# run_backtest_real.py — inside state_factory_mtf's factory()
from smc import detect_smc, SMCParams
win = candles[max(0, i - SMCParams().liquidity_pool_window): i + 1]
snap = detect_smc(win, len(win) - 1, SMCParams())
st = single(candles, i)              # existing regime/vol/atr math
mstate = apply_smc(st, snap)
mstate.htf_bias = htf_bias; mstate.mtf_aligned = mtf_aligned
return mstate
```

This guarantees the WR lift measured in `smc-verification.md` is the *same* code path that
runs live.

---

## 4. Integration point C — `decide_ctx` (relational modulator, unchanged)

SMC is the **single-name** microstructure layer; `decide_ctx` (`src/scoring.py` +
`src/marketcontext.py`) is the **cross-asset/MTF** modulator. They stack, they don't
overlap:

```
MarketState (with SMC slots populated)
   → decide()  → dual score (BUY/SELL)        # SMC raises structure+liquidity here
   → if ENTRY: decide_ctx() → MarketContext boost / hard gate   # BTC rudder + MTF stack
```

No change to `decide_ctx` is needed — SMC simply makes the `MarketState` it receives
richer, so the existing boost/clamp acts on better information.

---

## 5. Guardrails (keep the system safe)

| Guardrail | Mechanism | Doc |
|-----------|-----------|-----|
| Detection never changes risk | detector only sets SMC booleans; SL/TP still from ATR mults in orchestrator | doc 30 §3 |
| No over-fit thresholds in autonomous loop | `SMCParams` are code constants, not on `ParameterSurface` | doc 21/24 |
| Honest flags only | every boolean from OHLCV; no invented liquidity | doc 40 §5 |
| Double-count prevention | `fvg` decoupled from `bos` (§3.3 detector) | doc 40 §1.4 |
| Symmetry enforced | LONG/SHORT detectors independent; no mirror hack | doc 30 §5 |
| Rollback path | opt-in toggle; if WR decays post-promotion, disable per `pair×tf×side` | doc 30 §6/§7 |
| No new I/O | pure functions; no DB/network in `smc.py` | engines contract |

---

## 6. Rollout sequence (safe, shadow-first — doc 30 §1/§8)

1. **Implement** `src/smc.py` + `tests/test_smc.py` (unit: synthetic OB/sweep/FVG fixtures).
2. **Dark-run** in backtest: compute `detect_smc` but compare score with/without applying it
   (`decisions_log` can log both via a shadow column) — proves lift without risk.
3. **Shadow promote** the *factory* change on a few `(pair×tf×side)`; evaluate WR/expectancy/
   PF per doc 30 §5.
4. **Human review** the eval report; if all gates pass, enable live for those keys only.
5. **Monitor** OOS decay (doc 40 §P1/§P2); rollback any key whose WR falls <85%.

> The plug-in is *additive and reversible at every step* — it never affects sessions that
> don't opt in, and never touches the running surface.

---

## 7. What NOT to do

- ❌ Don't put `SMCParams` on the `ParameterSurface` (lets the Sentinel over-fit detection).
- ❌ Don't make `structure_score`/`liquidity_score` read SMC fields without tests + shadow.
- ❌ Don't call the exchange inside `smc.py`.
- ❌ Don't assume "SMC for longs, mirror for shorts" — both paths detected independently.
- ❌ Don't inflate scores by lowering `entry_threshold` to fake a WR lift — the lift must
  come from *separation* (smc-scoring-impact.md §2), validated by expectancy, not by a
  softer gate.
