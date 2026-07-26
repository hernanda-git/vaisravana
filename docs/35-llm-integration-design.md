# LLM / AI Integration Design — Project Vaiśravaṇa (Phase 11 proposal)

**Status:** design only — nothing implemented yet. The running bot is 100% deterministic
(no LLM). This document answers: *where can an LLM/AI model be placed to raise accuracy,
win-rate, and self-eval/correction/promotion — while keeping trades fast and
hallucination structurally impossible?*

It is written to be honest about limits, not to sell a model.

---

## 1. Verdict (read this first)

An LLM **should not** be the trade decider. Vaiśravana was deliberately built so the
*deterministic engines* (`src/engines.py`) decide internally — that is its core safety
property (doc 30 §1: "no signals — decides internally, enters immediately"). The
`learnernoearner-listener` uses an LLM (`deepseek-v4-flash`) to parse Telegram signals
and decide; that is exactly the failure class Vaiśravaṇa avoids (non-reproducible,
hallucinable, latency-bound, token-costly).

The LLM's correct role here is a **propose-only researcher that runs OFFLINE** and feeds
the *existing* bounded-Sentinel promotion loop. It makes the bot **smarter and faster to
improve**, not faster to execute a single trade. Concretely:

- **LLM = hypothesis generator for Sentinel** (what to tweak + why). Sentinel still
  tests it in shadow and promotes only if shadow ≥ baseline + composite health ↑.
- **LLM = regime/narrative context** for the engines (optional, enum-constrained). Lets
  the deterministic factors "see" news/chop regimes pure OHLCV cannot.
- **LLM = never in the hot path** (`PaperOrchestrator.on_candle_close`). Zero latency,
  zero cost, zero hallucination exposure on the live decision.

This keeps every existing guardrail intact: `apply_proposal` (±10%, ≤4 changes, doc-21
bounds, Σweights=1), `ShadowComparison.promotable`, and `safety.promotion_gate(
human_approved=True)`.

---

## 2. Where the LLM fits — mapped to real modules

### Insertion A — `src/llm_research.py` : `LLMResearcher` (the clean seam)

`Sentinel.cycle(prop, comparison_factory, ...)` **already accepts a `Proposal`**. So the
LLM's only job is to *produce a `Proposal`* — the exact dataclass Sentinel consumes:

```python
# src/sentinel.py (exists)
@dataclass
class Proposal:
    changes: dict[str, float]      # {param_path: new_value}  e.g. {"weights.momentum": 0.16}
    rationale: str = ""
    hypothesis: str = ""           # H1/H2/H3 text (doc 29)
```

`LLMResearcher.propose(...)` returns a `Proposal`. It does **not** touch trading, gates,
or the live loop. The flow:

```
eval_reports (evaluate() per pair×tf×side)  ─┐
fp_fn cases (ENTRY→SL trades + their MarketState) ─┤→  LLMResearcher.propose()
current ParameterSurface (config.default_surface) ─┘         │
                                                              ▼
                                                   raw LLM JSON  (constrained schema)
                                                              │  parse → Proposal
                                                              ▼
                                                   Sentinel.cycle(prop, shadow_factory)
                                                              │
                                              apply_proposal() guardrails (EXISTING)
                                                              │
                                   promotable? ── yes → new surface v{N+1}, results_log
                                              └─ no  → ROLLBACK, results_log, discarded
```

Because the LLM output is funneled through `apply_proposal` (the *existing* validator),
a hallucinated proposal is **refused, not trusted**: 5 changes → `SentinelViolation`;
weight delta >10% → refused; out-of-doc-21-bounds → pydantic `ValidationError` → refused;
any non-surface path (engine logic, schema) → refused. The LLM literally cannot alter
anything outside the ParameterSurface.

### Insertion B — `src/context.py` : `NarrativeContext` (optional, enum-constrained)

A periodic (15–60 min) LLM call summarizes macro/news/liquidation narrative for the
traded pairs into a **low-cardinality enum**, not free text:

```python
from typing import Literal
class NarrativeTags:
    regime: Literal["risk_on","risk_off","euphoria","capitulation","chop",
                    "news_driven","neutral"] = "neutral"
    liquidity_stress: Literal["low","normal","high"] = "normal"
```

These become optional `MarketState` fields (default `neutral`/`normal`) so the bot works
identically with the LLM disabled. A new engine `narrative_score(s)` consumes them.
**Hallucination guard:** the LLM is forced to emit only the enum (function-calling /
JSON schema with constrained values); an unknown tag maps to `neutral`. Worst case the
narrative is wrong → it's *neutral*, never poison.

### What the LLM reads (all already in the DB)

- `evaluation.evaluate(conn, pair, tf, side) -> EvalReport` — `win_rate_pct`,
  `expectancy_r`, `profit_factor`, `max_dd_pct`, `sharpe`, `passes`, `health()`.
- FP/FN attribution (doc 23) — ENTRY trades that hit SL, with their `MarketState`
  snapshot (stored in `trade_logs.scores_json` / a new `decisions_log` context column).
- `config.ParameterSurface` current weights + scalars.

---

## 3. Where the LLM must NOT go

| Location | Why excluded |
|---|---|
| `PaperOrchestrator.on_candle_close` | Hot path. Goal G1 = decision→fill <2s. LLM adds 200–2000ms + cost + non-determinism → breaks latency & reproducibility. |
| Replacing `TwoLayerGate` / `DecisionOrchestrator` | Safety must stay deterministic & auditable (doc 25/30 §3). |
| Making the ENTRY/EXIT decision | That is the listener's pattern; Vaiśravaṇa exists to avoid it. |
| `bot_paper._cycle` synchronously | Would stall the 30s loop on every network call. |

The live loop stays **air-gapped** from the LLM. The LLM runs in a separate research
process; only its *validated, shadow-passed* surface reaches trading (via `/data/surface.json`).

---

## 4. The "trade faster" paradox — honest answer

An LLM **cannot make a single trade faster** — it adds network latency and cost. What it
CAN do:

- **Higher win-rate via fewer bad entries** — narrative context helps the engines skip
  trades in chop/news regimes they currently misread → quality, not speed.
- **Faster to become a better bot** — the Sentinel improvement loop converges sooner
  because the LLM supplies *good hypotheses* instead of empty H1/H2/H3
  (`src/reasoning.py` currently leaves `hypotheses=[]`).

So: "faster" = shorter time-to-a-better-ParameterSurface, not lower per-trade latency.
If you want lower per-trade latency, the answer is *local pre-computed indicators*
(already instant) — not an LLM. Stating this plainly so the goal isn't mismatched.

---

## 5. Hallucination prevention — 7 mechanisms, all mapped

1. **Structured/constrained output.** LLM emits strict JSON / enum only. No free text
   enters the decision. `narrative_score` reads an enum, not prose.
2. **Funnel through `apply_proposal` (existing).** Every LLM diff is re-validated by the
   deterministic guardrail (±10%, ≤4, doc-21 bounds, Σweights=1). Output is *checked*, not
   trusted.
3. **Shadow-gated promotion.** A proposal reaches "promoted" only if
   `ShadowComparison.promotable` on **real replayed data** — `shadow.expectancy_r >=
   baseline` AND `shadow.max_dd_pct <= baseline` AND `health() ↑`. A hallucinated
   "great" proposal fails the replay.
4. **Human gate for live.** `safety.promotion_gate(human_approved=True)` — the LLM never
   flips a (pair,tf,side) to live. It can only earn a *shadow* promotion.
5. **Confidence threshold.** Require the LLM to return `confidence ∈ [0,1]`; <0.5 →
   discard the proposal (no-op).
6. **Full audit log.** Every prompt + raw response + parsed `Proposal` is written to
   `results_log` (`approved_by='llm_research'` or `'sentinel'`). Hallucinations are
   *visible post-hoc*, not silent.
7. **Offline-only execution.** The LLM runs in a research process; a hung/garbage LLM
   cannot freeze or poison the live loop. On provider outage the bot degrades to
   LLM=off (pure deterministic) with zero behavior change to trading.

Net: **a hallucination can at worst waste one shadow replay. It can never reach a live
order or alter engine logic.**

---

## 6. Accuracy / win-rate impact — honest expectation

| Lever | Effect | Realistic magnitude |
|---|---|---|
| Narrative context (Insertion B) | Fewer FPs in news/chop regimes the 8 factors misread | +1 to +4 pp WR on pairs where narrative matters; ~0 on clean trend pairs |
| LLM hypotheses for Sentinel (Insertion A) | Better, faster parameter convergence | shorter time-to-promotion; marginal WR lift once converged |
| Explainability | Human can audit *why* a change was made | qualitative, not a WR number |

**Ceiling (must be said):** win-rate is fundamentally capped by market structure + fees
(VIP0 maker 0.02% / taker 0.05%). No model defeats fees on noise. The LLM helps at the
**margin and on regime edges** — it is not a win-rate silver bullet. The 0.90 entry
threshold + Gate A/B already filter hard; the LLM cannot make a bad market tradeable.
Overfitting risk (LLM chasing recent noise) is contained by the rolling-200 window +
shadow test + human live gate.

---

## 7. Self-eval / self-correction / self-promotion — the 3-layer model

| Layer | Exists? | LLM's role |
|---|---|---|
| **Self-eval** | `evaluation.py` (per pair×tf×side, FP/FN) | ADDS natural-language *diagnosis* of why FPs happen (reads losing-trade `MarketState`) → feeds hypothesis. Numbers stay deterministic. |
| **Self-correction** | `Sentinel` bounded diff (doc 24) | SUPPLIES the *hypothesis* (what to change + why) instead of empty H1/H2/H3. Sentinel still tests + rolls back. **LLM = propose, Sentinel = judge.** |
| **Self-promotion** | `Sentinel.cycle` promotes on shadow pass | LLM = candidate generator. **Live flip stays human-gated** (`safety.promotion_gate`). |

This is exactly the "bounded, auditable, human-over-final" model the spec demands.
The LLM raises the *quality and speed* of layers 1–2; layer 3 (live) remains human.

---

## 8. Proposed module design (concrete)

```python
# src/llm_research.py
from typing import Protocol
from sentinel import Proposal, Sentinel
from evaluation import EvalReport
from context import NarrativeTags

class ProposalSource(Protocol):
    def propose(self, surface, evals: list[EvalReport], fp_fn: list) -> Proposal: ...

class LLMResearcher:
    def __init__(self, client, enabled: bool = False): ...
    def propose(self, surface, evals, fp_fn) -> Proposal:
        """Build a constrained prompt from eval reports + FP/FN cases, call the LLM,
        parse strict JSON -> Proposal. On malformed/low-confidence output, return an
        EMPTY Proposal (no-op). NEVER raises into the caller."""
    def context_tags(self, pair: str) -> NarrativeTags:
        """Enum-constrained narrative summary. Unknown -> neutral."""

# src/context.py
@dataclass
class NarrativeTags:
    regime: Literal["risk_on","risk_off","euphoria","capitulation","chop",
                    "news_driven","neutral"] = "neutral"
    liquidity_stress: Literal["low","normal","high"] = "normal"
```

### Wiring into `bot_paper.py` (off by default)
- `run()` spawns `research_loop()` (every 30–60 min, or per ~50 closed trades).
- `research_loop` → `LLMResearcher.propose(...)` → `Sentinel.cycle(prop, shadow_factory)`.
- On promotion: persist new surface to `/data/surface.json`, Telegram `🚀 SENTINEL
  PROMOTED v{N}`.
- The live `_cycle` reads the current `/data/surface.json` (fallback `default_surface()`).
  **The LLM is never in the candle loop.**

### Opt-in env (respects paper-safe cross-cutting rule)
```
VAISRAVANA_LLM = off          # default — identical to today, zero LLM/cost/risk
                 | research     # LLM proposes Sentinel diffs (offline)
                 | research+context  # + narrative context for engines
```

---

## 9. Rollout & verification (no hallucination reaches live)

- **Phase 11a** — `src/llm_research.py` + `src/context.py` + tests with a **mock LLM
  client**: assert (1) >4 changes refused, (2) weight delta >10% refused, (3) malformed
  JSON → empty `Proposal` (no-op, no raise), (4) unknown narrative tag → neutral, (5)
  confidence <0.5 → discarded. **No live calls in tests** (cross-cutting rule).
- **Phase 11b** — wire `research_loop` into `bot_paper` (default `off`).
- **Verify:** deploy with `LLM=off` → behavior identical to current (regression). Deploy
  with `LLM=research` → only `PROMOTED`/`ROLLBACK` appear in Telegram, each backed by a
  `results_log` row showing the shadow vs baseline numbers. A human reviews before any
  live flip.
- **Cost:** research ~every 30–60 min (<50 calls/day, cheap model); context ~every 15 min
  × pairs. Negligible. Latency irrelevant (offline).

---

## 10. Risks & honest caveats

- **Overfit to narrative** — mitigated by rolling-200 + shadow + human live gate; human
  should still review promotions.
- **Provider outage / drift** — bot degrades gracefully to `LLM=off` (deterministic).
- **Cost if misconfigured** — cap call frequency (env-bounded loop).
- **"Highest win-rate" is not guaranteed** — the architecture maximizes *safe* improvement,
  not a specific number. Market + fees set the ceiling.
- **Regulatory** — not applicable to paper; live remains human-gated regardless.

---

## 11. Summary for the user

- Can an LLM be added? **Yes — as an offline, propose-only researcher + optional
  narrative context.** Not as the decider.
- Where? `src/llm_research.py` (feeds `Sentinel` via the existing `Proposal`) and
  `src/context.py` (enum-constrained `NarrativeTags` consumed by a new `narrative_score`
  engine). Both opt-in via `VAISRAVANA_LLM`.
- Faster trades? **No** (latency); **faster improvement + fewer bad entries? Yes.**
- Hallucination? **Structurally prevented** — funneled through `apply_proposal` +
  shadow gate + human live gate; worst case wastes one shadow replay.
- Win-rate? **Margin + regime edges only**; fees/market cap the ceiling.
