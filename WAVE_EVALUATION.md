# Wave Engine — Evaluation Report

> Recorded from live paper-mode runs on sera (Tencent VPS). DBs in `/root/wave_eval_data/`.

## A. Pre-redesign run (`wave_live.db`)

| Metric | Value |
|--------|-------|
| Opens | 638 |
| Closes | 57 |
| Wins | 0 |
| Avg final R | **−0.327** |
| Avg peak R | **+0.152** |
| Close reasons | 56 anchor_hit + 1 conf_collapse |
| Direction | 588 SELL / 50 BUY |
| Notable | wave reached +0.15R then reversed to SL — no TP existed |

**Read:** pure noise-trader. No take-profit, one-directional (SELL), over-trades,
fee-killed. Peak +0.15R shows the wave *did* briefly win but was given back.

## B. Post-fix run (`wave_run1.db`, ~10 min)

| Metric | Value |
|--------|-------|
| Opens | 266 (≈26/min — over-trade) |
| Closes | 11 |
| Close reason | 11 × `conf_collapse` |
| Avg close R | **+0.07** (small winner) |
| Balance | $10.00 → $9.45 |
| Fees paid | $0.576 (266 trades × ~$0.002) |
| Sides | 801 SELL / 103 BUY (88% SELL — bearish window) |

**Read:** the engine now closes *small winners* (conf_collapse locks +0.07R).
But over-trading dominates: fee bleed ($0.576/10min) is the #1 survival risk.
The 1.5R TP is rarely reached because confidence dips close the wave first.

## C. Fresh capped run (`wave_run2.db`, interrupted)

Same code with `MAX_OPEN_WAVES=12`, `CONF_EXIT_FLOOR=0.16`, `COOLDOWN_TICKS=300`.
Interrupted before full evaluation; DB present for re-run.

## D. Win-rate verdict (honest, no bias)

- **Pre-fix:** 0% win, −0.327 R avg. Structurally broken (no TP, one-directional).
- **Post-fix:** still ~0% on the 1.5R TP, but closes are now *positive R*
  (conf_collapse +0.07). Net PnL negative only because of **fee bleed**, not
  because the waves lose — the waves actually scratch small wins.
- **Expert take:** the engine "surfs" but the edge is smaller than the fee.
  To make it profitable you must (1) cut trade frequency hard, (2) let TP fire,
  (3) avoid forcing trades in flat tape.

## E. Per-pair open counts (run1)

```
1000BONKUSDT 130 | PUMPUSDT 114 | ENAUSDT 112 | CRVUSDT 102 | PENGUUSDT 74
WLDUSDT 73 | INJUSDT 72 | WIFUSDT 63 | TAOUSDT 56 | APEUSDT 53
1000PEPEUSDT 26 | BTCUSDT 16 | ETHUSDT 6 | SOLUSDT 4 | AAVEUSDT 3
```
Altcoins trade far more than BTC/ETH — min-notional + low price makes them
cheap to open, but they also whipsaw most.

## F. SQL for re-evaluation

```sql
-- closes by reason (note: schema uses state='WAVE_BREAK', not 'CLOSED')
SELECT reason, COUNT(*) FROM wave_log WHERE state='WAVE_BREAK' GROUP BY reason;
-- per-pair
SELECT pair, COUNT(*) FROM wave_log GROUP BY pair ORDER BY 2 DESC;
-- sides
SELECT side, COUNT(*) FROM wave_log GROUP BY side;
```
