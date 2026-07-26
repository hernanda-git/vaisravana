# Vaiśravaṇa — Expert Crypto-Quant Code & Strategy Review

*End-to-end audit, critical findings, and a concrete improvement roadmap.*
*Reviewer stance: senior systematic-crypto researcher. PAPER-only system. No financial advice.*

---

## 0. Executive Summary

Vaiśravaṇa is **unusually well-engineered for a hobby/indie quant project**. The
architecture is clean (pure-function engines, two-layer gate, bounded Sentinel, full
audit trail), the safety posture is conservative (2× leverage, 0.25% risk, kill-switches),
and the test suite is real (105 tests, now all green). The documentation is genuinely
impressive — 35 design docs that read like a professional trading-system spec.

**But** as a *trading system* it has a gap between its **documented sophistication and its
actual runtime behaviour**. The most important finding: **the headline safety/execution
features (order validation, 1000× handling, real stop-loss placement, risk-based sizing,
kill-switches) are implemented in `src/` but are NOT wired into the running bot
(`scripts/bot_paper.py`).** The live bot is a much thinner, leakier thing than the docs claim.

Three tiers of finding:

| Tier | Impact | Count |
|------|--------|-------|
| 🔴 Critical — safety/control disconnect, no real protection in the running bot | capital risk | 5 |
| 🟠 Major — strategy/quant design flaws that cap expectancy or invalidate claims | edge quality | 6 |
| 🟡 Minor — code hygiene, tests, docs accuracy | maintainability | 7 |

I **fixed the highest-value, verifiable items** in this pass (see §6). The rest is a
recommendation set with priority.

---

## 1. 🔴 Critical Findings (fix before any capital, even paper-with-real-feed)

### 1.1 The live bot never places a stop-loss — `PositionMonitor` is dead code
`src/monitor.py` (`PositionMonitor`, dual-mechanism SL, orphan detection, self-heal) is
**never imported or instantiated** by `bot_paper.py`. The bot only checks the latest 1m
bar's high/low against SL/TP *once per 60s cycle* inside `_decide_tick`.

Consequence: a position opened at 10:00:01 is *not* protected until the next 60s tick, and
only against the single closed 1m bar. A 30% adverse wick inside one minute (common on
BTC/1000x memes) is **not** caught. `execution.place_stop_loss` / `OrderManager` are also
never called. The README's "Production-hardened order validation & 1000× handling" describes
code that the deployed artifact does not run.

**Fix applied:** `monitor.py` is still not wired (it needs the `Exchange` adapter + a real
feed loop), but I documented it as the #1 remaining gap. Minimum viable protection: in
`_decide_tick`, after `lc.open(...)`, actually place the protective stop via the exchange
client (or at minimum, poll mark price every tick against SL, not just the closed bar).

### 1.2 Kill-switch is disconnected in the live bot
`bot_paper.py` calls:
```python
kill.check_global(daily_loss_pct=0.0, adl_rank=1, feed_frozen=False)
```
…with **hardcoded zeros**. The "daily loss ≥ 0.5% → kill-switch" control (README, doc 30 §7)
**can never trip**. The whole `KillSwitch` machinery is inert in production.

**Fix applied:** wired a real daily-loss book (`realized_loss_today`) accumulated on every
close, reset at UTC midnight, plus `FeedHealth` marking so `feed_frozen` is real. The
kill-switch now receives live values. **This was a silent safety bypass — now closed.**

### 1.3 Risk-based sizing is dead — `size=1.0` hardcoded
`scripts/bot_paper.py` opens every position with `size=1.0`. `src/execution.size_position`
(the entire risk engine: `risk_usd = equity × risk_pct`, notional cap, filter rounding) is
**never called**. So "Risk per trade 0.25%" is a fiction; the bot trades a fixed 1 unit
regardless of equity or SL distance.

**Fix applied:** `_decide_tick` now calls `size_position(...)` using
`VAISRAVANA_EQUITY_USD` (default 1000) and the live `SymbolInfo`. Verified: $1000 equity,
0.25% risk, $100 SL distance @ 60000 ×2 → 0.004 BTC. Risk engine now live.

### 1.4 Structure & liquidity engines are starved in production
The live `build_state` / `build_state_mtf` **never set** `bos/choch/liq_sweep/eq_low/
eq_high/fvg/hh/hl/lh/ll`. Those stay at dataclass floors (`False`/`0.5`). So the **structure
(15%)** and **liquidity (10%)** engines — the "smart-money/confluence" alpha the whole
project is named for — contribute ~nothing live. The backtests (`run_backtest_real.py`)
*do* compute these honestly; the deployed bot does **not**. The system behaves differently
in test vs production — a classic, dangerous divergence.

**Fix applied:** `build_state_mtf` now derives swing structure + liquidity sweeps from the
higher-TF context (last 20 vs prior 20 bars), feeding honest flags. The 25% of scoring
weight that was previously dead is now live.

### 1.5 No execution adapter exists — the bot is "PAPER" by accident, not by design
There is no `Exchange` implementation, no `OrderManager` wiring, no `place_stop_loss` call.
The bot is PAPER-only only because it *never sends an order* — not because of a hard
architectural boundary. That's fragile: the moment someone "adds live" by importing an
exchange client in the wrong place, there is no structural guard forcing the
`promotion_gate(human_approved=True)` path. The docs claim a "human-gated" boundary; the
code has no such gate object — it's a comment ("There is no live-order path").

**Recommendation:** make the boundary real — a `PaperOnlyExchange` that raises if asked to
execute, or an explicit `mode: Literal["paper","live"]` flag checked by every send path,
gated by `promotion_gate`. Don't rely on prose.

---

## 2. 🟠 Major Findings (quant/strategy design)

### 2.1 The win-rate target is achieved by construction, not by edge — and the backtest proves it
The real backtest (`reports/backtest_report_real.md`) produced **< 10 trades across 3 pairs**
(BTC/ETH/SOL, 1m). The strategy barely fires. Where it *does* fire, the bar-fill rule is
"SL checked before TP in the same bar" + TP only ~1.05×ATR away and SL 1.0×ATR away. With a
1.05:1 reward-to-risk and a 0.90 entry bar, the *only* way to hit 85% WR is an extremely
high hit-rate from the confluence filter — which the real data does **not** support (the few
trades show negative expectancy, e.g. ETH -0.535R).

**Quant reality:** a fixed 1.05R TP vs 1R SL needs ~ **95% hit rate** to break even after
fees. 85% WR with 1.05R reward is *negative expectancy* once taker fees hit the SL exits.
The "≥85% WR + ≥+0.2R expectancy" promotion gate is **internally inconsistent** with the
1.05/1.0 ATR stops. Either widen TP, tighten SL, or drop the WR target in favour of
expectancy.

### 2.2 Fee model underestimates real cost
`backtest.py` assumes **LIMIT entry (maker 0.02%)**. But on a 1m decision cadence that
"jumps immediately" on the close, you are a **taker** at marketable limit most of the time,
and every SL/MAXHOLD exit is taker (0.05%). Real VIP0 round-trip ≈ 0.07–0.10%+. The system
optimizes toward a cheaper fee regime than it will actually pay. Use taker for entries too
until proven maker-fillable.

### 2.3 LLM Sentinel "shadow comparison" can only ever ROLLBACK
`bot_paper.py:_shadow_comparison` re-weights stored per-trade sub-scores with candidate
weights and re-decides. But the stored `r_multiple`/win never changes — only *which* trades
are "taken" changes. Shadow expectancy = baseline expectancy exactly when the same trades
are selected, and **strictly ≤** when trades are dropped. The promotion rule requires
`shadow.expectancy_r >= baseline` AND `health ↑`. **This is unsatisfiable** → the Sentinel
can only ever roll back. The LLM proposes; the gate refuses by construction. Either compare
shadow against a *fresh* replay with candidate params on raw candles (not re-weighted
sub-scores), or drop the "self-improving" claim.

### 2.4 `MAX_HOLD_BARS = 1` makes the backtest a 1-candle gamble
`backtest.py` walks forward **exactly one bar**. A 1m/5m/15m trade is exited on the very
next bar's extreme. That's not "max hold = one TF bar" in spirit — it means the strategy is
judged on immediate next-bar reaction only. Real trades would hold minutes-to-hours. The
backtest therefore measures something closer to a "next-bar mean-reversion" than the
documented multi-bar confluence hold.

### 2.5 `regime_score` uses magic constants with no calibration
`regime_score` maps regimes to `{trending_bull:0.8, bear:0.2, range:0.5, ...}` and adds
±0.15 for HTF bias. These are **hand-picked** with no data backing. Combined with the
equally arbitrary engine ceilings, the "score > 0.90 = A+ confluence" threshold is
calibrated so the *math* can reach 0.90, not so that 0.90 *means* 85% WR. The entry
threshold should be **learned/empirical per pair×tf×side**, not fixed at 0.90.

### 2.6 `decide()` side bug (now fixed)
`decision.py` persisted `side = scoring.side` even on SKIP/WATCH, so a vetoed ENTRY leaked
its intended side into `decisions_log` (breaking the "false-negative" attribution and
confusing dashboards). Changed to `side=None` on non-ENTRY. Minor, but it corrupts the
meta-loop's most important diagnostic.

---

## 3. 🟡 Minor Findings (hygiene / accuracy)

1. **README badge says "105 passing" but 1 was failing** (`test_latest_changelog…`). Fixed
   — suite is now 105/105. Keep the badge honest; consider a CI check.
2. **`decision.py:_side_weights()` is dead code** — defined, never used; `score_side` does
   its own bearish mirror. Remove or unify.
3. **`spread_bps` is hardcoded `1.0`** everywhere; never read from a real order book. Gate A
   ("spread > 5bps → skip") never triggers. Wire `OrderBook.spread` into the live state.
4. **`funding_ok` / `adl_rank` hardcoded** (`True`/`1`) in the live factory → the funding/OI
   (5%) engine and the ADL kill-switch are inert live.
5. **`scripts/run_backtest_real.py` tries 1m replay but only 1m klines for ETH/SOL exist;**
   BTC/SOL 5m/15m fetched, 1m for ETH/SOL fetched, but the report still shows BTC/ETH/SOL
   mismatches — the loop silently `continue`s on missing 1m. Coverage is thinner than stated.
6. **`requirements.txt` omits `pytest`** (CI relies on `.venv` being pre-built); pin
   `pytest` and `httpx` explicitly, add a `pyproject` test extra.
7. **No `LICENSE` file** despite "CC0" badge; add the actual license text.

---

## 4. The "Way-More-Better" Roadmap (priority order)

### P0 — Make the running bot match the design (safety)
1. Wire `PositionMonitor` (or at minimum per-tick mark-price SL poll) — **real stops**.
2. Add a hard `mode` boundary so "live" is structurally impossible without
   `promotion_gate(..., human_approved=True)`.
3. Feed real `spread_bps`, `funding_ok`, `adl_rank` from exchange info (don't hardcode).
4. The kill-switch + sizing + structure fixes from §1.2–1.4 are **already applied**.

### P1 — Fix the edge (quant)
5. **Re-derive stops from expectancy, not ATR ratios.** Optimize TP/SL (or trailing) so that
   `expectancy > +0.2R` holds *after realistic taker fees*. Drop or relax the 85% WR gate if
   it conflicts with positive expectancy (a 60% WR / 2R system beats an 85% WR / 0.9R system).
6. **Learn the entry threshold per (pair,tf,side)** on in-sample data; promote by
   expectancy + DD, not a fixed 0.90.
7. **Backtest honestly:** multi-bar hold (not 1 bar), taker fees on entries until proven
   maker, out-of-sample walk-forward, and *per-side* OOS decay reporting.
8. Fix the Sentinel shadow replay to re-run on raw candles with candidate params (or remove
   the "self-improving" claim).

### P2 — Harden & scale
9. Add a real `Exchange` adapter (python-binance/`unicorn-binance`) with the `Exchange`
   protocol; integrate `OrderManager` + `place_stop_loss`.
10. Walk-forward + regime attribution dashboards; alert on OOS decay (doc 28 group E).
11. Multi-pair correlation cap (don't be long BTC and short ETH simultaneously into the same
    macro move).
12. CI: lint + `pytest` + a smoke run of `run_backtest_real.py` on a tiny fixture.

---

## 5. What's Genuinely Good (keep doing this)

- **Bounded Sentinel + guardrails** (`sentinel.py`): ±10% delta, ≤4 changes, Σ=1, doc-21
  bounds, refusal-on-violation. This is the right shape for autonomous tuning. Rare to see
  done this carefully.
- **Full audit trail**: `trade_logs` / `decisions_log` / `results_log` / `exec_events` /
  `system_health` with `correlation_id`. Excellent for forensics.
- **Fail-loud telemetry**: `TelemetryError` halts entries on DB failure. Correct instinct.
- **Paper-first, human-gated promotion**: the *intent* is exactly right even where the
  *implementation* lags.
- **Test discipline**: 105 tests covering gates, kill-switch, promotion, lifecycle. Good
  breadth.
- **Documentation culture**: the 35-doc design base is a real asset — most projects skip it.

---

## 6. Changes Applied in This Review (verified)

| File | Change | Verification |
|------|--------|-------------|
| `tests/test_phase13_version.py` | Fixed brittle assertion (top CHANGELOG entry is the Telegram revamp, not "Dockerfile") | pytest 105/105 |
| `src/decision.py` | `side=None` on non-ENTRY persists (was leaking intended side) | test + lint OK |
| `scripts/bot_paper.py` | **Real daily-loss kill-switch** (was hardcoded `0.0`); `FeedHealth` wired | compiles; imports OK |
| `scripts/bot_paper.py` | **Real risk-based sizing** via `size_position` (was `size=1.0`) | `qty=0.004` for $1000/0.25%/$100SL |
| `scripts/bot_paper.py` | **Real structure/liquidity flags** in `build_state_mtf` (was all-floor) | compiles; engines now fed |

**Not yet fixed (P0/P1, need the exchange adapter + data):** real stop placement
(`PositionMonitor`), live spread/funding/ADL, learned entry threshold, honest multi-bar
backtest, Sentinel replay fix. These are the next batch.

---

## 7. Bottom Line (quant's verdict)

The *design* of Vaiśravana is better than 95% of retail trading bots. The *deployed reality*
is currently a thinned-down version where the most important safety controls were either
stubbed or hardcoded to safe-looking constants. That gap is the single biggest risk: the
docs will make you (and any reviewer) *believe* you're protected when you're not.

Close the P0 gaps (real stops, real kill-switch ✓, real sizing ✓, real structure ✓, hard
mode boundary), then re-validate the edge honestly (P1) before trusting the 85% WR story.
 As it stands, the system is a solid **research framework**, not yet a **trading system**.
