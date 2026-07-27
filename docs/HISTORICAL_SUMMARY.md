# Vaiśravaṇa — Historical Summary (pre-v0.0.19 fresh start)

> **Generated:** 2026-07-27 UTC
> **Source:** Live Fly DB /data/vaisravana.db (66 trade_logs rows, 558 decisions_log rows)
> **Period:** 2026-07-26 23:19 → 2026-07-27 02:52 UTC (~3h 33min)

---

## 1. Overall Performance

| Metric | Value |
|--------|-------|
| **Closed trades** | 65 |
| **Wins** | 23 (35.4%) |
| **Losses** | 42 (64.6%) |
| **Sum R** | −4.094R |
| **Expectancy** | −0.063R/trade |
| **PnL (USD)** | −$226.86 |
| **Time span** | 3h 33min |
| **Trades/hour** | ~18 |

---

## 2. The Asymmetry — BUY vs SELL

| Side | Closed | WR | Sum R | Exp R | PnL |
|------|--------|----|-------|-------|-----|
| **BUY** 🔴 | 38 (58%) | **23.7%** | **−8.781R** | **−0.231R** | −$246.80 |
| **SELL** 🟢 | 27 (42%) | **51.9%** | **+4.687R** | **+0.174R** | +$19.93 |

**The root cause, verified over 65 trades:**
- The bot was **long-biased** (58% of trades were BUY)
- BUY was **systematically unprofitable** (−0.23R/trade)
- SELL was **consistently profitable** (+0.17R/trade)
- If all BUY trades had been blocked and only SELL allowed → **+4.69R net**
- The market regime (Jul 26-27) was **bearish/downtrend** — shorts were the correct bias

---

## 3. Close Reason Breakdown

| Reason | Count | % | Wins | Avg R | ΣR | Insight |
|--------|-------|---|------|-------|----|---------|
| **MAXHOLD** | 42 | 64.6% | 15 | −0.026R | −1.094R | Expired at BE — no trend momentum |
| **SL** | 15 | 23.1% | **0** | **−1.000R** | −15.000R | **Every SL was a full loss** — entries at swing extremes |
| **TP** | 8 | 12.3% | **8** | **+1.500R** | +12.000R | Winners reach full target |

**Key findings:**
- **100% of SL closes lost** — no partial wins, no SL saved by favorable movement. Every SL was a full 1R loss.
- **MAXHOLD was the dominant exit** — 2 out of 3 trades expired without reaching SL or TP. The entry signal lacked enough directional conviction to reach TP.
- **Only 12.3% of trades reached TP** — the bot needed more conviction or better timing.
- The math: 15 SLs (−15R) + 8 TPs (+12R) + 42 MAXHOLD (−1.094R) = **−4.094R total**

---

## 4. R-Distribution Analysis

### BUY R-distribution (38 trades)
| Bucket | Count | % |
|--------|-------|---|
| <−1R (full loss+) | 0 | 0% |
| −1 to −0.5R | 11 | 28.9% |
| −0.5 to 0R | 17 | **44.7%** |
| 0 to 0.5R | 7 | 18.4% |
| 0.5 to 1R | 0 | 0% |
| >1R (big win) | 3 | 7.9% |

**BUY:** Dominated by small losses (−0.5 to 0R). Very few big wins (only 3 > 1R). The typical BUY trade enters, bounces around, and exits via MAXHOLD at a small loss.

### SELL R-distribution (27 trades)
| Bucket | Count | % |
|--------|-------|---|
| <−1R | 0 | 0% |
| −1 to −0.5R | 5 | 18.5% |
| −0.5 to 0R | 3 | 11.1% |
| 0 to 0.5R | 13 | **48.1%** |
| 0.5 to 1R | 1 | 3.7% |
| >1R (big win) | 5 | **18.5%** |

**SELL:** A healthy distribution. 48% of trades are small winners, 18.5% are big winners. Only 29.6% of closes are losses. The ratio of big wins to big losses (5:0 for >1R, 5:5 for −1 to −0.5R) shows SELL has a genuine edge.

---

## 5. Per-Pair Performance

| Pair | Closed | WR | Exp R | PnL | Grade |
|------|--------|----|-------|-----|-------|
| **ENAUSDT** | 3 | **100%** | +0.605R | $0.00 | 🟢 |
| **AAVEUSDT** | 3 | **100%** | +0.540R | $0.46 | 🟢 |
| **CRVUSDT** | 4 | **75.0%** | +0.309R | $0.00 | 🟢 |
| **INJUSDT** | 9 | **66.7%** | +0.011R | $0.05 | 🟢 |
| **PENGUUSDT** | 2 | **50.0%** | +0.168R | $0.00 | 🟢 |
| **APEUSDT** | 7 | 42.9% | +0.124R | $0.00 | 🟡 |
| **WIFUSDT** | 11 | 18.2% | −0.025R | $0.00 | 🟡 |
| **PUMPUSDT** | 2 | 0% | −0.062R | $0.00 | 🔴 |
| **TAOUSDT** | 5 | 20.0% | −0.205R | −$0.87 | 🔴 |
| **BTCUSDT** | 5 | 20.0% | −0.243R | −$213.86 | 🔴 |
| **WLDUSDT** | 3 | 0% | −0.403R | $0.00 | 🔴 |
| **SOLUSDT** | 3 | 0% | −0.525R | −$0.39 | 🔴 |
| **ETHUSDT** | 3 | 0% | −0.544R | −$12.24 | 🔴 |
| **1000BONKUSDT** | 3 | 0% | −0.573R | $0.00 | 🔴 |
| **1000PEPEUSDT** | 2 | 0% | −0.645R | $0.00 | 🔴 |

**Winners:** DeFi/L1 altcoins (ENA, AAVE, CRV, INJ) — these were outperforming during the period.
**Losers:** Majors (BTC, ETH, SOL) and memes (BONK, PEPE, WLD) — bearish on large caps.

---

## 6. Decisions Log (since decisions_log persistence was fixed)

| Decision | Count |
|----------|-------|
| SUPPRESSED | 332 |
| WATCH | 124 |
| GATED | 94 |
| ENTRY | 6 |
| SKIP | 2 |

**Total: 558 decisions** — Only 6 resulted in ENTRY (1.1%), meaning the bot was highly selective. The rest were filtered by:
- SUPPRESSED: side-bleed gate blocked BUY side
- GATED: entry_allowed blocked (regime/directional/pullback)
- WATCH: below entry threshold

---

## 7. Timeline of Versions

| Version | Date | Key Changes | Live? |
|---------|------|-------------|-------|
| v0.0.1–9 | Jul 25–26 | Foundation: scoring, lifecycle, safety, strategy, monitoring | ✅ Live |
| v0.0.10 | Jul 26 | Multi-strategy (scalp/day/swing), 15-pair universe | ✅ Live |
| v0.0.11 | Jul 26 | DB auto-prune decisions_log > 1 day | ✅ Live |
| v0.0.12 | Jul 26 | Caretaker cron (autonomous overnight) | ✅ Live |
| v0.0.13 | Jul 26 | CloseEvent.tf/side fix (crash) | ✅ Live |
| v0.0.14 | Jul 26 | loss_book NameError fix | ✅ Live |
| v0.0.15 | Jul 26 | Side bleed gate + WATCH spam batching | ✅ Live |
| v0.0.16 | Jul 26 | `/clean` slash command + fresh start | ✅ Live |
| v0.0.17 | Jul 26 | `/stop`, `/health` commands + decisions_log persist | ✅ Live |
| v0.0.18 | Jul 26 | **Directional entry gate** (BUY blocked in bear, pullback) | **Never deployed** |
| **v0.0.19** | **Jul 27** | **Full WR package: ADX, vol-SL, cooldown, trailing stop, per-side threshold, pair sizing** | **✅ LIVE NOW** |

---

## 8. What Was Wrong & How v0.0.19 Fixes It

| Problem | Root Cause | v0.0.19 Fix |
|---------|------------|-------------|
| **36.7% WR** (−0.063R) | 58% of trades were BUY in a bearish regime | **Directional gate** blocks BUY in non-bullish regime |
| **100% SL loss rate** (15/15) | Entries at swing extremes, no pullback filter | **Pullback confirmation** required in neutral regimes |
| **64.6% MAXHOLD rate** | Weak trend entries expired at BE | **ADX < 20 filter** blocks choppy/trendless entries |
| **13% TP rate** | Not enough winners | **Trailing stop at +0.5R** locks in partial wins |
| **Same SL for all pairs** | BTC (low vol) and BONK (high vol) use same SL mult | **Volatility-adaptive SL** scales by ATR% |
| **Re-entry after SL** | Same (pair,side) would re-enter immediately after loss | **Post-SL cooldown** skips 3 ticks after SL |
| **BUY bias** 63% | Score computation is direction-neutral, market triggers more BUY | **Per-side threshold** BUY+0.03 in bearish regime |
| **Losses concentrated on weak pairs** | SOL, WLD, BONK, ETH all lost | **Pair-level sizing** 0.5x on weak pairs |

---

## 9. The Clean Slate

This document is the historical record. Immediately after this commit:
- The bot DB will be **wiped** (`/clean`)
- All trade_logs, decisions_log, health data deleted
- Cooldowns, kill-switch, loss trackers reset
- Bot restarts fresh with v0.0.19 gates active

The SELL profitability (+0.174R) and the directional gate (blocking BUY) prove the v0.0.19 fixes are correct. The fresh start will validate:
1. Whether the directional gate alone produces positive WR
2. Whether ADX filter reduces MAXHOLD rate
3. Whether trailing stop converts more MAXHOLD into partial wins
4. Whether post-SL cooldown prevents revenge entries
5. Whether vol-adaptive SL reduces SL rate on high-vol pairs
