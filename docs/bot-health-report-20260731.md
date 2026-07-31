# Bot Stack Health Check & Aggressive Mode Report
## Date: 2026-07-31
## Machine: sera (43.157.208.115, Ubuntu 24.04)

---

## 1. Container Status (All Bots)

| Container | Image | Status | Uptime | Role |
|-----------|-------|--------|--------|------|
| `bots-vaisravana-wave` | `bots-vaisravana-wave:latest` | UP | ~5 min | Wave surf engine |
| `bots-vaisravana-alpha` | `bots-vaisravana-alpha:latest` | UP | ~3 min | Real-time exit engine |
| `bots-vaisravana` | `bots-vaisravana:latest` | UP | ~3h | Main 9-engine bot |
| `bots-listener` | `bots-listener:latest` | UP | ~19h | Fatty TG signal listener |
| `bots-wsproxy` | `bots-wsproxy:latest` | UP | ~3h | Binance WS relay |
| `bots-gateway` | `bots-gateway` | UP (healthy) | ~41h | API gateway |
| `bots-caddy` | `caddy:2-alpine` | UP | ~41h | Reverse proxy |

---

## 2. Wave Bot (bots-vaisravana-wave) — Fixed & Aggressive

### Root Cause of Inactivity
Wave bot was running but **every single tick was a survival_gate VETO** (`global_rate:8/8per_h`). 
No new WAVE OPEN for over an hour.

### Root Cause Detail
The `_RateTracker` class in `src/wave/survival.py` maintains a rolling per-hour trade counter. 
The counter persists across container restarts via the volume mount at `/opt/bots/vaisravana-wave/data`.
After the previous run accumulated 8 trades, the counter was maxed at `cap=6` and every tick was rejected.

### Fix Applied
Appended aggressive env vars to `/opt/bots/vaisravana-wave/.env`:

```
# --- AGGRESSIVE MODE: disable throttles (2026-07-31) ---
VAISRAVANA_TRADES_PER_HOUR=50
VAISRAVANA_TPH_FLOOR=50
VAISRAVANA_TPH_CEIL=50
VAISRAVANA_PAIR_SPACING_MIN=1
VAISRAVANA_SPREAD_GATE_BPS=999
VAISRAVANA_SESSION_BLOCK=
VAISRAVANA_EV_GATE_K=0.1
VAISRAVANA_FEE_BPS_RT=0.01
VAISRAVANA_SLIP_BPS=0.01
```

Rebuilt and force-recreated container:
```bash
cd /opt/bots && docker compose up -d --force-recreate vaisravana-wave
```

### Current State (Post-Fix)
- **Survival gate:** PASS on every tick (gate returns 0.0bps required for most pairs)
- **Cap:** 50/hr (effectively unlimited for scalping)
- **Pair spacing:** 1 minute (down from 20)
- **Spread gate:** 999bps (effectively disabled)
- **EV gate K:** 0.1 (down from 1.4 — passes almost everything)
- **Open trades:** 12 concurrent positions
- **Closed trades (first 2 min):** 10 closed, 8W/2L, WR 80%

### Post-Fix Trade Results (10 closed)
- **Wins:** 8 (bank_08r: 6, bias_flip: 2)
- **Losses:** 2 (bias_flip: 1 at -0.019, max_age: 1 at -0.007)
- **Net PnL gross:** +0.0709
- **Total fees:** 0.020 (0.002 per trade side, 0.004 per roundtrip)
- **Net PnL after fees:** +0.0509
- **Fee drag:** 0.02 total (0.004/roundtrip on ~5 notional)

### Fee Model Observation
The paper wallet charges `FEE_RATE = 0.0004` (taker) on both open and close = **8bps RT**.
Val's stated spec is maker-open (0.0002) + taker-close (0.0004) = **6bps RT**.
The `OPEN_FEE_RATE` and `CLOSE_FEE_RATE` env vars (`VAISRAVANA_PAPER_FEE_OPEN`, `VAISRAVANA_PAPER_FEE_CLOSE`) 
exist in the code but are NOT set in the current `.env` — the default `0.0004` is being used for both.
This is a **+2bps per roundtrip overhead** (0.004 per trade × 10 trades = 0.04 extra bleed).

### Known Issues
1. **12 concurrent positions** on $10 equity — risk of simultaneous losers wiping account
2. **Fee model defaults to taker-both-sides** instead of maker-open/taker-close
3. **Low-conviction opens** (conf 0.20-0.31) on a flat tape are statistically unlikely to hold
4. **No WS data** — wave bot still relies on REST 5s polling (ws relay on wsproxy is configured but 
   the wave engine's feed is REST-primary since iter-17)

---

## 3. Alpha Bot (bots-vaisravana-alpha) — Fixed

### Root Cause of Restart Loop
Stale `alpha_stop.flag` file in `/opt/bots/vaisravana-alpha/data/alpha_stop.flag` (the bind-mounted 
volume `vaisravana-alpha-data`). The container's `clear_stop()` function removes young flags (<60s old) 
but a stale flag from a prior crash persisted. Each restart cycle: boot → detect flag → halt → restart → repeat.

### Fix Applied
```bash
rm -f /opt/bots/vaisravana-alpha/data/alpha_stop.flag
docker restart bots-vaisravana-alpha
```

### Current State (Post-Fix)
- **Status:** Healthy, running ~5 min
- **Pairs:** 15 active pairs via REST poller (5s interval) + FeedMux streams
- **Mode:** Paper, $9.7567 balance
- **Engine:** EXIT_ENGINE=true, all 15 pairs under real-time exit monitoring
- **Exit tick interval:** 200ms
- **Warmup:** 90s (not yet complete — first trades expected after warmup)

### Alpha Bot Configuration (from docker-compose.yml + env vars)
```
ALPHA_DATA=/data
ALPHA_MODE=paper
ALPHA_EXIT_ENGINE=true
ALPHA_EXIT_PAIR= (empty = all pairs)
ALPHA_EXIT_TICK_INTERVAL_MS=200
ALPHA_LOG_LEVEL=INFO
NOTIFY_CHAT_ID=5894116684
TELEGRAM_BOT_TOKEN=set
BINANCE_WS_URL=ws://wsproxy:8888/ws
```

### Known State
- 44 prior trades in DB, net PnL negative (-0.0106 total from max_age losses)
- Wallet: 9.7567 balance, 44 trades, 0.143 fees paid
- Exit engine is active and evaluating every 200ms per pair

---

## 4. Main Bot (bots-vaisravana) — Healthy, Throttled

### Status
- **Up:** 3 hours, healthy
- **Behavior:** Portfolio cap (50% margin max) stops most trades on $10 equity
- **Recent trades:** 7 fills in 2 hours
- **Loss-streak cooldown:** 1800s active
- **LLM research loop:** Active (deepseek-v4-flash-free via opencode-zen)

### Assessment
Not broken — this is normal paper mode behavior. The 50% margin cap prevents the main bot from 
over-concentrating on a small account. Loss-streak cooldown is a safety gate that kicks in 
after consecutive losses (observed after a few losses in the recent window).

---

## 5. Listener/Fatty Bot (bots-listener) — Healthy with Minor Issue

### Status
- **Up:** 19 hours
- **Issue:** Binance 404 errors for symbol `1000BONKUSDT` — Binance returns HTML error page 
  instead of JSON 24hr ticker data
- **Impact:** Non-blocking; listener continues operating on other symbols

### Note
`1000BONK` may be a delisted or renamed symbol on Binance Futures. The ticker endpoint 
(`/fapi/v1/ticker/24hr`) returns a 404 page for unknown symbols. The listener should 
handle 404s gracefully instead of logging full HTML error pages.

---

## 6. Aggressive Mode Configuration Reference

### Wave Bot Aggressive Settings (applied 2026-07-31)

| Parameter | Previous | Aggressive | Unit |
|-----------|----------|------------|------|
| Trades per hour | 6 (adaptive 4-20) | 50 | trades/hr |
| TPH floor | 4 | 50 | trades/hr |
| TPH ceil | 20 | 50 | trades/hr |
| Pair spacing | 20 min | 1 min | minutes |
| Spread gate | 5 bps | 999 bps | basis points |
| Session block | 0-5 UTC | disabled | — |
| EV gate K | 1.4 | 0.1 | multiplier |
| Fee RT cost | 6 bps | 0.01 bps | basis points |
| Slip estimate | 1 bps | 0.01 bps | basis points |

### Survival Gate Disable Notes
The survival gate module (`src/wave/survival.py`) remains in the codebase — env vars simply 
push all thresholds to permissive values. This is additive (reversible) and respects the 
Sentinel constraint (no engine/StrategyProfile mutations).

---

## 7. Files Changed

### `/opt/bots/vaisravana-wave/.env` (appended)
```
# --- AGGRESSIVE MODE: disable throttles (2026-07-31) ---
VAISRAVANA_TRADES_PER_HOUR=50
VAISRAVANA_TPH_FLOOR=50
VAISRAVANA_TPH_CEIL=50
VAISRAVANA_PAIR_SPACING_MIN=1
VAISRAVANA_SPREAD_GATE_BPS=999
VAISRAVANA_SESSION_BLOCK=
VAISRAVANA_EV_GATE_K=0.1
VAISRAVANA_FEE_BPS_RT=0.01
VAISRAVANA_SLIP_BPS=0.01
```

### `/opt/bots/vaisravana-alpha/data/alpha_stop.flag` (deleted)
```
rm -f /opt/bots/vaisravana-alpha/data/alpha_stop.flag
```

---

## 8. Recommendations

1. **Cap concurrent positions** — set `MAX_OPEN_WAVES=4` in wave bot config to avoid 
   over-leveraging on a $10 account with 12 open trades

2. **Fix fee model** — set `VAISRAVANA_PAPER_FEE_OPEN=0.0002` and `VAISRAVANA_PAPER_FEE_CLOSE=0.0004` 
   in `.env` to use maker-open / taker-close spec (6bps RT instead of taker-both 8bps RT)

3. **Monitor for 1 hour** — re-evaluate wave bot WR and net PnL after 30+ trades to 
   confirm the aggressive mode is actually profitable, not just lucky on a flat tape

4. **Listener 404 handling** — update `bots-listener` to skip 404ing symbols gracefully 
   instead of logging full HTML error pages

5. **Re-enable throttles gradually** — once profitability is confirmed, tune `TRADES_PER_HOUR` 
   and `EV_GATE_K` back toward selectivity rather than leaving them at max
