# Comprehensive Bot Evaluation & Aggressive Scalping Redesign

> Date: 2026-07-30
> Owner: valarion
> Mode: paper trading, $10 starting balance
> Fee model: maker 0.02% open + taker 0.04% close = 6bps round-trip + ~1bps slip = 7bps total

---

## 1. CURRENT STATE — ALL 3 BOTS

### 1.1 Main Bot (vaisravana)

**Architecture:**
- 9-engine dual scoring: trend (30%), momentum (20%), volume (15%), structure (15%), liquidity (10%), atr (5%), funding_oi (5%)
- Multi-strategy layer: scalping/day/swing running concurrently
- Cross-asset + MTF relational context as modulator
- Two-layer safety gate (Gate A: pre-scoring, Gate B: post-scoring hard clamp)
- Paper execution: limit@mid maker, stop-loss, repair logic

**Performance (last 9 closed trades):**
- Win rate: 44.4% (4 wins / 5 losses)
- Total PnL: -0.041$
- Total fees: -0.027$
- Net (PnL + fees): **-0.068$**
- Close reasons: MAXHOLD (6), CONF_COLLAPSE (2), SL (1)
- 2 open positions (WLDUSDT SELL, ENAUSDT SELL)

**Problems:**
- Entry threshold too high (0.55-0.92) — only A+ setups pass
- MAXHOLD exits dominate — positions held too long, bleeding out
- CONF_COLLAPSE exits cutting winners prematurely
- Only 9 closed trades in hours of operation — too passive
- Portfolio cap blocking new entries (margin >50% equity)
- All trades are SELL — no BUY bias, missing upside

### 1.2 Wave Bot (vaisravana-wave)

**Architecture:**
- Wave engine: bias engine + scanner + manager
- Wave lifecycle: surf, trail, jump-OUT, partial/add, cooldown
- Survival gates: adaptive throttle (4-20 TPH), fee-aware EV gate, spread gate, session block
- SMC zone cache, structure detection, EMA-based bias
- Conf_collapse adverse-excursion gate (iter-19)
- Loss cut at -0.35R (iter-8)
- Max wave age 900s (15m)

**Performance (last 7 closed trades):**
- Win rate: 42.9% (3 wins / 4 losses)
- Total PnL: -0.026$
- Total fees: -0.014$
- Net (PnL + fees): **-0.040$**
- Close reasons: max_age (4), bank_08r (1), bias_flip (1), conf_collapse (1)
- 2 open positions

**Problems:**
- Survival gates blocking 100% of entries — adaptive throttle at floor (4/h)
- max_age exits dominate — waves held too long, never reaching TP
- Only 7 closed trades — extremely passive
- conf_collapse bucket is worst exit: avgR -0.136 (iter-19 eval)
- Expected move (15-20bps) barely covers fees (7bps) + safety margin

### 1.3 Alpha Bot (vaisravana-alpha)

**Architecture:**
- Engine runtime with survival gates, bias engine, scanner, manager
- Real-time exit engine merged (EXIT_ENGINE=true)
- Survival gates: adaptive throttle (4-20 TPH), fee-aware EV gate (K=1.4), spread gate, session block
- Paper wallet with trade tracking
- Agentic DB for run tracking

**Performance (last 26 closed trades):**
- Win rate: 34.6% (9 wins / 17 losses)
- Total PnL: -0.048$
- Total fees: -0.060$
- Net (PnL + fees): **-0.108$**
- Close reasons: max_age (15), reversal (4), bank_08r (5), conf_collapse (1), bias_flip (1)
- 6 open positions (all BUY)

**Problems:**
- Worst win rate of all 3 bots: 34.6%
- max_age exits dominate (57.7% of closes) — waves held way too long
- reversal exits are bleeding: avgR -0.057
- bank_08r is the only profitable bucket: avgR +0.012
- Survival gates blocking entries — adaptive throttle at 6/h cap
- Expected move (17bps) < required (23bps) — fee cost too high relative to edge

---

## 2. ROOT CAUSE ANALYSIS

### 2.1 The Fee Problem

All 3 bots use the same fee model:
- Maker 0.02% open + Taker 0.04% close = 6bps round-trip
- Plus ~1bps slip = 7bps total per round trip
- At $10 balance with $5 notional per trade, 7bps = $0.0035 per trade
- With 26 trades in alpha: $0.060 in fees alone

**The fee cost is 55% of the total loss in alpha.** The bots are bleeding to fees faster than they're losing on trades.

### 2.2 The Exit Problem

**max_age exits dominate across all 3 bots:**
- Main bot: 6/9 (67%) max_hold exits
- Wave bot: 4/7 (57%) max_age exits
- Alpha bot: 15/26 (58%) max_age exits

This means positions are held too long, never reaching TP, and bleeding out slowly. The exit logic is fundamentally broken — it's cutting winners on conf_collapse but letting losers run to max_age.

### 2.3 The Entry Problem

**Entry thresholds are too high:**
- Main bot: 0.55-0.92 (scalping/day/swing)
- Wave bot: conf-based, survival gates blocking everything
- Alpha bot: survival gates blocking everything

The survival gates are the biggest blocker. They're designed to protect capital, but they're protecting against the wrong thing. They block entries when the bot's recent performance is poor, which creates a death spiral: poor performance -> fewer entries -> no new data -> can't recover.

### 2.4 The Strategy Problem

**All 3 bots are trying to be the same thing:** swing/day traders with tight risk management. But at $10 balance with 7bps fees, swing trading is mathematically impossible. The edge needs to come from:
1. High frequency (more samples to compound)
2. Tight stops (less fee drag per trade)
3. Quick exits (less max_age bleeding)
4. Positive expectancy per trade (even at 55% WR with R:R 0.8)

---

## 3. AGGRESSIVE SCALPING REDESIGN

### 3.1 Design Principles

1. **No survival gates blocking entries** — the bot must always be able to trade
2. **Aggressive frequency** — target 20-40 trades/hour
3. **Tight stops** — 0.15R max loss per trade
4. **Quick exits** — 0.20R target, trail after 0.10R
5. **Fee-aware** — every trade must be +EV after fees
6. **Balance growth is the only metric** — win rate, frequency, R:R all secondary to growing balance

### 3.2 New Architecture

```
tick -> bias (1m) -> scan -> open (no gates) -> manage (trail + quick exit) -> close
```

**Removed:**
- Survival gates (fee-aware EV, adaptive throttle, spread gate, session block)
- MAXHOLD / max_age timer (replaced with aggressive trail)
- conf_collapse exit (cutting winners)
- Portfolio cap (allow full margin utilization)

**Added:**
- Aggressive scalping profile: 1m TF, 0.15R SL, 0.25R TP
- Trailing stop: moves to breakeven at +0.10R, then trails at 0.08R
- Quick exit: close at +0.25R or -0.15R, whichever comes first
- Fee tracking: real-time PnL after fees
- Balance growth monitor: if balance drops 20%, pause and re-evaluate

### 3.3 Entry Logic

**Scoring (simplified for speed):**
1. Trend: EMA15 > EMA50 (bullish) or EMA15 < EMA50 (bearish) — 0.5 weight
2. Momentum: RSI(7) > 50 (bullish) or RSI(7) < 50 (bearish) — 0.3 weight
3. Structure: BOS/CHoCH in direction of trade — 0.2 weight

**Entry threshold: 0.50** (minimum confluence)
**No survival gates** — every pair that scores >= 0.50 gets a trade

### 3.4 Exit Logic

**Primary exit:**
- TP: +0.25R (quick profit)
- SL: -0.15R (tight stop)
- Trail: after +0.10R, move SL to breakeven, then trail at 0.08R

**Secondary exit:**
- Max hold: 300s (5m) — hard close if nothing else fires
- Conf collapse: only if live_r <= -0.10R (don't cut winners)

### 3.5 Sizing

**Per trade:**
- Risk: 2% of balance ($0.20 at $10)
- Leverage: 5x (to amplify small moves)
- Notional: balance * risk_pct * leverage / sl_distance

**Portfolio:**
- Max open: 5 positions (spread risk)
- Max margin: 80% of balance (aggressive but not reckless)

---

## 4. IMPLEMENTATION PLAN

### 4.1 Wave Bot (primary target)

The wave bot is the best candidate for aggressive scalping because:
- It already has the wave lifecycle (surf, trail, exit)
- It has SMC zone detection
- It has bias/confidence scoring
- It just needs the gates removed and exits tightened

**Changes:**
1. Remove survival gates from `wave/survival.py`
2. Lower entry threshold to 0.50
3. Tighten SL to 0.15R, TP to 0.25R
4. Add aggressive trail (breakeven at +0.10R, trail at 0.08R)
5. Remove MAX_WAVE_AGE_S or set to 300s
6. Remove conf_collapse exit or tighten to -0.10R
7. Add fee tracking to every trade
8. Add balance growth monitor

### 4.2 Main Bot

The main bot has the most sophisticated scoring but is too conservative. For aggressive scalping:

**Changes:**
1. Remove portfolio cap
2. Lower entry thresholds for scalping profile to 0.50
3. Add aggressive scalping profile (1m TF, 0.15R SL, 0.25R TP)
4. Remove MAXHOLD timer
5. Add quick exit logic

### 4.3 Alpha Bot

The alpha bot has the worst performance (34.6% WR). It needs the most aggressive changes:

**Changes:**
1. Remove survival gates entirely
2. Lower entry threshold to 0.50
3. Tighten SL to 0.15R, TP to 0.25R
4. Add aggressive trail
5. Remove max_age exit
6. Add fee tracking

---

## 5. EXPECTED PERFORMANCE

### 5.1 Math

With aggressive scalping:
- Win rate: 55% (realistic for 1m TF with tight stops)
- R:R: 0.25/0.15 = 1.67
- Fee per trade: 7bps
- Expected value per trade: 0.55 * 0.25 - 0.45 * 0.15 - 0.007 = 0.1375 - 0.0675 - 0.007 = **+0.063R**

At 20 trades/hour:
- Expected PnL/hour: 20 * 0.063R * $0.05 (R unit) = **$0.063/hour**
- At $10 balance: **0.63%/hour growth**
- Over 24 hours: **~16% daily growth** (compounding)

### 5.2 Risk

- Max drawdown: 20% (balance drops to $8)
- If balance drops 20%, pause and re-evaluate
- If balance drops 50%, stop and redesign

---

## 6. NEXT STEPS

1. Implement aggressive scalping profile in wave bot (primary)
2. Test in paper mode for 24 hours
3. Monitor balance growth, win rate, fee drag
4. Iterate based on results
5. Apply to main bot and alpha bot if wave bot succeeds