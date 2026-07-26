# Project Vaiśravaṇa — A Stability-First, High-Win-Rate Crypto Futures Trading System
### Technical Paper (v1.0)

> **Project name:** Vaiśravaṇa (वैश्रवण) — Buddhist deity of wealth & guardian of the
> northern quarter. Chosen as the namesake of a system whose prime directive is the
> *preservation* of capital through stable, high-probability micro-timeframe execution.
> Previously codenamed "Goblin".

---

## Abstract

Project Vaiśravaṇa is a self-contained, two-agent architecture for automated cryptocurrency
futures trading on Binance USDⓈ-M. Its design objective is **threefold and non-negotiable**:
(1) **time-sensitive accuracy** — a decision-to-fill latency under two seconds; (2)
**stability** — maximum drawdown below 3% at all times; and (3) a **per-pair / per-timeframe
win rate of at least 85%** before any capital is committed to live trading. The system
deliberately **eliminates external signal sources**: it generates its own trading decisions
internally from a layered market-analysis engine and enters positions immediately. Every
trade, decision, and meta-loop revision is persisted to structured tables, enabling full
auditability and an autonomous, bounded self-improvement loop.

---

## 1. Motivation

Retail and semi-professional trading bots typically fail not because their indicators are
weak, but because of factors invisible to candlestick theory: execution reliability, data
integrity, infrastructure latency, exchange-specific contract quirks, research validity, and
the meta-loop itself. Vaiśravaṇa addresses these by treating **stability and auditability as
first-class design constraints**, not afterthoughts.

The project is further distinguished by two explicit philosophical choices:

- **No signaling.** The bot does not wait for, parse, or depend on any external telegram,
  webhook, or API signal. It watches the market itself and decides. This removes an entire
  class of failure (signal source downtime, parse errors, delayed/duplicate messages).
- **Evidence-over-rules.** Decisions are scored by a weighted ensemble, then validated by a
  dynamic reasoning layer (5W1H) that can form *novel* hypotheses outside the predefined
  factor dictionary — preventing both reward-hacking and brittle rule-locking.

---

## 2. System Architecture

Vaiśravaṇa is organised as **one active trader + one correction agent (Sentinel)**, with a
shared telemetry store. The architecture file is the single source of truth; every other
document is a detail of one box.

```
                 Binance USDⓈ-M (5m/10m/15m, all USDT perps)
                          │  market data + order execution
                          ▼
        ┌─────────────────────────────────────────┐
        │       VAIŚRAVAṆA-TRADER (active)          │  ← decides internally, enters immediately
        │  9 engines → scoring → risk → execution    │
        │  MODE DEFAULT: PAPER / UNREAL               │
        └───────┬──────────────────┬─────────────────┘
                │ decision          │ telemetry (every event)
                ▼                   ▼
        ┌──────────────┐   ┌──────────────────────────────┐
        │  Exchange     │   │  Telemetry Store (DB)          │
        │  Adapter      │   │  decisions_log / trade_logs /  │
        │  (LIMIT,      │   │  results_log / exec_events /   │
        │   validate-   │   │  system_health                 │
        │   repair)     │   └──────────────┬───────────────┘
        └──────────────┘                  │ read
                                          ▼
        ┌──────────────────────────────────────────────┐
        │  VAIŚRAVAṆA-SENTINEL (correction)             │
        │  reason (5W1H) → evaluate → review → correct   │
        │  → shadow-test → promote → document            │
        └──────────────────────────────────────────────┘
```

### 2.1 The Nine Engines + Reasoning Layer

| Engine | Role |
|--------|------|
| 1. Regime Detector | trending / ranging / breakout / high-volatility |
| 2. Market Structure | HH/HL, BOS, CHoCH |
| 3. Liquidity | equal highs/lows, sweeps, FVG |
| 4. Candle & Price Action | patterns + momentum quality |
| 5. Volume | volume, delta, anomalies |
| 6. Volatility (ATR) | stop/target sizing |
| 7. Multi-Timeframe | HTF bias ↔ LTF trigger agreement |
| 8. Risk Manager | sizing, exposure cap, kill-switch |
| 9. Scoring | weighted aggregate → entry/watch/skip |
| 10. **Reasoning (5W1H)** | dynamic hypothesis, incl. novel H3 |

### 2.2 Multi-Timeframe Shadow Engine

The universe is **all Binance USDT perpetuals**, liquidity-filtered. For every pair `P` and
every trade timeframe `TF ∈ {5m, 10m, 15m}`, an isolated `ShadowTrader(P, TF)` runs
independently. Each accumulates its own win-rate counter and is promoted to live trading
**only** after sustaining WR ≥ 85% over ≥200 unreal trades with expectancy > +0.2R and
drawdown < 3%. Bad pairs/timeframes cannot contaminate good ones (isolation principle).

---

## 3. Decision & Execution Flow (no signals)

```
[every candle close per pair×TF (shadow)]
  → engines → score → decisions_log (records decision + confidence_pct)
  → if ENTRY & Gate A (pre-scoring) & Gate B (hard clamp) pass:
        LIMIT order (PAPER) → exec_events → trade_logs (open)
[on exit: TP / SL / trailing / max-hold]
  → trade_logs update (pnl, r, win/loss bool, win_pct/loss_pct)
  → AUTO-EVALUATE per pair×TF (rolling 200)
[window: 200 trades / daily]
  → eval_report → Sentinel REASON (5W1H) → review → correct (shadow) → promote
[gate passed + human approve] → LIVE for that pair×TF (shadow stays as baseline)
```

The **two-layer safety gate** is central:
- **Gate A (pre-scoring):** cheap rejects — idempotency, per-pair cooldown, liquidity
  filter, spread guard. No engine cost.
- **Gate B (post-scoring, pre-execution):** hard clamps the score engine *cannot* override —
  size clamp to risk budget, leverage ≤ 2×, daily-loss limit, correct SL direction,
  `reduceOnly` on all closes.

---

## 4. Logging & Auditability (the backbone)

Three mandatory tables (full SQL schema in `30-concrete-spec.md §4`):

1. **`trade_logs`** — one row per trade that entered a position. Lifecycle timestamps
   (`ts_filled`, `ts_tp_hit`, `ts_partial_close`, `ts_fully_closed`), **`win`/`loss`**
   booleans, and cumulative **`win_pct`/`loss_pct`** per pair×TF. *Every* trade — win or
   lose — is recorded. This is the basis for auto-evaluation and promotion.
2. **`decisions_log`** — the internal decision (replacing any notion of an external signal),
   including **`confidence_pct`** (0–100%). The trade is already "in" when this is written.
3. **`results_log`** — the historical meta-loop trail: evaluation, reasoning (5W1H),
   thinking, correction, improvement, and review, each as typed columns plus a structured
   `content_json`.

A `correlation_id` flows through every table, so a single trade's full life
(decision → order → fill → TP → close) is reconstructable for Sentinel review and
postmortems.

---

## 5. Autonomous Self-Improvement (Sentinel)

The Sentinel never rewrites engine logic. It edits only a **bounded parameter surface**
(weights, thresholds, SL/TP multipliers, leverage, cooldown, filter on/off), always via:

1. **REASON** — build a 5W1H scenario; form hypothesis H1/H2, or novel H3.
2. **EVALUATE** — per-pair×TF WR, expectancy, attribution, composite health.
3. **REVIEW** — decide whether a correction is warranted.
4. **CORRECT** — propose a parameter diff (bounded, rate-limited, Σ weights = 1).
5. **SHADOW-TEST** — apply to a shadow trader; compare vs baseline.
6. **PROMOTE** — only if shadow ≥ baseline AND composite health improves.
7. **DOCUMENT** — append to `chronicle.md` and `results_log`.

Guardrails forbid the Sentinel from disabling safety filters or from reward-hacking
(optimising a metric at the expense of genuine stability). A human-in-the-loop approval gate
exists for large changes and for the initial paper→live promotion of each pair×TF.

---

## 6. Risk Posture (stability-first)

| Guard | Value |
|-------|-------|
| Max leverage | 2× (hard cap) |
| Daily loss limit | 0.5% (unreal & live) → kill-switch |
| Risk per trade | 0.25% of equity |
| Global live pairs cap | 5 (correlation/exposure control) |
| Max hold | = trade timeframe (5/10/15m) |
| Kill switches | ADL rank, funding spike, maintenance, frozen feed, black-swan |

---

## 7. Enrichment from Production Experience

Patterns from a separate production Binance futures listener
(`learnernoearner-listener`) were adopted as execution-reliability hardening: 1000× meme-coin
contract handling, deterministic order validation→repair→resubmit-once, dual-mechanism SL
(exchange conditional + mark-price polling), self-healing protection, orphan detection,
correlation-ID tracing, and proactive health reporting. Crucially, only the *execution and
safety plumbing* was borrowed — **not** the listener's external-signal model, since Vaiśravaṇa
has no signals by design.

---

## 8. Discussion & Limitations

- **The 85% target is a gate, not a guarantee.** The system *measures and gates* on it;
  pair/timeframe combinations that cannot sustain 85% in unreal are pruned. Capital is never
  forced into sub-85% setups.
- **"All pairs" is liquidity-filtered**, not literally every ticker — thin/high-spread
  contracts are auto-excluded to protect stability while honouring the broad universe.
- **Backtesting, fee-tier calibration, and the concrete DB/language choice** remain open
  implementation decisions (tracked in `31-glossary.md`).

---

## 9. Conclusion

Project Vaiśravaṇa reframes the trading-bot problem around **stability, internal
decision-making, and total auditability** rather than indicator cleverness. By combining a
layered analysis engine, a high-threshold scoring gate, an isolated multi-timeframe shadow
farm, and a bounded autonomous correction agent with rich structured logging, it aims for
consistently high win rates without sacrificing capital safety — wealth *preserved*, in the
spirit of its namesake.

---

### References (this repository)
- `ARCHITECTURE.md` — master design
- `docs/01`–`11` — eight analysis layers + scoring + engine design
- `docs/20`–`27` — two-bot system, telemetry, evaluation, Sentinel, safety, documentation
- `docs/28` — blind-spot research (execution/exchange/infra/meta-loop)
- `docs/29` — dynamic 5W1H reasoning
- `docs/30` — concrete spec (SQL schemas, parameters)
- `docs/31` — glossary
- `docs/32` — listener-lesson enrichment
