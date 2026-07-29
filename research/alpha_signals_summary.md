## Report delivered: `/root/scalp_entry_signals_report.md` (full version, ~18.6KB)

**What I did:** Searched academic literature (arXiv/SSRN/Springer/Frontiers 2024–2026) + practitioner sources, and **live-verified every Binance endpoint** (curl, no auth, all working: premiumIndex, openInterest, openInterestHist, takerlongshortRatio, topLongShortPositionRatio, globalLongShortAccountRatio).

### Top 5 by evidence strength for 5–45 min trades

1. **CVD / taker order-flow imbalance** (continuation) — strongest academic backing (Vafin 2026 SSRN 6938742; Frontiers 2026 "Microstructure alpha": OFI passes stability-selection for 5-min forward returns). **Zero extra REST calls** — klines field idx 9 (taker buy vol) → `delta = 2*takerBuy − vol`, z-score 15-bar CVD. Gate: veto SELL when cvd_z > +1; confirm when < −0.5. Hit rates ~53–58%, bp-scale edge — a selectivity filter, not a standalone trigger.
2. **OI-delta × price direction** (regime confirm / flush detector) — practitioner canon: price↓+OI↑ = new shorts → confirms SELL; price↓+OI↓ = liquidation flush → **veto** (this is likely why the bot's SELLs fill at flush bottoms). Poll `/fapi/v1/openInterest` per cycle (weight 1); seed history from `openInterestHist?period=5m`. Directly upgrades the underused `funding_oi` stub.
3. **VWAP deviation bands** (entry location) — quantified: 59% WR BTC intraday reversion backtest (CoinQuant), 61–63% reversion from 2σ bands, 57% WR/1.7RR equity study. For the SELL bucket: enter on pullback INTO VWAP (dev ∈ [0,+1.5σ]), veto when dev < −2σ (overextended) — fixes "TP rarely hit". Computed from existing klines.
4. **BTC lead-lag onto alts** (gate) — peer-reviewed 2026 (Springer, Binance HF data): alts lag BTC ~1 min, unidirectional Granger causality, lag strategy beats B&H; tick studies: 16–118 s lag. Veto alt SELL if BTC 3m return z > +1; boost if BTC dumped and alt hasn't caught up. Zero extra calls.
5. **Funding extremes + L/S crowding** (risk veto only) — strong event evidence (funding 10%→30% ann. before Oct-2025 cascade) but slow at minute scale. Best rule: positive funding during downtrend = trapped longs → confirms SELL; funding z < −2 after a big drop = crowded shorts → veto SELL (squeeze fuel). `/fapi/v1/premiumIndex` (live premium, one batched call for all pairs) + `/futures/data/*` ratios on a 5-min wheel.

**Secondary:** orderbook imbalance (grade-A evidence at native frequency but stale at 60s REST cadence — tiebreaker only); liquidation cascades (use OHLCV+OI proxy: vol_z>3 ∧ range_z>3 ∧ OI −0.5%/5m → 5–10 min SELL cooldown; forceOrder WS capped at 1 msg/sec/symbol); round numbers (clustering confirmed, **no post-level return edge** — use only for TP placement in front of levels); time-of-day (boost momentum 13–17 UTC, damp 02–06 UTC & Sunday US morning).

**Best stack (Stack A):** SELL only when trending_bear ∧ OI-rising-price-falling ∧ cvd_z<0 ∧ btc_z≤0 ∧ not-flush-cooldown ∧ not-funding-squeeze — all cheap booleans removing the three documented failure modes.

**Caveats flagged:** two 2026 SSRN negative-result papers show naive OHLCV/funding signals fail live; practitioner win rates treated as upper bounds. API budget: ~31 weighted calls/min vs 2400 limit — trivial.

**Issues:** transient search-API rate limits (retried OK); `execute_code` blocked in this profile (used direct tool calls instead). No other blockers.