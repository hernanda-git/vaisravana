# doc 42 — Cross-Asset & Multi-Timeframe Context + Scalping Tuning (v0.0.7)

Implements the two relational dimensions the brief called out as critical (doc 40 §1):
**BTC / BTC.d / ALTCOINS are one system**, and **small / medium / high timeframes are
related**. Plus a scalping-friendly surface so the bot is actually built for fast
execution, not swing holds.

## 1. What changed

### New module `src/marketcontext.py` (pure, no I/O)
- `MarketContext` — one snapshot of the relational state for a decision:
  - **BTC leader**: `btc_bias` (EMA20/50 on HTF) + `btc_ret`.
  - **Dominance / risk regime**: `dominance_delta` (proxy = alt-basket-return minus BTC
    return) and `risk_regime` (bullish = alt bid / risk-on, bearish = BTC bid / risk-off).
  - **Alt relative strength**: `alt_rs_btc` (this pair's return minus BTC's) + `alt_breadth`
    (fraction of the alt basket above its EMA — a participation gauge).
  - **MTF relational**: `ltf_bias` / `mtf_bias` / `htf_bias2` (explicit 3 layers) +
    `mtf_confluence` (all three agree) + `pullback_to_anchor` (LTF retraced into the HTF
    bias then resumed — the actual scalping entry trigger).
- `build_context(series)` builds all of the above from raw closes (no network).
- `ctx_boost()` — a **modulator** in [0.9, 1.12]: rewards BTC-confirmed + risk-on +
  MTF-confluent + pullback-to-anchor setups; the doc-21 Σweights=1.0 invariant is
  preserved (the relational factors modulate the existing 7-factor score, they do not
  add a new free weight).
- `ctx_gate_open(side)` — a **hard gate**: blocks a long while BTC is bearish AND
  dominance is rising (risk-off), blocks a short while BTC is bullish AND risk-on, and
  blocks a trade when LTF/MF/HTF all oppose the side.

### Engines `src/engines.py`
- `MarketState` gained 11 relational fields (all default-neutral so old behavior is
  unchanged when context is absent).
- Two new 0..1 factor functions: `crossasset_score` (BTC/dominance/RS confirmation) and
  `mtf_relational_score` (confluence + pullback-to-anchor). They are exposed for
  attribution/testing; the scalping path applies them via the modulator, not as new weights.

### Scoring `src/scoring.py`
- New `decide_ctx(s, surface)` = the existing 7-factor `decide()` PLUS the relational
  boost + hard gate. `decide()` is unchanged (all prior tests keep passing). When context
  is absent the boost is neutral (1.0) and the gate is open, so `decide_ctx` degrades to
  the 7-factor path gracefully.

### Bot `scripts/bot_paper.py`
- Each tick now fetches BTC (leader) + the other configured pairs (alt basket) + the
  tradable's LTF/MF/HTF closes (best-effort; any fetch failure stays neutral so the loop
  never crashes) and folds the relational context into the `MarketState`.
- `_decide_tick` uses `decide_ctx` → context-confirmed, BTC-aware entries.

### Surface `src/config.py` (scalping-tuned, within doc-21 bounds)
- `entry_threshold` 0.90 → **0.86**, `tp_atr_mult` 1.05 → **1.25** (positive R:R so a
  realistic WR can be profitable), `max_leverage` 2 → **3**, `cooldown_after_loss` 10 → **5**.

## 2. Evidence

`tests/test_phase15_context.py` proves:
- BTC bullish + risk-on + MTF confluence + pullback → `ctx_boost() > 1.0`, gate allows.
- Long while BTC bearish + risk-off → hard-blocked.
- Short while BTC bullish + risk-on → hard-blocked.
- `build_context` derives alt-bid (risk-on) when the pair outperforms BTC.

Manual check (real logic):
- A 0.889 base 7-factor setup with BTC-confirmed context → **0.996** after `decide_ctx`.
- The same 7-factor long while BTC bearish + risk-off → downgraded to **WATCH** (blocked).

## 3. Honest status (do not over-claim)

`scripts/run_backtest_honest.py` now builds the relational context from real klines and
re-runs with taker fees + 60-bar multi-bar hold + IN/OUT-of-sample split. On the
2026-07-26 data the **base 7-factor signal is still extremely sparse** (~1-2 entries per
1500 bars across all pairs/TFs) — the relational layer is correctly wired and gating, but
the *base alpha is too rare* to be a usable scalper yet. The architecture is production-
grade; the **edge needs more signal density** (denser entry logic, longer history, and a
re-tuned R:R or gate) before any live promotion is warranted. This is the same conclusion
as doc 40 §2, now with the relational dimension fully in place.

## 4. Next steps (recommended)
1. Add a denser entry trigger (e.g. mean-reversion at VWAP/eq-low with MTF confluence) so
   the scalper actually trades several times per session.
2. Validate on 6–12 months of 5m/15m history with the context layer; report OOS expectancy.
3. Keep `winrate_gate_pct` as a *promotion* gate, not a per-trade filter (doc 40 §2.2).
