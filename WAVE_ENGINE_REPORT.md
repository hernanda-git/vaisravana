# Vaisravana Wave Engine — Full Report

> Date: 2026-07-28
> Author: Kira (val's assistant) + Hermes agent
> Branch: `vaisravana-wave`
> Status: **bot runs end-to-end in paper mode; cascade bugs fixed; improvements live; evaluation ongoing**

---

## 1. What this is

The Wave Engine is a tick-driven, structure-based "surfing" trader that opens a
`Wave` on SMC/EMA confluence and rides it until structure breaks, TP hits, or
confidence collapses. It runs **paper mode** (no real orders): `VAISRAVANA_MODE=paper`
→ `PaperSimExchange`, fake balance default **$10**, taker fee **0.04%** per open/close.

It is deployed on **sera** (Tencent Cloud VPS, Ubuntu 24.04) as the docker
container `bots-vaisravana-wave` (compose project `bots`), built from
`/opt/bots/vaisravana-wave` and wired to the `@wave_vaisravana_bot` Telegram bot.

---

## 2. Cascade of bugs found & fixed (this session)

The bot was completely silent (0 opens) for most of the session. Root cause was
a **chain of bugs**, each uncovered only after the previous one was fixed:

| # | Bug | Symptom | Fix |
|---|-----|---------|-----|
| 1 | `manager.closed_today` attribute did not exist | REST poll crashed every cycle (`AttributeError`) → bot dead silently | `getattr(manager, "closed_today", [])` |
| 2 | `_rest_poll_loop` is module-level but referenced `manager` + `wave_state` (local to `run_wave_engine`) | `name 'manager' is not defined` → REST poll dead | pass `manager, wave_state` as params |
| 3 | `ticker/bookTicker` has no `lastPrice` field | `price = 0` → `if price:` false → `on_tick` never called | derive `price = (bid+ask)/2` from bookTicker |
| 4 | `read_bias()` compared `ema_15m` vs `ema_1h`; `ema_1h` was usually 0 (WS 1h stream down) | bias always `neutral` → 0 opens | compare `ema_15m` vs live `price` instead |
| 5 | `ctx.ema_15m` only updated from tick price (≈ price) | `mtf_ema ≈ 0` → neutral → 0 trades | feed `ema_15m` from 15m kline closes in `on_kline` |
| 6 | `zone_cache.has_zones(...)` method does not exist on `SMCZoneCache` | `AttributeError` in `scan` → 0 opens | use `zone_cache.get_zones(pair)` (truthy check) |
| 7 | `Wave` dataclass had no `margin` field | `Wave.__init__() got unexpected keyword 'margin'` → 0 opens | add `margin: float = 0.0` to `Wave` |
| 8 | duplicate `nonlocal _diag_n` (temp DIAG) + `pair`/`ctx` used before `nonlocal` assignment | `SyntaxError` / `cannot access local variable` | removed temp DIAG; `pair = tick.pair` at top of `on_tick` |
| 9 | `docker compose restart` does not rebuild from a changed image | all code fixes silently ignored | must `build --no-cache` + `up --force-recreate` |

**Lesson:** every fix revealed the next hidden bug. The engine now trades.

---

## 3. Improvements built (expert wave-surfing)

### 3.1 Realistic sizing (was: `size = notional/price` only)
- `lev = int(env VAISRAVANA_PAPER_LEVERAGE, 3)` (3x)
- `notional = max(MIN_NOTIONAL[pair], min(survival_notional, balance))`
  - `MIN_NOTIONAL`: Binance per-pair floors (BTC 100, ETH 10, SOL 10, others 5)
  - `survival_notional = balance * risk_pct` (0.20) clamped to `max_notional` (100)
- `margin = notional / lev`
- `size` (base units) = `notional / price` (telemetry only)

### 3.2 Take-profit (was: none → 0% win rate)
- `tp_price = entry ± risk*1.5` (1.5R target)
- near-TP at `+0.5R` (bank partial profit so peak gains are not given back)

### 3.3 Trailing stop (was: breakeven at 1.0R, never reached)
- breakeven at `peak_r >= 0.3` (SL → entry, lock 0)
- lock `+0.3R` at `peak_r >= 0.6`
- lock `+0.6R` at `peak_r >= 1.0`

### 3.4 Wider structure SL (was 0.5%)
- anchor buffer `1.0%` so choppy tape doesn't stop out before the wave forms

### 3.5 Thresholds relaxed (surf even if random)
- `BIAS_THRESH` 0.15 → 0.06
- `CONF_ENTRY_FLOOR` 0.25 → 0.12
- `MIN_BIAS_STRENGTH` 0.40 → 0.30
- `STRUCTURE_SCORE_FLOOR` 0.25 → 0.12
- `CONF_EXIT_FLOOR` 0.25 → 0.16 (hold long enough for 1.5R TP)
- `COOLDOWN_TICKS` 180 → 300 (~25m)

### 3.6 Over-trade guard
- `MAX_OPEN_WAVES = 12` (env `VAISRAVANA_MAX_OPEN_WAVES`) — skip new entries past cap

### 3.7 Paper wallet hardening
- persists `/data/paper_wallet.json` (balance, trades, fees, peak)
- `is_broke` halts engine when balance ≤ `VAISRAVANA_PAPER_STOP` (default 0.0)
- fee charged on every open + close; visible in notifications

### 3.8 Notification redesign (was: `Entry: 0.0 | SL: 0.0 Size: 670.70`)
- `notify_wave_open`: side icon, Entry, SL, TP, Size(base), Notional$, Margin$, Lev, Conf, OpenFee$, Balance
- `notify_wave_close`: Entry, Exit, SL/TP, R, RealizedPnL$, CloseFee$, Net$, Balance
- `/wave` card: per-wave unrealized PnL + totals (used balance, unrealized, realized)
- `/surf` card: closed waves, win rate, avg R, total PnL, fees

### 3.9 `/stop` command fix (was: local-scope assignment bug)
- `import wave.engine as E; E.stop_requested = True` (module-level flag)
- fallback file flag `/data/.wave_stop`
- verified: engine actually halts (container exits)

---

## 4. Evaluation data (recorded)

All DBs copied to `/root/wave_eval_data/` on sera (and committed under `eval_data/`):

| File | Content |
|------|---------|
| `wave_live.db` | pre-redesign run: 638 opens, 57 closes, 0 wins, avg R −0.327, peak R +0.152, 56 anchor-hit + 1 conf-collapse, 588 SELL / 50 BUY |
| `wave_run1.db` | post-fix run: 266 opens / 10 min, 11 closes all `conf_collapse` r=+0.07, balance $9.45, fee $0.576 |
| `wave_run2.db` | fresh run with `MAX_OPEN_WAVES` cap (interrupted before full eval) |

**Honest read:** the engine now trades and even closes small winners
(`conf_collapse` at r=+0.05..0.07). But it over-trades (266 opens/10min) and the
fee bleed ($0.576 in 10 min) is the dominant drag on survival. The 1.5R TP is
rarely reached because confidence dips close the wave first.

---

## 5. Files changed (this session)

```
src/wave/bias.py        — mtf_ema vs price; thresholds lowered
src/wave/gate.py        — zone check guarded; thresholds lowered
src/wave/manager.py     — realistic sizing + margin; MAX_OPEN_WAVES; trailing;
                          wider SL; TP; CONF_EXIT_FLOOR lowered
src/wave/models.py      — Wave.margin field
src/wave/paper_wallet.py— persisted paper wallet (already present, hardened)
src/wave/engine.py      — ema_15m feed; _rest_poll_loop params; bookTicker price;
                          notify redesign; /stop flag
src/wave/db.py          — log_wave_close writes pnl_usd + fees_usd
scripts/bot_paper.py    — /stop router fix; /wave /surf pass wallet
.env                    — paper vars (REDACTED token)
```

---

## 6. How to run / rebuild (IMPORTANT)

```
cd /opt/bots
docker compose build --no-cache vaisravana-wave
docker compose up -d --force-recreate vaisravana-wave
```

`docker compose restart` is NOT enough — it does not rebuild the image from
changed source.

Reset paper wallet: `docker exec bots-vaisravana-wave rm -f /data/paper_wallet.json`
Reset DB: `docker exec bots-vaisravana-wave rm -f /data/vaisravana-wave.db`

---

## 7. Known limitations / next steps

See `WAVE_IMPROVEMENTS.md`. Top priorities:
1. Reduce fee bleed (lower trade frequency, raise MAX_OPEN_WAVES discipline)
2. Let 1.5R TP actually fire (tighter conf-hold, or exit on TP before conf)
3. Add regime filter so the bot does not force-trade flat tape
4. Record win rate properly (DB `pnl_usd` now written; build a live dashboard)
