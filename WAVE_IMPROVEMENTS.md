# Wave Engine — Improvements Roadmap

Prioritized for "surf even if random, improve win rate, be more expert."

## P0 — Stop the fee bleed (survival first)
- [ ] **Lower trade frequency.** Current 26/min is fatal. Options:
  - Raise `COOLDOWN_TICKS` to ~600 (50m) per pair.
  - Lower `MAX_OPEN_WAVES` to 6–8.
  - Require a *confirmed* structure break (not just bias) before entry.
- [ ] **Bigger notional per wave** (fewer, larger waves) so fee % of PnL drops.
  e.g. `risk_pct` 0.20 → 0.40, `max_notional` 100 → 200.
- [ ] Track **fee-adjusted R**: only count a close as a "win" if net of both
  fees is positive. Current `conf_collapse +0.07R` may be net-negative after fees.

## P1 — Let the 1.5R TP actually fire
- [ ] **Exit on TP before conf collapse.** In `evaluate_exit`, check TP first;
  only fall back to conf-collapse if price is far from TP.
- [ ] **Widen conf-hold** (`CONF_HOLD_MS` 1.5 → 3–5s) so a 1-tick conf dip
  doesn't kill a winning wave.
- [ ] **Trailing takeover:** once `peak_r >= 0.3` (breakeven), let the trailing
  SL ride instead of conf-exit.

## P2 — Regime awareness (don't force-trade flat tape)
- [ ] **ADX / range filter:** if `adx < 18` AND `ema_slope ≈ 0`, skip entry
  (stay flat). This prevents the bearish/neutral whipsaw.
- [ ] **Bias flip guard:** if `bias.strength` is weak (< 0.20) do not open.
- [ ] **Per-pair win-rate excluder:** keep `PairExcluder` but only activate after
  ≥ 10 trades AND WR < 35% (avoid excluding too early).

## P3 — Signal quality
- [ ] **Real flow/book pressure:** REST poll currently derives `book_pressure`
  from bookTicker bid/ask — good. Add `flow_delta` from aggTrade volume imbalance.
- [ ] **EMA cross as primary, not secondary:** `mtf_ema = ema_15m vs ema_1h` was
  dropped because `ema_1h` was dead; now that 1h is fed, re-test weighting.
- [ ] **Volatility-scaled SL/TP:** use ATR instead of fixed 1.0% so calm pairs
  don't get stopped at noise.

## P4 — Observability (record everything)
- [ ] **Live dashboard** (`/wave`, `/surf`) already show cards; add a
  `/stats` command with rolling win rate, avg R, fee drag, survival ETA.
- [ ] **Persist eval to a timeseries** (sqlite `wave_metrics` table or
  elasticsearch) so win rate is tracked per-hour, not just per-run.
- [ ] **Alert on death:** when `is_broke`, post to Telegram with final stats.

## P5 — Safety / ops
- [ ] Add `MAX_DAILY_TRADES` hard cap.
- [ ] Add `/clean` Telegram command to reset wallet + DB from chat.
- [ ] Document the `build --no-cache` + `up --force-recreate` requirement in
  `DEPLOY-VPS.md` (cost us hours this session).

---
*Next session starts here. Bot is stopped; DBs + docs committed.*
