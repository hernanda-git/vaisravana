# SMC Knowledge Base — Index

> **Project:** Vaiśravaṇa (stability-first, high-WR ≥85%, bidirectional futures bot)
> **Scope:** Smart Money Concepts (SMC) as an **opt-in plug-in engine** that feeds the
> existing 9-engine scoring stack to raise win rate, accuracy, and decision speed.
> **Status:** Documentation / implementation blueprint. Purely additive — no running
> session, surface, or engine is modified by these docs.

This folder is the single source of truth for *how SMC plugs into Vaiśravaṇa*. It is
structured so a developer can implement the detector behind tests, a quant can verify
the win-rate lift against the real backtest harness, and an operator can read the
quick-reference without wading through the spec.

## Reading order

| # | File | Audience | What it answers |
|---|------|----------|-----------------|
| 0 | `smc-index.md` | everyone | This map. |
| 1 | [`smc.md`](smc.md) | everyone | The SMC doctrine, re-anchored to Vaiśravaṇa's actual engines & dual-score. |
| 2 | [`smc-detector.md`](smc-detector.md) | dev | `src/smc.py` interface, data model, algorithms, performance design. |
| 3 | [`smc-scoring-impact.md`](smc-scoring-impact.md) | quant | Exact math: detected structure → 7 factors → confluence → win-rate lever. |
| 4 | [`smc-wiring.md`](smc-wiring.md) | dev/ops | Where it plugs in + Sentinel constraint + guardrails. |
| 5 | [`smc-verification.md`](smc-verification.md) | quant/QA | E2E plan: pytest + real-data backtest + acceptance gates. |
| 6 | [`smc-quickref.md`](smc-quickref.md) | ops | Cheat sheet + the knobs the Sentinel *can* tune. |
| 7 | [`smc-execution-plan.md`](smc-execution-plan.md) | dev/lead | Phase-by-phase build + rollout, shadow-first, reversible. |

## Alignment facts (verified against the code, not assumed)

- `MarketState` (`src/engines.py`) already exposes SMC slots:
  `hh, hl, lh, ll, bos, choch, liq_sweep, eq_high, eq_low, fvg`.
- `structure_score` (15% weight) and `liquidity_score` / `liquidity_score_bear` (10%)
  already **reward those slots** (`src/engines.py`: `_FACTORS` registry, doc 10).
- The live factory `build_state_mtf` (`scripts/bot_paper.py`) only feeds a *rough*
  heuristic: `fvg=bos`, sweep detected from prior-20-bar extremes. **doc 40 §1.4** calls
  structure (15%) + liquidity (10%) "starved" in production because of this.
- The dual-score path is first-class bidirectional (`src/scoring.py:decide`,
  `score_side`): a SHORT is NOT a mirrored long — the plug-in must populate SMC slots
  **symmetrically** for both sides.
- Cross-asset + MTF relational context is a separate modulator (`src/marketcontext.py`,
  `decide_ctx`) — SMC is the *single-name* microstructure layer that stacks under it.
- The **Sentinel cannot edit engine code** (`src/sentinel.py`): it only emits a new
  `ParameterSurface`. Therefore the detector is a **new pure module** that *feeds* the
  existing engines — not a rewrite of them. Any enrichment of `structure_score`/
  `liquidity_score` itself is a human-gated change behind tests (see `smc-scoring-impact.md`).

## Design invariants (must hold for every file here)

1. **Pure & side-effect free** — `src/smc.py` does no I/O, no network, no DB. Input is
   `list[Candle]`; output is a dataclass. This matches the engine contract
   (`src/engines.py` header: "Each engine is a PURE function").
2. **Additive, non-breaking** — detectors set slots on a `MarketState` that already has
   safe defaults; existing tests keep passing.
3. **Symmetric** — every detector produces LONG-usable and SHORT-usable facts.
4. **Performance-first** — O(n) single pass, incremental pivot cache, optional numpy.
   The bot evaluates many `(pair × tf × side)` per minute; detection must not dominate
   the <200 ms decision budget (doc 30 §1).
5. **Honest flags** — every boolean traces to OHLCV arithmetic; no invented liquidity.
   This satisfies the audit-trail / fail-loud culture (doc 30 §4, doc 40 §5).
