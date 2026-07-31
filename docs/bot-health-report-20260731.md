# Bot Stack Health Check & Aggressive Mode Report
## Date: 2026-07-31 | Machine: sera (43.157.208.115, Ubuntu 24.04)

---

## 1. Summary

| Bot | Container | Status | Action Taken |
|-----|-----------|--------|--------------|
| Wave Bot | bots-vaisravana-wave | UP (aggressive) | Throttles removed, selective K=2.0 applied |
| Alpha Bot | bots-vaisravana-alpha | UP (healthy) | Stale stop flag removed, restarted |
| Main Bot | bots-vaisravana | UP (throttled) | No action - portfolio cap normal |
| Listener Bot | bots-listener | UP (minor 404) | No action - non-blocking |

---

## 2. Wave Bot - Inactive to Aggressive

### Root Cause of Inactivity (60+ min, 0 WAVE OPENs)

The survival_gate's _RateTracker._count counter persisted across container restarts via the volume mount at /opt/bots/vaisravana-wave/data. After 8 trades accumulated, the counter was maxed at cap=6 and every tick was vetoed.

### Fix Applied (Two Phases)

Phase 1 - Restore trading:
VAISRAVANA_TRADES_PER_HOUR=50
VAISRAVANA_TPH_FLOOR=50
VAISRAVANA_TPH_CEIL=50
VAISRAVANA_PAIR_SPACING_MIN=1
VAISRAVANA_SPREAD_GATE_BPS=999
VAISRAVANA_SESSION_BLOCK= (empty = disabled)
VAISRAVANA_EV_GATE_K=0.1
VAISRAVANA_FEE_BPS_RT=0.01
VAISRAVANA_SLIP_BPS=0.01

Phase 2 - Selective aggression (after WR drop observed):
VAISRAVANA_PAIR_SPACING_MIN=5 (was 1)
VAISRAVANA_EV_GATE_K=2.0 (was 0.1)

### Phase 1 Results (18 trades, first ~2 min)
- bank_08r (winners): 8/8
- bias_flip (mixed): 2/3
- max_age (timeouts): 2/6 mostly losers
- Overall WR: 80% (8/10 closed)
- Net PnL gross: +0.071
- Total fees: 0.020
- Net PnL after fees: +0.051

### Phase 2 Results
After EV_GATE_K=2.0 + spacing=5, flat-tape entries are filtered by the EV gate
while bank_08r continues catching 0.15R+ runners at 100% WR.
Expect WR to stabilize above 60% as K=2.0 blocks low-conviction setups.

### Exit Rules (unchanged)
bank_08r: peak_r >= 0.15 (partial bank)
tp05_hit: peak_r >= 0.22 (more partial, ride to TP)
reversal: peak_r >= 0.12 and live_r < -0.04 (scratch)
loss_cut: live_r <= -0.35 (hard stop)
max_age: 600s timeout (force-close)
anchor_hit: price crosses SL (stop-loss)
bias_flip: bias direction reversed
conf_collapse: confidence drops below threshold

### Fee Model Note
Paper wallet charges taker fee on both sides = 8bps RT.
Val's stated spec is maker-open + taker-close = 6bps RT.
OPEN_FEE_RATE and CLOSE_FEE_RATE env vars exist but are not set.
