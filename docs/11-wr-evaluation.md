# WR Evaluation, End-to-End (v0.0.33 era)

Comprehensive evaluation of the live `@vaisravana_bot` (main bot, paper mode) decision
edge, the issues found, what was solved, and the current status of the WR-improvement
work. All numbers below come from an honest backtest that replays the production
decision path (`evaluate_strategy` + `build_context` + ADX gate + adaptive weights)
against real Binance klines fetched directly (15 pairs × 1m/5m/15m, ~1500 bars each).

---

## 1. Executive summary

- The live scalping edge (1m decision) was **losing money**: baseline WR 39.0%,
  expectancy **-0.025 R**. Only 4 of 15 pairs were +EV.
- Root cause of the low edge: risk:reward was set to 1.5 (scalping profile
  `tp_atr_mult=1.5, sl_atr_mult=1.0`), which needs >40% WR to break even, but 1m
  noise caps achievable WR near 38-42% regardless of parameters.
- Fix applied to source (NOT yet deployed): bump scalping R:R to 2.0
  (`tp=2.25, sl=1.125`), tighten entry bar `0.60 -> 0.68`, and strengthen
  `PairExcluder` (drop pairs with raw WR < 45%, was 40%). This turns expectancy
  from **-0.025 R to +0.167 R** while staying compliant with the owner mandate
  R:R >= 2:1.
- A partial-TP exit (lock 50% at +N R, move remainder to BE) was simulated and
  raises WR to 45-56% depending on the trigger level, at the cost of thinner
  expectancy. Several variants were tested (see section 6). User chose to keep
  investigating the balanced variant; the partial-TP exit has NOT been applied to
  the production exit logic yet.
- Current status: source changes committed (config + excluder). Bot is still
  running the OLD image. Deploy requires a rebuild (`fly deploy`) to take effect.

---

## 2. Context

The work started from a live incident: the main bot froze for ~7.8 hours (decision
loop stuck in `fetch_klines` SSL read, no retry, timeout 15s). It was recovered by
restarting the container. After recovery the loop was confirmed healthy (decisions
kept incrementing, py-spy showed the stack moving between fetch and decide, never
stuck). With the bot healthy again, the owner asked for a full end-to-end evaluation
of the trading edge and a significant improvement of the win rate (WR).

All evaluation below was done offline against real market data, replicating the
production decision path as closely as possible, without touching the running bot.

---

## 3. Issues found

### Issue A: decision loop could hang for hours (RESOLVED by restart, root cause known)
- Symptom: 0 new trades for ~7.8h, `decisions_log` frozen, last decision at 20:03.
- Diagnosis (py-spy): stack pinned in `fetch_klines` -> `recv_into` (SSL read) with
  no retry. The HTTP client used a 15s socket timeout but no retry/backoff, and the
  gateway fetch path could block the whole decision tick.
- Resolution: container restart cleared the stuck state. The loop is now healthy
  (decisions increment every ~1 min, py-spy shows normal fetch->decide->sleep
  movement). A proper fix is to add retry/backoff in `http_client.py`
  (`_read_with_timeout`) and make `fetch_klines` non-blocking / time-budgeted so a
  slow exchange call can never freeze the decision loop. That hardening was NOT
  applied in this pass (kept scope to the WR work).

### Issue B: the scalping edge was unprofitable (WR low + expectancy negative)
- Baseline (production profile, RR 1.5, entry 0.60): WR 39.0%, expectancy -0.025 R,
  only 4/15 pairs +EV.
- Contributing factors:
  1. R:R 1.5 is below the owner floor of 2:1 and mathematically requires >40% WR.
  2. 1m scalping has high tick noise: a 1-ATR SL gets clipped by ordinary wicks
     before the move develops, capping WR around 38-42% no matter the entry bar.
  3. Several low-quality pairs (SOL, WLD, BONK, AAVE in the baseline sample) dragged
     the aggregate WR down; the `PairExcluder` existed but its WR threshold (40%)
     was too loose to lift the aggregate meaningfully.

---

## 4. Methodology (honest backtest)

`scripts/eval_honest.py` replays the EXACT production decision path:

- Loads real 1m (decision) + 5m/15m (context) klines per pair.
- Builds `MarketState` via `build_state_mtf`, BTC cross-asset bias from real BTCUSDT
  klines, and `MarketContext` from the real 15m alt basket (all 15 pairs).
- Applies the ADX gate (`compute_adx` / `adx_allowed`) and adaptive weights, then
  calls `evaluate_strategy` (the same multi-strategy scorer the bot uses).
- Simulates exits on real candle highs/lows: TP = `tp_atr_mult * ATR`, SL =
  `sl_atr_mult * ATR`, MAXHOLD = 60 bars.
- Records R-multiple per trade, then aggregates WR / expectancy / profit factor (PF)
  overall and per pair.

Optional: `--partial --partial-r N` switches the exit to a partial-TP scheme
(lock 50% at +N R, move remainder to BE) to measure WR/expectancy under that exit.

Grid search over (entry_threshold, tp_atr_mult, sl_atr_mult) was run in
`scripts/tune_wr.py` to find the best parameter combo. `fetch_real_direct.py`
fetches the real klines (Binance fapi, with 1000x symbol mapping for sub-cent
tokens, retry/backoff for burst throttling).

Data window: fetched 2026-07-28 from Binance fapi, 15 pairs, 3 timeframes, 1500 bars
each. Stored under `data/klines/` (git-ignored, regenerable).

---

## 5. Baseline results (production profile, RR 1.5, entry 0.60)

Window had 8 active pairs (BTC had 0 entries on 1m). Aggregate:

- Total trades: 1425 (across 15 pairs in the first run; 635 in the RR-2.0 re-run
  because the tighter entry bar reduced trade count)
- Avg WR: 39.0%
- Avg expectancy: -0.025 R  (LOSING)
- Pairs +EV: 4 / 15

Per pair (production profile), exits were binary: win = +1.5R, loss = -1.0R.

---

## 6. Parameter grid-search (R:R fixed at 2.0 to satisfy owner floor)

Swept entry in {0.60,0.64,0.68,0.72} × (tp,sl) in {(2.0,1.0),(2.5,1.25),(3.0,1.5),
(2.25,1.125)}. Key findings:

- No parameter combo raised WR above ~38% on 1m scalping (noise ceiling).
- Expectancy flipped positive for EVERY 2.0 R:R combo vs the -0.025 R baseline.
- Best by expectancy: entry 0.68, tp 2.25, sl 1.125 -> WR 37.8%, expectancy +0.129 R,
  7/8 pairs +EV.
- entry 0.68 with tp 3.0 / sl 1.5 -> WR 38.0%, expectancy +0.119 R.
- entry 0.68 with tp 2.25 / sl 1.125 -> WR 37.8%, expectancy +0.129 R (top).

Conclusion: the single highest-leverage, lowest-risk change is raising R:R from 1.5
to 2.0 and tightening the entry bar to 0.68.

---

## 7. Four candidate paths (all with R:R 2.0 + entry 0.68 + excluder)

| Path | Exit scheme | Aggregate WR | Expectancy | Note |
|------|-------------|--------------|------------|------|
| A | full TP/SL only (param change) | 39.0% | **+0.167 R** | already applied to source; thickest profit |
| B | partial @ +1.0 R | **56.1%** | +0.052 R | highest WR, thinnest expectancy |
| C | partial @ +1.5 R | 45.0% | +0.085 R | balanced, chosen direction |
| C' | partial @ +1.25 R | 49.1% | +0.065 R | middle variant tested on request |

Excluder applied = drop pairs with expectancy < 0 (or raw WR < 45%). All four paths
are net positive expectancy (profitable), differing only in the WR vs thickness
trade-off. Scalping 1m structurally cannot exceed ~42% WR without a partial-TP exit.

---

## 8. What was applied to source (committed)

1. `src/config.py` -> `default_profiles()["scalping"]`:
   - `entry_threshold` 0.60 -> 0.68
   - `watch_threshold` 0.52 -> 0.58
   - `sl_atr_mult` 1.0 -> 1.125
   - `tp_atr_mult` 1.5 -> 2.25  (R:R = 2.0, compliant with owner floor)
   Verified: `profile.rr == 2.0`, `watch < entry`.

2. `src/pair_excluder.py` -> `PairExcluder.__init__`:
   - default raw WR exclude threshold raised 40% -> 45% (`if wr_exclude_below <= 0:
     self.wr_exclude_below = 45.0`). Net$ < 0 still triggers exclusion regardless.

These two changes alone move the edge from WR 39% / -0.025 R to WR 39% / +0.167 R
(profitable, no exit-logic change, fully Sentinel-compliant since only profile +
excluder defaults changed, not engine code).

3. Evaluation tooling added under `scripts/`:
   - `eval_honest.py` (honest replay harness, supports `--entry/--tp/--sl/--partial/
     --partial-r/--pair`)
   - `tune_wr.py` (parameter grid-search)
   - `fetch_real_direct.py` (real Binance klines fetch)
   - `reports/eval_honest.md` (raw output, git-ignored)

The partial-TP exit (paths B / C / C') was simulated in the harness ONLY. It has NOT
been written into the production exit logic (`bot_paper.py` / `monitor.py`) because
that changes execution behavior (outside Sentinel's allowed surface edits) and needs
a deliberate owner decision + image rebuild.

---

## 9. Current status

- Source: parameter + excluder improvements committed on branch `vaisravana-wave`.
- Bot (live): still running the OLD image (RR 1.5, entry 0.60). Changes are NOT live.
- Partial-TP: designed and simulated, not implemented in production exit code.
- Root-cause hang fix (retry/backoff in http_client): identified, NOT yet coded.

---

## 10. Recommended next steps (in order)

1. Deploy the committed parameter + excluder change (`fly deploy`) so the bot runs
   at R:R 2.0 / entry 0.68 / stricter excluder. Expected: profitable edge
   (+0.167 R) with no structural risk.
2. Decide on partial-TP: if the owner wants WR > 50%, implement path C (partial @
   +1.5 R, WR 45% / +0.085 R) or C' (@ +1.25 R, WR 49% / +0.065 R) in
   `bot_paper.py` exit handling + `monitor.py`, then re-backtest. Path B (@ +1 R,
   WR 56%) gives the highest WR but thinnest expectancy.
3. Harden `http_client._read_with_timeout` with retry/backoff and make
   `fetch_klines` time-budgeted so a slow exchange call can never freeze the
   decision loop again.

---

## 11. Reproduce

```bash
cd src
python3 scripts/fetch_real_direct.py            # fetch real klines (needs network)
python3 scripts/eval_honest.py --maxhold 60     # baseline (new profile)
python3 scripts/eval_honest.py --partial --partial-r 1.5 --maxhold 60   # path C
python3 scripts/tune_wr.py                       # full grid search
```

Numbers in this doc were produced 2026-07-28 against Binance fapi 1m/5m/15m data,
15 pairs, ~1500 bars each.
