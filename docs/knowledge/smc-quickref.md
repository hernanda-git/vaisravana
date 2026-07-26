# SMC Quick Reference — eng / ops cheat sheet

> One-page reference for the SMC plug-in ([`smc.md`](smc.md) family). Print this; read the
> spec files for why.

---

## A. The 25% lever (what SMC actually moves)

| Factor | Weight | SMC slot fed | Engine |
|--------|--------|--------------|--------|
| Structure | 15% | `hh hl lh ll bos choch` (+ `ob_*` `breaker` `mitigation`) | `structure_score` |
| Liquidity | 10% | `liq_sweep eq_high eq_low fvg` (+ `premium` `discount`) | `liquidity_score`/`_bear` |

The other 5 factors (trend 30 / momentum 20 / volume 15 / atr 5 / funding 5) are **not** SMC.
SMC's job: make those two factors *real* instead of floor-defaulted (doc 40 §1.4).

---

## B. Detector → slot map

| Detector output | → `MarketState` | Long use | Short use |
|-----------------|-----------------|----------|-----------|
| swing HH/HL | `hh`,`hl` | trend up | — |
| swing LH/LL | `lh`,`ll` | — | trend down |
| BOS | `bos` | breakout up | breakout down |
| CHoCH | `choch` | first reversal up | first reversal down |
| FVG (3-candle) | `fvg`,`fvg_top/bottom` | inefficiency fill | inefficiency fill |
| EQ-low sweep | `liq_sweep`,`eq_low` | **entry zone** | — |
| EQ-high sweep | `liq_sweep`,`eq_high` | — | **entry zone** |
| Bullish OB | `ob_bull` | footprint | — |
| Bearish OB | `ob_bear` | — | footprint |
| Breaker | `breaker` | cont. long | cont. short |
| Mitigation | `mitigation` | retest entry | retest entry |
| Discount / Premium | `discount`/`premium` | long value | short value |
| Displacement z | `displacement_z` | conviction | conviction |

**Rule of thumb:** ENTRY likes `choch + bos + liq_sweep(at EQ) + OB + displacement`, entered
at `discount`(long)/`premium`(short). Missing any → score stays under 0.90 → SKIP.

---

## C. The decision pipeline (per candle)

```
candles → detect_smc() → MarketState(SMC slots)
        → decide()  → dual score (long/short) → ENTRY/WATCH/SKIP
        → if ENTRY: decide_ctx() → BTC rudder + MTF stack boost/gate
        → Gate A (spread/cooldown/liquidity) + Gate B (SL dir/lev/DD)
        → open (PAPER) → SL/TP from ATR mults → monitor
```
SMC lives at step 1. It raises the *input* to step 2. It never decides side or size.

---

## D. Symptom → check

| Symptom | Likely cause | Check |
|---------|--------------|-------|
| WR high but expectancy negative | R:R too tight / fees | doc 40 §2.1; widen TP or tighten SL into OB |
| Entries too sparse | threshold 0.90 + gates strict | expected; raise quality, not quantity |
| Entries too many / bad | `fvg=bos` coupled, weak sweep | ensure `smc.py` decoupled FVG + displacement filter |
| LONG fires vs BTC dump | relational gate off | `decide_ctx` `ctx_gate_open` must block (doc 40 §1.4) |
| Test/vs-prod divergence | factory not using detector | wire per `smc-wiring.md` §2/§3 |
| Latency creep | python loop in detector | use numpy path / pivot cache |

---

## E. Knobs the Sentinel CAN tune (ParameterSurface, doc 21)

These are fair game for the autonomous loop — they are *weights/thresholds*, not detection
logic:

| Knob | Range | Effect on SMC |
|------|-------|---------------|
| `weights.structure` | 0.05–0.25 | how much structure matters |
| `weights.liquidity` | 0.00–0.20 | how much liquidity matters |
| `entry_threshold` | 0.85–0.92 | A+ bar strictness (default 0.90) |
| `watch_threshold` | 0.78–0.85 | WATCH cutoff |
| `sl_atr_mult` / `tp_atr_mult` | 0.8–2.0 / 1.0–2.0 | R:R of SMC entries |

Knobs the Sentinel **CANNOT** touch (detection is code, human-gated): `SMCParams`
(`swing_window`, `fvg_min_gap_pct`, `ob_body_ratio`, `displacement_z`,
`liquidity_pool_window`), and the engine source of `structure_score`/`liquidity_score`.

---

## F. One-line mental model

> **MTF MA = which side. SMC = is it real, and where. decide_ctx = does the market agree.
> The 0.90 gate = only A+ confluence enters. SMC is what makes "A+" mean something.**

---

## G. Files in this set

`smc-index.md` · `smc.md` · `smc-detector.md` · `smc-scoring-impact.md` ·
`smc-wiring.md` · `smc-verification.md` · `smc-quickref.md`
