# Smart Money Concepts (SMC) + Multi-Timeframe MA — *Vaiśravaṇa-aligned*

> Companion to [`smc-index.md`](smc-index.md). This file re-anchors the SMC doctrine to
> Vaiśravaṇa's **actual** runtime: the 9-engine dual-score stack, the `MarketState` SMC
> slots, and the `decide_ctx` relational modulator. The mechanical detector spec lives in
> [`smc-detector.md`](smc-detector.md); the win-rate math in
> [`smc-scoring-impact.md`](smc-scoring-impact.md).

---

## 0. Why this doc exists (and what changed vs. the original)

The original `smc.md` was a *generic* SMC primer. It was correct but disconnected from
the codebase: it never named the slots the engine reads, the weights those slots feed, or
the plug-in that is missing. This revision keeps the doctrine and binds every concept to a
**concrete, verifiable** part of Vaiśravaṇa:

| SMC concept | Vaiśravaṇa home | Doc |
|-------------|-----------------|-----|
| Trend filter (MTF MA) | `regime_score` + `htf_bias` | `08-multi-timeframe.md`, `src/engines.py` |
| Order Block | `smc.py` → `ob_bull`/`ob_bear` → `structure_score` | `smc-detector.md` |
| FVG | `smc.py` → `fvg` (decoupled from `bos`) | `06-liquidity.md`, `smc-detector.md` |
| Liquidity sweep / EQ highs-lows | `liq_sweep`, `eq_high`, `eq_low` | `06-liquidity.md` |
| BOS / CHoCH / MSS | `bos`, `choch`, `hh/hl/lh/ll` | `01-market-structure.md` |
| Premium / Discount | `premium`, `discount` (enrichment) | `smc-scoring-impact.md` |
| Breaker / Mitigation blocks | `breaker`, `mitigation` (enrichment) | `smc-detector.md` |
| Displacement | `displacement_z` (enrichment) | `09-smart-candle-analysis.md` |

The single most important correction: **SMC is not a separate strategy here — it is the
microstructure input layer that makes the existing 15% structure + 10% liquidity factors
real instead of floor-defaulted.** (doc 40 §1.4: those two factors were "starved" live.)

---

## 1. Objective

Build a *probabilistic* read of:

- Market trend (MTF MA — strategic compass)
- Institutional intent (SMC — tactical map)
- Liquidity (where stops/entries cluster)
- Market structure (BOS/CHoCH/swing sequence)
- High-probability entry zones (OB / FVG / premium-discount reversion into an OB)
- Risk placement (SL beyond swept liquidity / invalidated structure)

…so the **7-factor confluence score** (`src/engines.py`, doc 10) only clears the
`entry_threshold` (default **0.90**, doc 30 §3) on genuine A+ setups. Higher-quality
confluence → fewer, better entries → higher win rate without loosening risk.

---

## 2. Core Philosophy (unchanged in spirit, now engine-bound)

Retail asks *"is price above the EMA?"* — a lagging, single-instrument question.
Professionals ask:

- Who is in control? → `regime_score` + `htf_bias` (the MA lens)
- Where did institutions accumulate / distribute? → `ob_bull` / `ob_bear`
- Where is liquidity? → `liq_sweep`, `eq_high`, `eq_low`, `fvg`
- Has structure shifted? → `bos`, `choch`, `hh/hl/lh/ll`
- Was the breakout genuine or engineered? → sweep + displacement + CHoCH triad
- Premium or discount vs. the dealing range? → `premium` / `discount`

SMC answers these by reading price *as institutional behavior*, not as an indicator output.

---

## 3. Separation of Responsibilities (maps to the stack)

| Concern | Owner in Vaiśravaṇa | Weight | Reads SMC? |
|---------|---------------------|--------|-----------|
| Should I look for longs or shorts? | MTF MA → `regime_score` + `htf_bias` | **trend 30%** | no (MA lens) |
| Momentum / exhaustion | `momentum_score` | 20% | candle only |
| Volume confirmation | `volume_score` | 15% | no |
| **Where do I enter / is structure valid?** | `structure_score` | **15%** | **yes** |
| **Liquidity / sweep / FVG** | `liquidity_score`/`_bear` | **10%** | **yes** |
| Volatility sweet-spot | `atr_score` | 5% | no |
| Funding/OI sanity | `funding_oi_score` | 5% | no |
| Cross-asset + MTF stack | `decide_ctx` modulator | — (boost/clamp) | via `MarketContext` |

Think of MTF MA as the **strategic compass**, SMC as the **tactical map**, and
`decide_ctx` as the **air-traffic controller** that blocks trades fighting BTC's rudder.

---

## 4. Institutional Workflow (now a per-candle pipeline)

The original 5-step workflow maps 1:1 onto the bot's per-candle cycle
(`src/decision.py:DecisionOrchestrator.process`):

1. **Higher-TF bias** → `regime_score` (EMA20/50 slope) + `htf_bias` (1h/4h).
2. **Wait / retrace** → no chase; the detector looks for price returning into an OB or
   discount zone on the LTF.
3. **Observe structure** → `smc.py` sets `bos`/`choch`/`liq_sweep`/OB. No confirmation
   (all three-layer confluence absent) → the 15%+10% factors stay low → score stays
   under threshold → **SKIP**.
4. **Execute** → only after `decide()` returns `ENTRY` (score ≥ `entry_threshold`) **and**
   both gates pass (`src/gate.py` TwoLayerGate). For LONG: SL below swept liquidity; for
   SHORT: SL above (Gate B enforces SL direction — doc 25 §2).
5. **Risk** → SL beyond liquidity / invalidated structure; R:R ~1.0 (doc 30 §3).

### Typical LONG workflow (engine-readable)
```
htf_bias=bullish  (1h/4h EMA20>EMA50)
   ↓
pullback_to_anchor=True  (LTF dipped into HTF bias, resumed)   [marketcontext]
   ↓
price enters Bullish OB  → ob_bull=True  + discount=True
   ↓
liq_sweep=True (EQ-low swept, reclaimed) + eq_low=True
   ↓
choch=True (first HL after a bear leg) → bos=True (HH printed)
   ↓
displacement_z high (strong bullish candle, not exhaustion)
   ↓
decide() → long_score ≥ 0.90 → ENTRY(BUY)
   ↓
Gate A (spread<5bps, cooldown, liquidity) + Gate B (SL<entry, lev≤cap)
   ↓
target next sell-side liquidity (EQ-high / prior high)
```

### Typical SHORT workflow (symmetric — first-class, not mirrored)
```
htf_bias=bearish
   ↓
pullback_to_anchor=True
   ↓
price enters Bearish OB → ob_bear=True + premium=True
   ↓
liq_sweep=True (EQ-high swept, rejected) + eq_high=True
   ↓
bearish choch + bos
   ↓
decide() → short_score ≥ 0.90 → ENTRY(SELL)
   ↓
Gate B enforces SL>entry
   ↓
target next buy-side liquidity (EQ-low / prior low)
```

---

## 5. Decision Hierarchy (unchanged, now with the SMC owner noted)

```
Trend (regime_score + htf_bias)
  ↓
Bias (BUY / SELL / WATCH / SKIP)        ← decide() dual-score
  ↓
Liquidity (liq_sweep, eq_*, fvg)        ← smc.py + liquidity_score
  ↓
Market Structure (hh/hl/lh/ll, bos, choch) ← smc.py + structure_score
  ↓
Confirmation (displacement + sweep + choch) ← smc.py
  ↓
Entry (price/SL/TP/R:R)                  ← orchestrator + Gate B
  ↓
Risk Management (SL beyond liquidity)    ← Gate B + monitoring
  ↓
Trade Management (trailing/maxhold)      ← lifecycle + monitor
```
Never reverse this order — entries are searched for **only after** trend + context exist.

---

## 6. AI / Engine Decision Framework (Vaiśravaṇa phrasing)

The engine answers, *in order*, per `MarketState`:

- **Trend** — `regime` + `htf_bias`: trending_bull/bear, range, breakout, high_vol?
- **Bias** — `decide()` returns `side ∈ {BUY, SELL, None}` + `decision ∈ {ENTRY, WATCH, SKIP}`.
- **Liquidity** — `liq_sweep`, `eq_high`, `eq_low`, `fvg`: where is the pool?
- **Institutional zones** — `ob_bull`, `ob_bear`, `breaker`, `mitigation`, `premium`, `discount`.
- **Market structure** — `hh/hl/lh/ll`, `bos`, `choch` (the swing sequence + MSS).
- **Confirmation** — sweep cleared + structure confirms + displacement present.
- **Entry** — `entry_price`, `sl_price`, `tp_price`, R:R (orchestrator from ATR mults).

---

## 7. Guiding Principles (the project's, made explicit)

- Trend provides **context**, not an entry. SMC provides **execution precision**, not trend.
- Liquidity **attracts** price; institutions take liquidity *before* the real move.
- Structure carries more information than any single candle — the detector reads the
  **sequence**, not the last bar.
- Confirmation precedes execution; no CHoCH/sweep → no trade.
- Patience is a strategic advantage — the 0.90 bar is *designed* to fire rarely.
- A high-probability setup = multiple **aligned** factors, not one indicator.
- **Symmetry**: LONG and SHORT are evaluated as independent counters (doc 30 §5). The
  detector must never assume "SMC for longs, mirror for shorts."

---

## 8. What the plug-in changes (summary)

| Before (doc 40 §1.4) | After (`smc.py` plug-in) |
|----------------------|--------------------------|
| `fvg = bos` (coupled booleans) | `fvg` = independent 3-candle imbalance |
| sweep = one-bar reclaim vs prior-20 extremes | sweep = wick-through + displacement + EQ-pool hit |
| no OB / breaker / premium-discount | OB + breaker + mitigation + premium/discount detected |
| structure+liquidity at dataclass floors in many bars | both factors populated every bar they apply |
| 25% of scoring weight effectively dead live | 25% of weight now carries real alpha |

See [`smc-scoring-impact.md`](smc-scoring-impact.md) for the quantified lift and
[`smc-verification.md`](smc-verification.md) for how to *measure* it on real data.

---

## 9. Summary

MTF MA answers **"which side of the market?"** (trend 30%). SMC answers **"where, and is
it real?"** (structure 15% + liquidity 10%). `decide_ctx` answers **"does the market's
rudder agree?"** (BTC leader + MTF stack). Together, top-down trend → micro SMC execution
→ relational confirmation produces a *sparse, high-confluence* entry stream — the exact
shape the ≥85% WR target requires.

> **Next files:** implement the detector ([`smc-detector.md`](smc-detector.md)), prove the
> score lift ([`smc-scoring-impact.md`](smc-scoring-impact.md)), wire it
> ([`smc-wiring.md`](smc-wiring.md)), verify it ([`smc-verification.md`](smc-verification.md)).
