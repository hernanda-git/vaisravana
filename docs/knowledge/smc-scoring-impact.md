# SMC → Scoring Impact — the win-rate lever, quantified

> Exact math linking [`smc-detector.md`](smc-detector.md) output to Vaiśravaṇa's 7-factor
> score and, through it, to win rate. This is the file that justifies the plug-in: it shows
> *why* proper SMC detection raises the confluence score and how that translates to fewer
> false entries and a higher WR.

---

## 1. The score the engine actually computes

From `src/engines.py` + `src/scoring.py` (`decide` / `score_side`), the chosen side's score:

```
chosen = Σ (weight_k · factor_k)      # weights sum to 1.0 (doc 21)
```

| factor | weight | SMC feeds it? | engine formula (relevant terms) |
|--------|--------|--------------|----------------------------------|
| trend | 0.30 | no (MA lens) | `regime_score` |
| momentum | 0.20 | candle only | `momentum_score` |
| volume | 0.15 | no | `volume_score` |
| **structure** | **0.15** | **yes** | `0.35 +0.20·bos +0.15·choch +0.15·(hh&hl) +0.15·(lh&ll) +0.15·body_ratio` |
| **liquidity** | **0.10** | **yes** | long: `0.5 +0.20·liq_sweep +0.10·eq_low +0.10·fvg` |
| atr | 0.05 | no | `atr_score` |
| funding_oi | 0.05 | no | `funding_oi_score` |

The plug-in moves **structure (15%)** and **liquidity (10%)** — 25% of the score — from
"floor-defaulted" to "real". That is the entire lever.

---

## 2. Before vs. after — the structural lift

### Before (live factory, doc 40 §1.4)
- `fvg = bos` → the `+0.10 fvg` term duplicates BOS information.
- sweep = one-bar reclaim vs prior-20 extremes → fires rarely, noisy when it does.
- No OB / premium-discount / displacement confirmation.
- Result: in many bars `bos/choch/liq_sweep/eq_*/fvg` are all `False` →
  `structure_score ≈ 0.35 + 0.15·body_ratio`, `liquidity_score ≈ 0.50`.
  **Those two factors contribute a near-constant ~0.10 (structure) + ~0.05 (liquidity) =
  ~0.15 of the 1.0 score, regardless of how good the setup is.** Alpha is dead.

### After (`smc.py`)
For a genuine A+ long (OB + sweep + CHoCH + FVG + discount):
- `structure` = `0.35 +0.20 +0.15 +0.15 +0.15·1.0` = **1.00** (capped) → ×0.15 = **0.150**
- `liquidity` = `0.5 +0.20 +0.10 +0.10` = **0.90** → ×0.10 = **0.090**

So proper detection adds up to **+0.090** to the total score on a real setup vs. the flat
~0.15 baseline contribution — i.e. it **creates the separation** between a real A+ confluence
and a mediocre one. Without it, a great setup and a mediocre one score almost identically on
the SMC dimensions, so the 0.90 `entry_threshold` can't distinguish them → entries that
should be SKIP become ENTRY (false positives, doc 23) → WR drops.

> **The win-rate mechanism is separation, not inflation.** SMC doesn't push every score up;
> it pushes *good* setups up and leaves *bad* ones down, so the 0.90 gate finally means
> something. That is exactly the doc 40 §2.5 criticism ("0.90 is calibrated so the math
> *can* reach it, not so 0.90 *means* 85% WR") answered by **information**, not by constants.

---

## 3. Worked example (numbers trace the engine)

Assume a bar where trend/momentum/volume/atr/funding are "average-good":
`trend=0.8, momentum=0.7, volume=0.8, atr=1.0, funding=1.0` (these are NOT SMC-driven).

**Mediocre setup (old factory, no real SMC):**
`structure=0.50, liquidity=0.50`
```
chosen = .30·.80 + .20·.70 + .15·.80 + .15·.50 + .10·.50 + .05·1.0 + .05·1.0
       = .240 + .140 + .120 + .075 + .050 + .050 + .050 = 0.725  → WATCH (under 0.90)
```
**A+ setup (smc.py populated):**
`structure=1.00, liquidity=0.90`
```
chosen = .30·.80 + .20·.70 + .15·.80 + .15·1.00 + .10·.90 + .05·1.0 + .05·1.0
       = .240 + .140 + .120 + .150 + .090 + .050 + .050 = 0.840  → still WATCH
```
Even with perfect SMC, a merely *average* trend/momentum/volume leaves it at 0.84 — the
gate correctly stays closed. Now make trend/momentum/volume genuinely bullish
(`trend=0.95, momentum=0.9, volume=1.0`):
```
chosen = .30·.95 + .20·.90 + .15·1.00 + .15·1.00 + .10·.90 + .05·1.0 + .05·1.0
       = .285 + .180 + .150 + .150 + .090 + .050 + .050 = 0.955  → ENTRY (BUY)
```
**Conclusion:** SMC is the *decisive* +0.09–0.15 that tips a genuinely aligned, confirmed
setup over 0.90 — and withholds it from unconfirmed ones. That is the win-rate lift.

---

## 4. Proposed enrichment (human-gated, NOT Sentinel-tunable)

Today `structure_score`/`liquidity_score` ignore `ob_bull/ob_bear/breaker/mitigation/
premium/discount/displacement_z`. Adding them is a **developer change behind tests**, not a
Sentinel change (the Sentinel only emits a `ParameterSurface`, `src/sentinel.py`). Suggested
additive terms (kept inside the existing 15%/10% ceilings so Σ-weights stays 1.0):

```python
# inside structure_score — additive, capped so base+terms ≤ 1.0
if s.ob_bull or s.ob_bear: sc += 0.10      # price at an institution's footprint
if s.breaker:               sc += 0.05      # OB flipped → continuation
if s.mitigation:            sc += 0.05      # returned to test the OB (entry trigger)

# inside liquidity_score — additive
if s.discount: sc += 0.05    # long entered in discount (value)
if s.premium:  sc += 0.05    # short entered in premium (value)
sc += 0.05 * _clamp(s.displacement_z / 3.0)   # conviction of the move
```

These are **optional** — the plug-in already lifts WR via §2's existing slots; §4 is the
"far better" upside once the team validates it in shadow. Each term must be A/B-tested in
the backtest harness (see `smc-verification.md`) before promotion; the Sentinel cannot
introduce them on its own.

---

## 5. Symmetry — why SHORT gets the same lift

`score_side(s, "SELL")` already uses `liquidity_score_bear` (sweep at `eq_high`, not
`eq_low`) and `1.0 - trend` for the bearish mirror (`src/scoring.py`). The detector populates
`eq_high`/`eq_low` and `ob_bear`/`ob_bull` **symmetrically**, so a genuine A+ short (bearish
OB + sweep of EQ-high + bearish CHoCH + premium) scores identically high on its own path.
No mirroring hack — LONG and SHORT are independent counters (doc 30 §5, doc 40 §2.6).

---

## 6. The expectancy caveat (honest — from doc 40 §2.1)

A higher hit rate helps only if **expectancy stays positive after fees**. doc 40 §2.1 notes
the current `tp_atr_mult≈1.05` vs `sl_atr_mult=1.0` needs ~95% hit rate to break even post-
fees. SMC improves this two ways:
1. **Higher hit rate** via cleaner entries (into OBs / FVG fills, not random retracements).
2. **Better R** — entering at an OB near `eq_low` means the SL (just below the sweep) is
   *tighter* than a blind ATR stop, while the TP can target the next liquidity pool. This
   widens R:R without loosening the 0.90 bar.

The verification plan ([`smc-verification.md`](smc-verification.md)) therefore reports
**expectancy (R) and profit factor alongside WR**, and uses **realistic taker fees**
(`backtest.py`: entry taker 0.05%, TP maker 0.02%, SL/MAXHOLD taker 0.05%) and **multi-bar
hold** (`MAX_HOLD_BARS=60`), per doc 40 §P1. A WR lift that comes with negative expectancy is
**not** accepted.

---

## 7. Acceptance math (what "better" means)

| Metric | Source of truth | Plug-in goal |
|--------|-----------------|--------------|
| Win rate (per pair×tf×side) | doc 30 §5 / `evaluation.py` | **↑** toward ≥85% |
| Expectancy (R) | doc 30 §5 | **> +0.2R** (must hold post-fee) |
| Profit factor | doc 30 §5 | **> 1.20** (target >1.30 for live) |
| False positives (ENTRY→SL) | `evaluation.false_positives` | **↓** |
| Entries fired | `decisions_log` | **sparser** (A+ only) — quality over quantity |
| Decision latency | doc 30 §1 (<200 ms) | **unchanged / faster** (O(n) detector) |

See [`smc-verification.md`](smc-verification.md) for the exact commands and gates.
