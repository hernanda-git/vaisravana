# Enrichment — Lessons from `learnernoearner-listener`

> **Source:** `C:\Working Folder\Research\learnernoearner-listener` (production Binance
> USDⓈ-M Futures auto-trader by Hernanda, deployed on Fly.io). Extracted patterns that
> **benefit VaiÅravaá¹a** — applied to concrete execution, safety gates, and all-pairs reality.
>
> These are *enrichments*, not replacements. VaiÅravaá¹a's architecture (`ARCHITECTURE.md`),
> spec (`30`), and two-bot design are unchanged. This doc maps proven patterns → VaiÅravaá¹a docs.

---

## Why this benefits VaiÅravaá¹a

VaiÅravaá¹a's earlier docs (`22`, `25`, `28-B`, `30` §3) described execution/safety *conceptually*.
The listener has **run those concepts in production against real Binance API limits**. Since
VaiÅravaá¹a now trades **all Binance pairs** (not just BTC/ETH), the listener's hardest-won
lessons — **1000x contract handling**, **order validation/repair**, **SL/TP mechanics** —
are exactly the footguns VaiÅravaá¹a would hit. We adopt them proactively.

---

## Lesson 1 — Two-Layer Safety Gate (pre-decision / post-decision)

**Listener pattern:** Gate 1 runs *before* any expensive work (cheap rejects: idempotency,
cooldown, whitelist, media filter). Gate 2 runs *after* the decision and **hard-clamps**
values the decision engine cannot override (size, leverage, daily loss, SL direction).

**VaiÅravaá¹a mapping:** Our "Safety immutable" (`25`) already forbids Sentinel from disabling
daily-loss/kill-switch. Add the **two-layer split** to the decision pipeline (`24`/`30` §3):
- **Gate A (pre-scoring):** idempotency (one entry per **decision**, not signal), per-pair cooldown,
  pair whitelist/liquidity-filter, spread guard. Cheap, no engine cost.
- **Gate B (post-scoring, pre-execution):** hard clamps — clamp size to `risk_usd`,
  enforce `max_leverage`, `daily_loss_limit`, SL must be on correct side, margin ≤ 80%.
  The 9-engine score **cannot override** these.

> Applied to: `25-safety-shadow-rollback.md` (new §: Two-Layer Gate), `30` §3 (pre-entry
> checks now split into Gate A / Gate B).

---

## Lesson 2 — All-Pairs Reality: 1000x Contracts

**Listener finding:** Binance lists low-price tokens (BONK, PEPE, SHIB, FLOKI) as **1000x
contracts** (e.g. `BONKUSDT` → `1000BONKUSDT`). Differences that break naive code:
- Quantity in base tokens (integer `stepSize=1`), price in base-asset scale, `minNotional`
  enforced as `qty × price` ≥ $5.
- **`STOP`/`TAKE_PROFIT` conditional orders** are the default SL/TP (LIMIT fills, no
  slippage). But some contracts reject them (`-4120`) → must fall back.
- **`LIMIT SELL below market is NOT a valid SL** — it fills instantly as a cheap ask.**
  Naive SL placement closes the position immediately.

**VaiÅravaá¹a mapping:** VaiÅravaá¹a trades *all* Binance pairs → MUST handle 1000x. Add to `30` §2/§3:
- **Symbol resolution:** map user pair → exchange symbol via `exchangeInfo` (SymbolRegistry).
- **Filter-aware rounding:** load real `tickSize`/`stepSize`/`minNotional` per symbol;
  round price to tickSize, qty to stepSize (integer lots); enforce minNotional.
- **SL placement rule:** never place SL as a naive LIMIT on the wrong side. Use conditional
  STOP (reduceOnly) primary; fall back to position-manager mark-price polling if blocked.

> Applied to: `28-unexpected-factors.md` group B (new rows: 1000x mapping, LIMIT-SL instant
> fill, conditional-order -4120). `30` §2/§3 (all-pairs handling).

---

## Lesson 3 — Deterministic Order Validation & Repair (no-LLM fallback)

**Listener pattern (APE-1111 reliability pass):** every order goes through ONE validated
path, no model involvement in repair:
1. Resolve futures symbol.
2. Load **real** exchange filters (not hardcoded `rules[0]`).
3. Round price/qty to real filter; loop until `qty × price ≥ minNotional`.
4. Gate B sizes qty/leverage from config (no hardcoded literals).
5. **Pre-submission `validate_order`** checks precision/min/max/minNotional → must return
   `None` or order is **skipped** (never sent unvalidated).
6. Entry = **LIMIT**; idempotent `client_order_id` (one active entry per decision).
7. On reject: `_repair_order` re-derives qty/price from filters, revalidates, resubmits
   **once**. Still invalid → `VALIDATION_SKIP`. (LLM fallback removed.)

**VaiÅravaá¹a mapping:** Enrich `28-B` (partial fill / reject) with this concrete pipeline. The
Sentinel/reasoning engine must **never** be in the repair path — repair is deterministic.

> Applied to: `28-unexpected-factors.md` group B (new row: validate→repair→resubmit-once).
> `30` §3 (execution: LIMIT entry + idempotent id + validate-before-send).

---

## Lesson 4 — Position Manager Runtime Safety (background loop)

**Listener pattern (`position_manager.py`, 10s loop):**
- **SL dual-mechanism:** exchange conditional order (primary) + mark-price polling backup
  (for 1000x where conditional blocked).
- **Self-heal:** if SL/TP missing on exchange but position open → re-place once/session.
- **Orphan detection:** position with zero orders & age >30min → verify exchange (source of
  truth) → close or self-heal.
- **Time-based exit:** held > `max_hold` → market close.
- **reduceOnly** flag on all close orders (prevents accidental flip).
- **Telegram/Push notification on every close** with PnL, reason, closed-by.

**VaiÅravaá¹a mapping:** Our `30` §3 has trailing + max-hold but no *runtime protection loop*.
Add a **Position Monitor** component (already implied in `11` §8 Risk Manager) with the
dual-mechanism SL, self-heal, orphan detection, reduceOnly. Notifications on close feed the
`exec_events` / `trade_logs` logging.

> Applied to: `30` §3 (Position Monitor subsection), `25` (runtime safety), `11` §8.

---

## Lesson 5 — Correlation ID Tracing (log everything, linked)

**Listener pattern:** every pipeline run gets a 12-char `correlation_id` flowing
signal → decision → order → position → trade_logs → position_events. Full trace via
`GET /logs/{correlation_id}` or `SELECT * FROM trade_logs WHERE correlation_id=?`.

**VaiÅravaá¹a mapping:** Our `22` logs events but doesn't *link* them. Add `correlation_id`
to every telemetry table (`decisions_log`, `exec_events`, `trade_logs`, `results_log`, `system_health`)
so a single trade's full life is reconstructable — critical for Sentinel auto-review and
postmortems.

> Applied to: `22-telemetry.md` (add `correlation_id` column everywhere), `30` §4 (schema).

---

## Lesson 6 — Health Reporter (proactive subsystem check)

**Listener pattern (`health/reporter.py`, every 6h):** checks Telegram bot, Telethon
session, LLM provider, exchange connection + balance, portfolio, margin mode, leverage
ceiling, symbol registry, DB reachability. Sends Markdown-escaped Telegram report.

**VaiÅravaá¹a mapping:** Our `system_health` table captures snapshots but no *proactive reporter*.
Add a HealthReporter that periodically validates all subsystems and alerts — this is the
"logger must not fail silently" rule from `30` §4 made operational.

> Applied to: `25` (health reporter), `30` §4/`28` group C.

---

## Lesson 7 — Error Categorization (Binance-specific)

**Listener pattern:** errors classified → action:
- `401/403` AUTH → fail-fast, don't retry.
- `429` RATE_LIMIT → retryable with backoff.
- `5xx` SERVER → retryable.
- Network → return `PENDING` (not FAILED).
- Order failure → `OrderInfo(status="FAILED", error=...)`.

**VaiÅravaá¹a mapping:** Enrich `28-D` (API rate limit 429) and `28-B` (reject) with this
categorization so the execution-health metrics (`23`) and Sentinel reasoning (`29`) handle
each class correctly (e.g. never retry auth errors; backoff on 429).

> Applied to: `28-unexpected-factors.md` group B/D, `23` metrik eksekusi.

---

## Lesson 8 — Config Snapshots & Audit

**Listener pattern:** `config_snapshots` table + `ConfigSnapshotRepository` record every
config state; post-mortem compares trade against the snapshot active at the time.

**VaiÅravaá¹a mapping:** We already have `config_version` in `trade_logs` (`30` §4) and
`audit_trail` (`25` §7). Add **periodic config snapshots** (not just per-change) so a
rolling-window evaluation can attribute performance to the exact config that produced it.

> Applied to: `25` §7 (audit trail), `22` (add `config_snapshots` note).

---

## Summary: What changed in VaiÅravaá¹a docs

| Lesson | Primary doc updated |
|--------|---------------------|
| 1. Two-layer gate | `25`, `30` §3 |
| 2. 1000x all-pairs | `28-B`, `30` §2/§3 |
| 3. Validate/repair | `28-B`, `30` §3 |
| 4. Position monitor | `30` §3, `11` §8, `25` |
| 5. Correlation ID | `22`, `30` §4 |
| 6. Health reporter | `25`, `30` §4, `28-C` |
| 7. Error categories | `28-B/D`, `23` |
| 8. Config snapshots | `25` §7, `22` |

> These enrich VaiÅravaá¹a toward **execution reliability** (the listener's strongest area) —
> without changing VaiÅravaá¹a's strategy, two-bot architecture, or stability-first WR≥85% goal.
> Note: the listener *receives external signals*; VaiÅravaá¹a has **no signals** — it decides
> internally. We only borrowed the listener's *execution/safety* plumbing, not its
> signal-source model. VaiÅravaá¹a's `decisions_log` replaces the listener's `signals` table.
