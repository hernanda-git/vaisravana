# Pro-desk techniques a naive 1-min perp scalper lacks — prioritized for the fee-bleeding $10 bot

Context: Binance USDT-perp paper bot, 15 pairs, 1-min scalps, 0.04% taker both sides (8 bps round trip),
106 trades/10h, WR 45%, gross ≈ breakeven, fees -$8.40. TP hit 9/106; most exits = MAXHOLD timeout.
Diagnosis: the strategy has ~zero net edge per trade (< 8 bps average move captured) and trades ~10x too often.
Everything below attacks either (a) cost per trade, (b) trades per hour, or (c) captured move per trade.

---

## 1. Post-only (maker) limit entries — HIGH impact, MEDIUM difficulty
Real desks almost never cross the spread on entry for a scalp; they rest post-only limits at or inside the
touch. On Binance USDT-M VIP0 the fee ladder is maker 0.02% / taker 0.05% (0.018/0.045 with BNB) — flipping
entry from taker to maker cuts entry cost ~60%, and combined with maker exits (TP as post-only limit) the
round trip drops from ~8 bps to ~4 bps or less; some venues pay maker rebates (fee becomes income). For this
bot: place entry as a post-only limit at best bid (long) / best ask (short) with a 2–5s time-in-force, cancel
if unfilled. Bonus: unfilled = the market ran away without you, which disproportionately removes chase-y,
adverse-selected entries. Caveat (Market Maker's Dilemma, arXiv 2502.18625): passive fills are adversely
selected — you get filled most easily when price is about to go against you — so pair with the spread/imbalance
filters below. Keep the SL as a stop-market (safety > fee) but make the TP a resting maker limit.

## 2. Fee-aware expected-value gate — HIGH impact, LOW difficulty (pure additive gate)
Rule used by every professional engine: don't send the order unless E[move] > k × (round-trip fee + spread + slippage),
k ≥ 2–3. Concretely: expected favorable move proxy = confidence × ATR-projected move over intended hold;
required threshold at taker/taker = 8 bps + spread_bps + ~2 bps slip ≈ 12–15 bps, ×2 safety ≈ 25–30 bps
minimum expected move on a 1-min hold. Most 1-min signals on majors can't clear that — which is the point:
this single gate would have vetoed the majority of the 106 trades that netted ~0 gross. Cheapest, highest-ROI
change available; implementable as one `if` before order submission.

## 3. Fix the TP/hold geometry (MFE-based) — HIGH impact, LOW difficulty
9/106 TP hits + MAXHOLD-dominant exits is a textbook broken-geometry signature: TP is placed beyond the move
the strategy actually generates within the hold window. Log MFE/MAE per trade (standard prop-desk practice —
see TradesViz/Trademetria MFE-capture methodology): set TP at ~the 60–70th percentile of historical MFE
(so 30–40% of trades can reach it), not at a fixed R multiple fantasy. If median MFE is 0.4R, a 1.5R TP will
never hit and every trade decays into a timeout that pays full fees for zero edge. Alternatively scale hold
time so hold ≥ time-to-median-MFE-peak. This converts fee-paying timeouts into paid winners without touching
the entry logic.

## 4. Trade-frequency throttle / quality-over-quantity — HIGH impact, LOW difficulty
106 trades in 10h on a $10 account is churn, not trading. Desks cap trades per unit time and per pair and
force the engine to take only the top-decile signals. Concrete: global cap ~2–4 trades/hour, per-pair cap
~1/hour, and raise the confidence threshold until daily trade count falls ~70–80%. With gross ≈ breakeven,
fees scale linearly with count, so cutting count 75% cuts the bleed 75% while (if the confidence score is even
weakly informative) keeping the best-EV trades. The tv-hub scalping-cost analysis (2026) makes the same point:
after taker fees a scalper needs implausible win rates; the only free lever is fewer, better trades.

## 5. Spread + liquidity filter per pair — HIGH impact, LOW difficulty
Skip any signal where current spread_bps > ~1–2 (majors) or > ~3–5 (alts), and drop pairs whose typical spread
is a large fraction of expected move. On a 1-min scalp the spread is paid twice and is pure cost, same as fees.
15 pairs almost certainly includes thin alts where spread + fees exceed any 1-min edge. Also require minimum
top-5-level book depth vs your order size. This is a data-feed + one-comparison change and synergizes with #1
(passive entries need tight, deep books to fill without adverse selection).

## 6. Volatility-regime gate (ATR percentile) — HIGH impact, LOW difficulty
Only trade when the move budget exists: require 1-min ATR (or realized vol) above its ~60–70th rolling
percentile for that pair. In low-vol chop the expected move can't clear costs (see #2) and momentum signals
are noise; in expanding vol the same signal has 2–4x the follow-through. Counterpart rule some desks use:
if you must trade low-vol regimes, flip to mean-reversion logic there and momentum only in high-vol — regime-
conditional signal selection is one of the most robust "unusual" tricks (trend signals invert into fade signals
in compression regimes).

## 7. Session/time-of-day filter — MEDIUM-HIGH impact, LOW difficulty
Crypto has strong intraday seasonality: volume/volatility peak in the Europe–US overlap (~13:00–16:00 UTC) and
around US equity open/close; 00:00–03:00 UTC late-Asia hours are thin, high-impact, mean-reverting (Talos
market-impact study; Time-of-Day Periodicities in Bitcoin, IRFA; Quantpedia overnight-session work; Concretum/
SSRN 5209907 shows intraday trend-following works best from Sunday 19:00 ET through Monday and worst US Sunday
morning). For a momentum-ish 1-min bot: whitelist ~12:00–21:00 UTC weekdays, ban weekend chop and 00:00–06:00
UTC unless in mean-reversion mode. Fewer trades, better trades — stacks multiplicatively with #4 and #6.

## 8. Breakeven stop after +0.5R & partial TP — MEDIUM impact, LOW difficulty
Standard exit science: once open PnL ≥ ~0.5R (calibrate to median winner MFE), move SL to entry ± fees
("breakeven-plus-costs"), and optionally close 50% at ~0.5–0.7R letting the rest run to TP. This directly
attacks the pattern where MAXHOLD exits round-trip a winner back to flat and still pay 8 bps. Warning from
MFE-capture research: too-tight trailing extracts only ~20–35% of available MFE — trail by ~1 ATR, not ticks.

## 9. Funding-rate awareness — MEDIUM impact, LOW difficulty
Three parameter-level uses on Binance perps (funding every 8h, applied at 00/08/16 UTC): (a) never hold a
position through a funding timestamp on the paying side — for a scalper this is a free rule (close or don't
enter in the last ~10 min if funding is against you); (b) tiebreaker/skew: when funding is strongly positive
(crowded longs), require higher confidence for longs and lower for shorts — extreme funding is a documented
contrarian/positioning signal (MetaMask perp-funding guide; Richey May 2024 "Funding Rate Factor": high funding
precedes volatility and marks crowded positioning); (c) on ~zero-edge signals, prefer the side that *collects*
funding. Impact is capped for a fast scalper (most 1-min holds never touch a funding event) but the crowding
signal costs nothing.

## 10. Post-large-candle cooldown (adverse-selection avoidance) — MEDIUM impact, LOW difficulty
Desks avoid initiating right after an outsized move: after a 1-min candle > ~3× ATR, block new entries on that
pair for 2–5 minutes. Immediately post-spike, spreads blow out, books thin, and price is dominated by
liquidation cascades and mean-reverting overshoot — exactly where naive momentum entries buy the top of the
wick and pay maximum spread. Related HFT concept: don't be the liquidity that informed flow just ate
(adverse-selection literature; Changelly HFT primer lists adverse selection as market-making risk #1).

## 11. Loss-streak cooldown / anti-cluster — MEDIUM impact, LOW difficulty
After N consecutive losses (N=2–3) globally or per pair, pause that scope for 15–30 min; after a daily loss
limit (e.g., -3% of equity net of fees), halt for the day. Losses cluster in regimes the strategy doesn't fit;
a naive bot re-fires the same broken signal into the same regime every minute, converting one bad read into
five fee-paying losers. This is the systematic version of a prop desk's tilt control and is the cheapest
drawdown-flattener available. (Bot already excludes pairs by rolling WR — this adds the time dimension.)

## 12. Volatility-targeted position sizing + fractional Kelly — MEDIUM impact, MEDIUM difficulty
Size = (risk budget per trade) / (ATR-based stop distance), scaled so each trade risks a constant fraction
(vol targeting, as used in the Concretum benchmark: constant-vol exposure roughly doubled Sharpe vs raw).
Then cap at ~¼ Kelly computed from rolling WR/payoff *net of fees* — at WR 45% with the current payoff
profile, net Kelly is negative, which correctly says "bet zero": Kelly-gating doubles as an edge-existence
check. Prevents thin-alt positions from carrying more real risk than BTC positions and stops the bot from
betting when its own stats say it has no edge.

## 13. Order-book imbalance entry confirmation — MEDIUM impact, MEDIUM-HIGH difficulty
Queue/order-flow imbalance is one of the few robust short-horizon predictors (Cont–Kukanov–Stoikov: near-linear
OFI→price-change relation; Gould & Bonart: queue imbalance predicts next tick; confirmed in crypto LOBs,
arXiv 2506.05764). Use top-5-level depth imbalance ρ = (B−A)/(B+A) as a confirmation gate: only take longs
when ρ > +0.2, shorts when ρ < −0.2. For passive entries (#1) it also warns of adverse fills — being joined to
a huge queue opposite a strong imbalance is how passive orders get run over. Requires a depth websocket, so
harder than the pure-parameter gates, but it's the highest-quality *new signal* on this list.

## 14. Weak-signal inversion / breakout-failure fade — LOW-MEDIUM impact, MEDIUM difficulty (experimental)
Two counterintuitive tricks with real precedent: (a) if a signal bucket has stable WR < 45% over a large
sample, its inverse has > 55% — before deleting a consistently-losing signal, test trading its mirror
(works only if the loss isn't fee/spread-caused); (b) 1-min breakouts in crypto chop fail most of the time —
trading the *failure* (entry when price re-crosses back through the broken level, stop beyond the wick) puts
you with the mean-reversion majority and gives structurally tight stops. Fits the existing engine as a new
entry type rather than a rewrite, but needs paper A/B validation before trusting it.

## 15. Per-pair net-expectancy scoreboard (fee-inclusive) — LOW-MEDIUM impact, LOW difficulty
Upgrade the existing WR-based pair excluder to rank pairs by rolling *net expectancy per trade* (gross PnL −
fees − spread cost, per trade) and by MFE-capture rate. WR alone is misleading at 45% WR with asymmetric R;
a pair can have 55% WR and negative net expectancy after its spread. Trade only the top ~5 of 15 pairs each
day. Data the bot already logs; one aggregation function.

---

### Stacking estimate for this bot
#2 + #4 + #5 + #6 + #7 cut trade count ~75–85% at roughly constant gross edge → fee bleed from ~$8.4/10h to
~$1.5–2/10h. #1 halves the remaining per-trade cost. #3 + #8 convert timeout-flats into small realized winners.
That combination moves net expectancy from ≈ −8 bps/trade to plausibly positive before any new alpha (#13, #14)
is added. Priority order for implementation: 2, 4, 5, 3, 6, 7, 1, 8, 11, 9, 10, 15, 12, 13, 14.

### Key sources
- Binance USDT-M fee schedule: maker 0.02% / taker 0.05% VIP0, 10% BNB discount (binance.com/en/fee/futureFee)
- "The Market Maker's Dilemma: Fill Probability vs Post-Fill Returns" — arXiv 2502.18625 (queue position, adverse selection of passive fills)
- Cont, Kukanov, Stoikov — "The Price Impact of Order Book Events" (OFI linearity); Gould & Bonart — queue imbalance as one-tick predictor
- Talos, "What is the Best Time to Trade BTC" (intraday market-impact profile, 11:00–13:00 UTC cheapest, 00:00–03:00 UTC worst)
- Quantpedia, "How To Profitably Trade Bitcoin's Overnight Sessions" (Nov 2024); Concretum/SSRN 5209907, intraday trend seasonality (2025)
- Richey May Market Intel (Jun 2024), "The Funding Rate Factor"; MetaMask perp-funding strategies guide
- TradesViz / TradersSecondBrain MFE-MAE guides (TP placement from MFE percentiles, MFE capture rate 35–55% typical retail)
- tv-hub.org "Best Crypto Scalping Bots 2026" (fee math: taker scalping needs ~92% WR on spot; maker futures ~57%)
