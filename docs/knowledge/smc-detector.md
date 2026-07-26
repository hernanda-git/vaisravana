# SMC Detector — Plug-in Engine Specification (`src/smc.py`)

> Implementation blueprint for the **opt-in** SMC detector. Pure functions, no I/O, no
> engine rewrite — it *feeds* the existing `MarketState` SMC slots so `structure_score`
> (15%) and `liquidity_score`/`_bear` (10%) carry real alpha. Companion to
> [`smc.md`](smc.md) and [`smc-scoring-impact.md`](smc-scoring-impact.md).

---

## 1. Design contract (why it is safe + fast)

1. **Pure** — input `list[Candle]` (or numpy arrays), output a dataclass. No network/DB.
   Mirrors `src/engines.py` ("Each engine is a PURE function").
2. **Additive** — returns an `SMCSnapshot`; a thin `apply_smc(state, snap)` merges flags
   onto `MarketState` (which already has safe defaults). No existing test breaks.
3. **Symmetric** — every detector yields LONG- and SHORT-usable fields.
4. **O(n)** — single forward pass with a rolling pivot window; optional incremental cache
   for the live per-minute loop (amortized O(1) per new bar).
5. **Honest** — every boolean derives from OHLCV; nothing invented (doc 30 §4, doc 40 §5).

---

## 2. Data model

```python
# src/smc.py
from __future__ import annotations
from dataclasses import dataclass, field
from marketdata import Candle

@dataclass
class SMCParams:
    """Detection thresholds. DESIGN-TIME constants (not on ParameterSurface).

    Rationale: the Sentinel may only tune the ParameterSurface (doc 21/24). Detection
    thresholds are structural; a developer changes them behind tests. Keeping them out of
    the surface prevents the autonomous loop from 'discovering' an over-fit threshold.
    """
    swing_window: int = 3          # bars left/right to confirm a pivot
    fvg_min_gap_pct: float = 0.0005  # min 3-candle imbalance as % of price
    ob_lookback: int = 20          # bars to look back for an OB origin
    ob_body_ratio: float = 0.6     # candle must be predominantly body (institutional)
    displacement_z: float = 1.5    # volume/size z-score for a "real" move
    liquidity_pool_window: int = 50  # window to find EQ highs/lows
    premium_discount_levels: tuple[float, float, float] = (0.5, 0.618, 0.786)  # Fib retrace

@dataclass
class SMCSnapshot:
    """All SMC facts for bar i. Booleans map 1:1 onto MarketState SMC slots;
    ranges/prices feed the proposed enrichment (smc-scoring-impact.md §4)."""
    # --- swing structure (existing MarketState slots) ---
    hh: bool = False
    hl: bool = False
    lh: bool = False
    ll: bool = False
    bos: bool = False           # break of prior swing
    choch: bool = False         # first reversal swing (MSS)
    # --- liquidity (existing slots) ---
    liq_sweep: bool = False     # wick-through of a pool then reclaim/reject
    eq_high: bool = False       # equal-high pool present + swept (short side)
    eq_low: bool = False        # equal-low pool present + swept (long side)
    fvg: bool = False           # 3-candle imbalance (DECOUPLED from bos)
    fvg_top: float = 0.0
    fvg_bottom: float = 0.0
    # --- order blocks (enrichment; additive fields) ---
    ob_bull: bool = False       # bullish OB: down-close candle before an up-move
    ob_bear: bool = False       # bearish OB: up-close candle before a down-move
    ob_high: float = 0.0
    ob_low: float = 0.0
    breaker: bool = False        # OB that flipped and is now resistance/support
    mitigation: bool = False     # price returned to test an OB (entry trigger)
    # --- premium / discount (enrichment) ---
    premium: bool = False        # price in top third of dealing range (short-favored)
    discount: bool = False       # price in bottom third (long-favored)
    # --- displacement (enrichment) ---
    displacement_z: float = 0.0  # magnitude of the last decisive move
    swing_high: float = 0.0
    swing_low: float = 0.0

    def as_marketstate_kwargs(self) -> dict:
        """The subset that maps onto existing MarketState SMC fields."""
        return {
            "hh": self.hh, "hl": self.hl, "lh": self.lh, "ll": self.ll,
            "bos": self.bos, "choch": self.choch,
            "liq_sweep": self.liq_sweep, "eq_high": self.eq_high, "eq_low": self.eq_low,
            "fvg": self.fvg,
        }
```

---

## 3. Core algorithms

### 3.1 Swing pivots (foundation for everything)
A swing high at `i` = `candles[i].h` is the max of `[i-w, i+w]`; swing low symmetric.
With `swing_window=3`, a pivot needs 3 bars on each side — standard SMC definition that
filters noise (vs. the current `prior-20 vs recent-10` heuristic which double-counts).

```python
def _swing_highs_lows(c: list[Candle], w: int) -> tuple[list[int], list[int]]:
    highs, lows = [], []
    for i in range(w, len(c) - w):
        if all(c[i].h >= c[j].h for j in range(i-w, i+w+1) if j != i):
            highs.append(i)
        if all(c[i].l <= c[j].l for j in range(i-w, i+w+1) if j != i):
            lows.append(i)
    return highs, lows
```
**Complexity:** O(n·w); with `w=3` it is effectively O(n). For the live loop, cache the
last `2w` pivots and only re-test the newest bar → O(1) amortized.

### 3.2 BOS / CHoCH / swing sequence
Walk the pivot lists; track the running `last_hh`, `last_hl`, `last_lh`, `last_ll`.
- `bos` (bull) = a candle close **above** `last_hh` after a HL existed.
- `choch` (bull) = first `hl` **higher** than the prior `ll` after a downtrend (MSS).
- Mirror for bear. This is exactly the `hh/hl/lh/ll` + `bos/choch` set the engine reads.

```python
def _structure(c, highs, lows) -> tuple[bool,bool,bool,bool,bool,bool]:
    # returns (hh, hl, lh, ll, bos, choch) — see smc-detector reference impl
    ...
```

### 3.3 Fair Value Gap (decoupled from BOS)
3-candle imbalance: for a **bullish FVG**, `candle[i-1].l > candle[i+1].h` (gap left
between candles i-1 and i+1, candle i is the displacement). Record `fvg_top`, `fvg_bottom`.
- This is the **fix** for `fvg = bos` in the live factory: FVG and BOS are now independent,
  so the `+0.1 fvg` term in `liquidity_score` adds *new* information instead of duplicating
  the `+0.2 bos` term in `structure_score`.

### 3.4 Liquidity sweep + Equal Highs/Lows
- **EQ pool**: two (or more) swing highs within `tick_tol` of each other → `eq_high` pool;
  swing lows → `eq_low` pool (window = `liquidity_pool_window`).
- **Sweep (long side)**: bar `i` makes a **wick** below `eq_low` (`bar.l < eq_low`) but
  **closes back above** it (`bar.c > eq_low`) → stop-hunt complete → `liq_sweep=True`,
  `eq_low=True`. Optionally require `displacement_z` on the reclaim candle (rejects noise).
- **Sweep (short side)**: mirror above `eq_high`.
- This replaces the crude `bar.l < prior_lo and bar.c > prior_lo` one-bar test, which
  misses wick-only sweeps and has no displacement filter.

### 3.5 Order Blocks (enrichment)
- **Bullish OB**: the *last down-close candle* immediately **before** a bullish displacement
  (a bos/choch up-move) where that candle's body ratio ≥ `ob_body_ratio`. The OB zone =
  that candle's range `[ob_low, ob_high]`.
- **Bearish OB**: mirror.
- **Mitigation** = price later returns into `[ob_low, ob_high]` (the entry trigger).
- **Breaker** = an OB that was violated and flipped to act as opposite-side liquidity
  (strong continuation signal). Detected when price breaks the OB and then uses it as
  support/resistance on the retest.

### 3.6 Premium / Discount (enrichment)
Define the **dealing range** as `[swing_low, swing_high]` of the current leg.
- `discount` = `last_close` ≤ `swing_low + 0.382·range` (long-favored).
- `premium`  = `last_close` ≥ `swing_high − 0.382·range` (short-favored).
Maps to the "enter at discount (long) / premium (short)" rule from the original `smc.md`.

### 3.7 Displacement
`displacement_z` = z-score of the bar's `|close−open|·volume` vs the trailing window. A
high value = institutions committed (filters exhaustion spikes, which `momentum_score`
already penalizes at 0.15). Used to *confirm* sweeps/OBs, not as a standalone entry.

---

## 4. Top-level entry point

```python
def detect_smc(candles: list[Candle], i: int,
               params: SMCParams | None = None) -> SMCSnapshot:
    """Pure SMC detection for bar i. O(n) over the window ending at i."""
    p = params or SMCParams()
    if i < p.swing_window * 2:
        return SMCSnapshot()                      # not enough context yet
    window = candles[max(0, i - p.liquidity_pool_window): i + 1]
    highs, lows = _swing_highs_lows(window, p.swing_window)
    hh, hl, lh, ll, bos, choch = _structure(window, highs, lows)
    fvg, ft, fb = _fvg(window, p.fvg_min_gap_pct)
    eq_hi, eq_lo = _eq_pools(highs, lows)
    sweep, s_eq_hi, s_eq_lo = _sweep(candles[i], eq_hi, eq_lo, p)
    ob_b, ob_be, ob_h, ob_l, breaker, mit = _order_blocks(window, bos, choch, p)
    prem, disc, sh, sl = _premium_discount(window)
    dz = _displacement(window, p.displacement_z)
    return SMCSnapshot(
        hh=hh, hl=hl, lh=lh, ll=ll, bos=bos, choch=choch,
        liq_sweep=sweep, eq_high=s_eq_hi, eq_low=s_eq_lo,
        fvg=fvg, fvg_top=ft, fvg_bottom=fb,
        ob_bull=ob_b, ob_bear=ob_be, ob_high=ob_h, ob_low=ob_l,
        breaker=breaker, mitigation=mit,
        premium=prem, discount=disc, displacement_z=dz,
        swing_high=sh, swing_low=sl,
    )

def apply_smc(state: "MarketState", snap: SMCSnapshot) -> "MarketState":
    """Merge detector output onto an existing MarketState (non-destructive copy)."""
    from dataclasses import replace
    return replace(state, **snap.as_marketstate_kwargs(),
                   # enrichment fields only if MarketState has them (additive)
                   ob_bull=snap.ob_bull, ob_bear=snap.ob_bear,
                   breaker=snap.breaker, mitigation=snap.mitigation,
                   premium=snap.premium, discount=snap.discount,
                   displacement_z=snap.displacement_z)
```

> **Note on enrichment fields:** `ob_bull/ob_bear/breaker/mitigation/premium/discount/
> displacement_z` are *additive* `MarketState` fields (default `False`/`0.0`). They are
> inert to today's engines until [`smc-scoring-impact.md` §4](smc-scoring-impact.md) is
> implemented behind tests. Adding them does **not** break existing code or the Σ-weights
> invariant (doc 21).

---

## 5. Performance design (the "speed" priority)

| Concern | Choice | Why |
|---------|--------|-----|
| Pivot scan | rolling window, cached last `2w` pivots in the live loop | O(1) amortized/bar |
| Arrays | optional `numpy` view of OHLC for `_fvg`/`_displacement` | vectorized, no Python loop |
| Allocation | one `SMCSnapshot` per bar; reuse buffers across pairs | low GC pressure |
| Branching | early `return SMCSnapshot()` when `i < 2·swing_window` | skip cold start |
| Determinism | no randomness; pure OHLCV math | reproducible backtests |

**Budget check:** with `n≈600` bars × ~12 pairs × 3 contexts, a single O(n) pass per
context per minute is well under the 200 ms decision budget (doc 30 §1). The detector runs
*once per new bar*, not per engine call.

---

## 6. What this module does NOT do (boundaries)

- Does **not** change weights, thresholds, or gates → that is the Sentinel's
  `ParameterSurface` (doc 21). The detector only supplies *inputs*.
- Does **not** call the exchange, DB, or LLM → pure math only.
- Does **not** decide side/entry → `decide()` / `decide_ctx()` own that.
- Does **not** invent liquidity → every flag traces to OHLCV (doc 40 §5 "honest flags").

See [`smc-wiring.md`](smc-wiring.md) for exactly where `detect_smc` is called, and
[`smc-verification.md`](smc-verification.md) for the test/backtest that proves it.
