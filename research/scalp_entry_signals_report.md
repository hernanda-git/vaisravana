# Evidence-Backed Entry Signals for 1m–15m Binance USDT-Perp Scalping (Free Public Endpoints)

Prepared 2026-07-29. All endpoints verified live/no-auth against fapi.binance.com on this date.
Context: weighted-scoring 1m bot, 15 pairs, only profitable bucket = SELL in trending_bear, TP rarely hit, profit from time-exits, fees 0.02%/0.04% (0.06% round trip → gross edge per trade must exceed ~0.10–0.15% to matter).

---

## 0. Honest evidence calibration (read first)

- Peer-reviewed evidence for *minute-scale* predictability is real but small (single basis points per event); practitioner win-rate claims (55–65%) are unaudited and should be treated as upper bounds. Two 2026 SSRN papers explicitly document that naive OHLCV+funding cross-sectional signals and backtest-only ML claims fail live (SSRN 6701738 "Failure of Cross-Sectional Alpha Screening on Crypto Perps"; SSRN 6566940 "The Prediction Paradox").
- Consequence for this bot: use these signals as **gates and sub-score inputs that improve the *selectivity* of the existing profitable bucket (SELL/trending_bear)**, not as standalone entry triggers. The realistic payoff is fewer bad entries (higher expectancy) rather than a new alpha stream.

---

## 1. TOP 5 BY EVIDENCE STRENGTH (5–45 min holding)

### #1 — Cumulative Volume Delta / Taker order-flow imbalance (CONTINUATION)
- **What it predicts:** direction persistence over the next 1–30 min. Aggressor-side net flow is the single most robust short-horizon predictor in the microstructure literature, and in crypto the aggressor side is *reported, not estimated* (SSRN 6938742, Vafin 2026, review of OFI in crypto). A 2026 Frontiers in Blockchain study ("Microstructure alpha") finds OFI among 12 features that all pass stability-selection for predicting **5-min forward returns** at minute frequency; short-horizon momentum and spread proxies are the most robust. EFMA 2025 "Order Flow and Cryptocurrency Returns": order flow dominates fundamentals for out-of-sample prediction (LS Sharpe 3.45 daily — longer horizon, but confirms flow is the dominant information channel).
- **Realistic expectancy:** sign-agreement hit rates of ~53–58% on next-5–15m direction in microstructure studies; per-event edge is bp-scale, so it must ride on top of a trend signal, not replace it.
- **Endpoints (free, zero extra infra):**
  - Already in your klines: field index **9 = taker buy base asset volume** and 5 = volume in `GET /fapi/v1/klines`. Per-bar delta = `2*takerBuyVol − vol`. CVD = running sum. **This costs zero extra REST calls.**
  - Aggregated 5m ratio: `GET /futures/data/takerlongshortRatio?symbol=X&period=5m&limit=N` (verified: returns buySellRatio, buyVol, sellVol; 5m granularity, ~30 days history).
- **Wiring:**
  - `delta_ratio_1m = (2*takerBuy − vol)/vol` per bar; `cvd_z = zscore(sum(delta over last 15 bars), lookback 240 bars)`.
  - **Score input:** for SELL, add `w * clip(−cvd_z/2, −1, 1)` into the flow/funding_oi sub-score.
  - **Gate (recommended first):** veto SELL when `cvd_z > +1` (aggressive buying against you); confirm SELL when `cvd_z < −0.5` AND last 1m delta_ratio < 0.
  - **CVD absorption divergence** (price makes lower low, CVD makes higher low → sellers absorbed) = veto fresh SELL (practitioner-standard; CryptoCred 2023 guide).

### #2 — Open-interest delta × price direction (REGIME CONFIRMATION / FLUSH DETECTOR)
- **What it predicts:** whether a down-move is *new short positioning* (continuation, safe to SELL) or a *position flush* (late; reversal risk). Canonical mapping (practitioner canon — CryptoCred, Leviathan; consistent across 2023–2026 sources):
  - price ↓ + OI ↑ (+CVD ↓) = shorts opening → **trend continuation, confirms SELL**
  - price ↓ + OI ↓ = longs closing/liquidated → move mostly done → **veto fresh SELL**
  - price ↑ + OI ↓ = short squeeze → don't chase either way
- **Evidence:** quantified academic backtests are thin at minute scale, but this is the most universally used perp-native filter among practitioners, and it mechanically identifies liquidation flushes (see #5/liquidations) that explain "TP rarely hits, entries near flush bottoms lose". Evidence grade: B (strong practitioner consensus, weak formal quantification).
- **Endpoints:**
  - Live snapshot: `GET /fapi/v1/openInterest?symbol=X` (weight 1; poll each 60s cycle → build your own 1m OI series). Verified.
  - History: `GET /futures/data/openInterestHist?symbol=X&period=5m&limit=N` (verified; sumOpenInterest + sumOpenInterestValue; 5m granularity, updates every 5m, 30d history) — use to seed the series on startup.
- **Wiring:** `oi_chg_15m = OI_now/OI_15m_ago − 1`, `px_chg_15m` likewise.
  - SELL confirmation score: `+1 if px_chg<0 and oi_chg>+0.15%`, `0 if flat`, `−1 (veto) if px_chg<−1×ATR15 and oi_chg<−0.5%` (flush).
  - This directly upgrades the underused `funding_oi` stub and specifically sharpens the bot's one profitable bucket.

### #3 — VWAP deviation / reversion bands (ENTRY LOCATION)
- **What it predicts:** intraday price gravitates back to session VWAP; extensions beyond ±2σ revert with elevated probability. Published/backtest numbers: ~61–63% reversion rate from 2σ extensions and 57% win rate / 1.7:1 RR in an equity intraday study (TradeAlgo summary of JPM 2021); a 3-month BTC intraday VWAP-reversion backtest (CoinQuant, 2025/26) reports **59% win rate** but warns losses run larger than wins without a stop — i.e., positive win rate, fragile expectancy. Practitioner consensus (r/algotrading 2025 threads): VWAP works better as *location filter* than as trigger.
- **For this bot (SELL-side):** in trending_bear, the highest-quality short entry is a **pullback INTO VWAP / upper band that stalls**, not a breakdown entry far below VWAP. This matches the observed "TP rarely hit" pathology: entries chasing extension have no room; entries at VWAP-retest do.
- **Endpoint:** none needed — compute from existing 1m klines: session VWAP anchored 00:00 UTC = `Σ(typicalPrice·vol)/Σvol`; σ bands from rolling deviation of (price−VWAP).
- **Wiring:**
  - `vwap_dev = (close − VWAP)/σ_vwap`.
  - **Gate:** veto SELL when `vwap_dev < −2` (already overextended down; reversion against you). 
  - **Score input:** for SELL in trending_bear, reward `vwap_dev ∈ [0, +1.5]` (pullback zone below/at resistance) — e.g. `score = 1 − |vwap_dev − 0.75|/1.5` clipped to [0,1].
- Evidence grade: B+ (multiple independent quantified backtests, but crypto-specific numbers come from short samples).

### #4 — BTC lead-lag onto alts (CROSS-ASSET GATE)
- **What it predicts:** alt returns over the next ~1–5 min follow BTC's immediately preceding move; effect is bigger for less-liquid pairs. Peer-reviewed 2026 (Kurihara & Matsumoto, *Asia-Pacific Financial Markets*, open access, Binance high-frequency data): small-cap alts show significant cross-correlation at **lag −1 min**, unidirectional Granger causality BTC→alts across bull/bear regimes, and a lag-trading strategy using BTC's preceding return **consistently beats buy-and-hold**. Tick-level studies put the lag at ~16–118 s for mid-caps (Anderson 2023, BTC→ADA), i.e., right at your 60s decision cadence. Cross-crypto predictability at 5–13 min rebalancing also confirmed (JEDC 2024).
- **Endpoints:** you already fetch BTCUSDT klines. Zero extra calls.
- **Wiring:**
  - `btc_ret_3m = BTC close/close[3] − 1`, normalized by BTC 3m ATR → `btc_z`.
  - **Gate:** veto alt SELL if `btc_z > +1` (BTC just impulsed up; alts will follow up within 1–2 min). Confirm/boost alt SELL if `btc_z < −1` and the alt has NOT yet moved as much as beta implies (laggard-catch-up short).
  - Cheap beta: rolling 1h regression of alt 1m returns on BTC 1m returns, or just rank pairs by correlation once a day.
- Evidence grade: A− (peer-reviewed, crypto-native, correct horizon, strategy-validated).

### #5 — Funding-rate extremes + positioning crowding (RISK VETO / SQUEEZE FILTER)
- **What it predicts:** *not* minute-scale direction — it predicts which side is crowded and therefore which direction can cascade. Extreme positive funding preceded the Oct 10, 2025 liquidation event (funding climbed ~10%→~30% annualized in the days before; 1.6M accounts liquidated — FTI Consulting via Yellow research, 2025). Practitioner rule with the best support: **the divergence, not the level** — e.g. *positive funding persisting during a downtrend = trapped longs = bear continuation* (confirms your SELL bucket); *deeply negative funding after a big drop = crowded shorts = squeeze risk → veto SELL*.
- **Honest read:** at 5–45 min horizon funding is slow (settles 8h, premium index updates continuously). It has genuine event-level evidence (2024–2025 cascades) as a *conditioning* variable, weak evidence as an *entry* signal. Use as veto/bias only. Academic daily-scale cross-sectional funding signals failed live tests (SSRN 6701738) — don't over-weight.
- **Endpoints (verified):**
  - `GET /fapi/v1/premiumIndex?symbol=X` → `lastFundingRate` + live `markPrice−indexPrice` premium (the *instantaneous* crowd pressure; more responsive than settled funding).
  - `GET /fapi/v1/fundingRate?symbol=X&limit=N` → settled history for z-scoring.
  - Crowding: `GET /futures/data/globalLongShortAccountRatio` (retail accounts — contrarian at extremes), `GET /futures/data/topLongShortPositionRatio` (top traders by position — follow, not fade). Both verified, 5m period, 30d history.
- **Wiring:**
  - `fund_z = z(lastFundingRate, 30d history)`; `premium_bp = (mark−index)/index`.
  - **Veto:** block new SELL if `fund_z < −2` AND price already < −1.5×ATR60 below 1h ago (crowded shorts into a hole = squeeze fuel).
  - **Confirm:** boost SELL if `fund_z > +0.5` while regime = trending_bear (longs still paying to stay trapped), especially if `globalLongShortAccountRatio` is rising (retail buying the dip — fuel below).
- Evidence grade: B (strong event/case evidence at hours–days; conditioning value at minutes; poor as trigger).

---

## 2. SECONDARY SIGNALS (worth wiring, weaker or infra-heavier evidence)

### Orderbook imbalance (OBI)
- **Predicts:** next seconds-to-few-minutes direction; academically the strongest micro predictor (55–60% next-move sign accuracy in equity/crypto L2 studies; arXiv 2607.09230 shows order flow adds predictive power conditional on book state). **Problem for this bot:** the signal half-life is seconds; sampled once per 60s via REST it is stale and noisy. Grade A evidence at native frequency, C at your cadence.
- **Endpoint:** `GET /fapi/v1/depth?symbol=X&limit=50` (weight 2, fine for 15 pairs/min); or `<sym>@depth5@500ms` websocket if you ever add one.
- **Wiring:** `obi = (Σbid_qty − Σask_qty)/(Σbid+Σask)` over top 20 levels; use only as **tiebreaker confirmation** (require `obi < 0` for SELL), weight small. Also useful: distance-weighted book (near-book imbalance) is less spoofable than raw top-of-book.

### Liquidation cascade detection (forceOrder)
- **Predicts:** cascade exhaustion → sharp snap-back within minutes; entering *with* a cascade after it has run = worst entry on the board. Oct-2025 events made this the most-watched perp signal; formal backtests are scarce (practitioner dashboards, Medium guides, LinkedIn live-runs of "trade away from liquidation cluster" bots). Grade C+ formally, but mechanically sound and it *explains your loss pattern* (SELL fills at flush bottoms).
- **Endpoint:** websocket `wss://fstream.binance.com/ws/!forceOrder@arr` (all symbols) or `<sym>@forceOrder`. **Caveat: since 2021-04-27 Binance pushes at most ONE forceOrder per symbol per second** — it's an indicator of liquidation activity, not the full tape.
- **No-websocket proxy (recommended given your architecture):** flag `flush = (vol_z_1m > 3) AND (range_z_1m > 3) AND (oi_chg_5m < −0.5%)`. This is computable from data you already have + #2's OI series.
- **Wiring:** after a `flush` in the SELL direction → **cooldown gate: no new SELL for 5–10 min** (or only allow reversion BUY logic if the bot ever gets one). A flush *against* an open short = take the time-exit early.

### Round-number magnets
- **Evidence:** price clustering at round numbers is strongly confirmed in crypto (Li 2020; *Financial Innovation* 2021 intraday clustering; Southampton study: >10% of BTC trades end in "00"), **but** the same Southampton study finds **no significant return pattern after round numbers** → clustering ≠ tradable direction. Grade: A for clustering existing, D for entry alpha.
- **Use:** execution only. Place TP *in front of* (not beyond) round levels ($0.50/$1/$100/$1k grids per pair); expect stalls there → with your fee structure this directly raises TP hit rate at zero signal cost. Do not spend score weight on it.

### Session-open / time-of-day momentum
- **Evidence:** BTC volume & realized vol peak around **13:00–16:00 UTC (US equity open window; H14–H16 highest)** and trough 03:00–05:00 UTC (multiple studies incl. IREF 2024, Bitstamp studies). Concretum/SFI (2025, SSRN 5209907): intraday **trend-following works best from Sunday 19:00 ET through Monday**, and is *negative* (choppy/mean-reverting) US Sunday morning. The arXiv "Quarter-Hour Effect" (2026, Binance perps 2021–2024): algorithmic flow clusters at :00/:15/:30/:45 boundaries; quarter-hour opening order imbalance has *significant* predictive content — but mainly at **4–12 h horizons**, not 5–45 min; boundary minutes themselves are noisier.
- **Wiring:** a per-hour multiplier on the momentum sub-score (boost 13:00–17:00 UTC weekdays; damp 02:00–06:00 UTC and Sunday 12:00–17:00 UTC); optionally skip entries in the exact first 1m bar after :00/:15/:30/:45 (algo-burst noise). Grade B for vol timing, C for direction.

### Taker buy/sell ratio & long/short ratios (the /futures/data family)
- Covered inside #1 and #5. One extra practitioner datapoint: divergences where **Binance taker ratio < 1 while price holds** preceded 5–10% corrections (Feb 2024, Aug 2023 — CryptoQuant via NewsBTC). Note `/futures/data/*` endpoints update on 5-minute snapshots — poll once per 5 min per pair, not every cycle; cache.

---

## 3. WHAT STACKS BEST (combination playbook)

Your engine supports gates + sub-score weights. Recommended stacks, in order of expected impact:

**Stack A — "Confirmed bear continuation" (sharpen the profitable bucket):**
SELL allowed only if: regime=trending_bear AND `oi_chg_15m > 0` with price down (#2) AND `cvd_z < 0` (#1) AND `btc_z ≤ 0` (#4) AND NOT flush-cooldown (#5b) AND NOT `fund_z < −2` (#5).
→ Every element is a cheap boolean; jointly they remove the three documented failure modes: shorting a flush bottom, shorting into a BTC bounce, shorting a crowded-short squeeze.

**Stack B — "VWAP pullback short" (fix TP-rarely-hit):**
In trending_bear, prefer entries where `vwap_dev ∈ [0,+1.5]` and the 1m bar shows delta_ratio flipping negative (#3 + #1). Entries at the band instead of the extension give ~0.4–0.8×ATR of room to VWAP → TPs become reachable; keep the time-exit as fallback.

**Stack C — "Crowd-fuel bonus" (small weight):**
`fund_z > +0.5` AND `globalLongShortAccountRatio rising` while price trends down → +0.5 to funding_oi sub-score (trapped longs = fuel). Follow top-trader positioning (`topLongShortPositionRatio` falling = smart money net-shorting = mild confirm), fade retail.

**Anti-stacks (do NOT combine):** funding extreme + liquidation flush both firing on the *same side you're trading into* is the classic squeeze setup — that's a hard veto, not two confirmations. Similarly OBI should never override the flush cooldown (books look one-sided *during* cascades).

---

## 4. ENDPOINT CHEAT SHEET (all verified free/no-auth, 2026-07-29)

| Data | Endpoint | Granularity / cost | Poll cadence |
|---|---|---|---|
| Taker buy vol per bar | `GET /fapi/v1/klines` field idx 9 | 1m, already fetched | free (existing) |
| Taker buy/sell ratio | `GET /futures/data/takerlongshortRatio?period=5m` | 5m snapshots, 30d | every 5 min |
| OI live | `GET /fapi/v1/openInterest` | real-time, weight 1 | every 60s/pair |
| OI history | `GET /futures/data/openInterestHist?period=5m` | 5m, 30d | startup seed |
| Funding (live premium) | `GET /fapi/v1/premiumIndex` | real-time, weight 1 | every 60s (batch: omit symbol → all pairs, one call) |
| Funding history | `GET /fapi/v1/fundingRate` | 8h settles | hourly |
| Retail L/S accounts | `GET /futures/data/globalLongShortAccountRatio?period=5m` | 5m, 30d | every 5 min |
| Top-trader L/S positions | `GET /futures/data/topLongShortPositionRatio?period=5m` | 5m, 30d | every 5 min |
| Order book | `GET /fapi/v1/depth?limit=50` | real-time, weight 2 | every 60s/pair (optional) |
| Liquidations | WS `!forceOrder@arr` | 1/sec/symbol max | optional; use OHLCV+OI proxy instead |

Budget: 15 pairs × (klines + openInterest + shared premiumIndex) ≈ 31 weighted calls/min against a 2,400/min limit — trivial. `/futures/data/*` endpoints are stricter (rate-limited separately, 5m data): fetch them on a 5-minute wheel, ~3 calls/pair/5min = fine.

## 5. Key sources
- Vafin (2026), *Order-Flow Imbalance and Short-Horizon Return Predictability in Crypto* — SSRN 6938742
- *Microstructure alpha* — Frontiers in Blockchain (2026), 5-min forward-return feature stability
- Liu/Maynard/Tsiakas (2025), *Order Flow and Cryptocurrency Returns* — EFMA
- Kurihara & Matsumoto (2026), *Price Transmission from Bitcoin to Altcoins* — Asia-Pac Fin Markets (open access)
- *The Quarter-Hour Effect* (2026) — arXiv 2607.09426 (Binance perps, boundary order flow)
- *When Does Order Flow Matter?* — arXiv 2607.09230 (L2 state dependence)
- Anderson (2023), BTC→ADA tick lead-lag (16–118 s) — IMFI
- JEDC (2024), *Cross-cryptocurrency return predictability* (5–13 min rebalancing)
- Yellow Research (2025), funding-rate extremes & the Oct-2025 cascade (FTI data); Zipmex funding guide (2026)
- CryptoCred (2023), *Comprehensive Guide to Crypto Futures Indicators* (OI/CVD/liquidation canon)
- CoinQuant (2025/26) BTC VWAP backtest (59% WR caveats); TradeAlgo VWAP band stats (61–63% 2σ reversion)
- Concretum/SFI RP 25-80 (2025), BTC intraday trend seasonality; IREF 2024 intraday periodicity
- Li et al. (2020) & Financial Innovation (2021) & Univ. Southampton — round-number clustering (no post-level return edge)
- Negative results: SSRN 6701738 (perp alpha screening failure), SSRN 6566940 (backtest→live gap)
