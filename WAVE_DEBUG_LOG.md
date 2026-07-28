# Wave Engine — Debug Log (chronological)

This is the raw debugging trail from the session that got the bot from
"completely silent, 0 opens" to "trading end-to-end in paper mode".

Each step below was verified against live container logs / eval scripts.

---

## Step 0 — Baseline: bot silent
- `docker logs` showed REST poll heartbeat but **0 WAVE OPEN**.
- Eval script (`wave_eval.py`) seeded klines manually → bias `bearish 0.67`,
  `scan` returned candidates. So the *logic* worked; the *live feed* did not.

## Step 1 — `manager.closed_today` AttributeError
- REST poll loop crashed every cycle: `name 'manager' is not defined` (later
  `AttributeError: manager.closed_today`).
- `WaveManager` only had `self.waves`; `run_wave_engine` did
  `wave_state["closed_today"] = list(manager.closed_today)`.
- Fix: `list(getattr(manager, "closed_today", []))`.

## Step 2 — `_rest_poll_loop` scope
- `_rest_poll_loop` is a **module-level** function but referenced `manager` and
  `wave_state` (locals of `run_wave_engine`).
- Fix: added `manager, wave_state` params; pass them at the `create_task` call.

## Step 3 — bookTicker has no lastPrice
- Switched REST poll from `ticker/24hr` to `ticker/bookTicker` to get bid/ask,
  but bookTicker has **no `lastPrice`** → `price = 0` → `if price:` false →
  `on_tick` never called.
- Fix: `price = (bid + ask) / 2.0` from bookTicker.

## Step 4 — `read_bias` neutral (ema_1h=0)
- `read_bias` compared `ema_15m` vs `ema_1h`. In live REST mode `ema_1h` was
  almost always 0 (WS 1h stream down, REST 1h fetch not wired).
- `_ema_cross_strength(ema_15m, 0)` = 0 → `mtf_ema = 0` → score < threshold →
  `neutral` → 0 opens.
- Fix: compare `ema_15m` vs live `price` (always available).

## Step 5 — `ctx.ema_15m` not fed from 15m klines
- Even after Step 4, `ema_15m` was only updated from tick price
  (`ema_update(ctx.ema_15m, tick.price, 20)`), so `ema_15m ≈ price` →
  `mtf_ema ≈ 0` → neutral.
- `on_kline` fed `ema_1h` from 1h closes but NOT `ema_15m` from 15m closes.
- Fix: in `on_kline`, `if tf == "15m" and is_final: ctx.ema_15m = ema_update(...)`.
- Verified: live `read_bias` now returns bullish/bearish for real pairs.

## Step 6 — `zone_cache.has_zones` missing
- `wave_quality_pass` called `zone_cache.has_zones(pair)` — method does not exist
  on `SMCZoneCache` → `AttributeError` in `scan` → 0 opens.
- Fix: `if zone_cache and zone_cache.get_zones(pair):` (truthy list check).
- Also: zone check / invalidation now **skipped when cache empty** (REST mode
  has no zones) so the bot is not blocked from trading.

## Step 7 — `Wave.margin` field missing
- `manager.open` passed `margin=margin` to `Wave(...)` but the dataclass had no
  `margin` field → `Wave.__init__() got unexpected keyword 'margin'` → 0 opens.
- Fix: added `margin: float = 0.0` to `Wave`.

## Step 8 — temp DIAG + scoping crash
- Added a temp DIAG log using `nonlocal _diag_n` (duplicate) and `pair`/`ctx`
  before they were assigned locally → `SyntaxError` / `cannot access local
  variable`.
- Fix: removed temp DIAG; `pair = tick.pair` at top of `on_tick`; removed
  leftover `nonlocal _diag_n`.

## Step 9 — rebuild discipline
- `docker compose restart` does NOT rebuild the image; all fixes were invisible.
- Fix: `docker compose build --no-cache vaisravana-wave` +
  `docker compose up -d --force-recreate vaisravana-wave`.

---

## Result after all fixes
- 33 opens in 2 min, then 266 opens / 10 min (over-trade), realistic notional
  ($5/$10), 3x leverage, BUY+SELL both firing, fees visible.
- Closes: `conf_collapse` at r=+0.05..0.07 (small winners), balance drifting
  down from fee bleed ($0.576 / 10 min).
- Bot now survives and trades; survival is limited by fee bleed, not logic bugs.
