# Vaisravana Wave Engine — Comprehensive Code Review & Strategic Re-Evaluation

**Author:** Kira (agent review for val)
**Date:** 2026-07-29
**Scope:** Full data path review (feed.py → bias.py → scanner.py → manager.py → engine.py) + strategic reassessment of the entire approach vs. val's goal: *"grow the balance, low-latency real-time fast scalping, no matter win or loss; some arb bots buy and sell at once."*

This document is deliberately blunt. It is not a celebration. It is a diagnosis.

---

## 0. TL;DR (read this first)

The current bot is a **directional prediction bot that trades on indicators that lag the tape by minutes, on a $10 account, paying taker fees on both sides, with a 10-minute cooldown between trades.** It cannot and will not "grow the balance fast" because:

1. **It is a slow signal on a fast market.** Its edge (EMA cross + book pressure + flow) is recomputed from 1m/5m/15m candles. At best it reacts in seconds-to-minutes. HFT/arb bots react in microseconds. By the time this bot decides, the move is half over.
2. **You are right about the millions-of-bots problem.** Every retail bot on Binance reads the *same* Binance klines, the *same* EMA, the *same* RSI. When millions of bots see the same bullish cross, they buy together, the price spikes, then they all hit the same SL and sell together. The signal is *crowded to the point of being the price*. Directional TA on a public exchange is a shared hallucination.
3. **Fees eat it alive at this size.** Taker 0.04% × 2 sides = 0.08% per round trip. On a $5 notional that is ~$0.004/trade, but the bot opens ~50% of a $10 account per wave (min-notional clamp = $5). Over a session that is a steady 1% bleed per 10 trades. The fee-bleed fix (iter-9) removed *phantom* fees; the *real* fees are structural and unavoidable on taker fills.
4. **It does not have a positive expectancy.** Every measured run (run12–run16) shows avg_final_r near 0, win rate near a coin-flip, net PnL flat-to-negative before you credit the one green-tape window. There is no edge, only survival.

**The thing val intuitively reached for is correct: a "buy and sell at once" strategy (market-making / arbitrage / catch-order-flow imbalance) is the only class of strategy that can grow a small balance by *capturing the spread or a price dislocation*, independent of predicting direction.** The current engine is the wrong architecture for that. Below is the full reasoning and a concrete rebuild path.

---

## 1. Full Code Path Review (what the bot actually does)

### 1.1 Feed (feed.py) — the "real-time" claim, measured
- `FeedMux` opens **one** multiplexed Binance WS and subscribes to **8 streams × 15 pairs = 120 streams** on a single socket. That is a lot for one TCP connection; Binance WS is fine with it but the *read loop is single-threaded async* — every message goes through `parse_ws_message` then `on_tick`. Fine for throughput, but:
- **The decision latency is not the WS latency — it is the indicator latency.** `read_bias()` blends `ema_15m vs ema_1h` (line 118-119) and `price vs ema_15m`. These EMAs are seeded from **15m and 1h candles**. A 15m EMA only meaningfully moves when a new 15m candle prints, which happens **every 15 minutes**. So the "real-time" bot's directional bias is, in practice, a 15-minute-smoothed signal. The aggTrade ticks update `ema_15m` per tick (line 146) but that EMA barely twitches within a candle.
- **REST poll fallback drives the bot when WS is weak** (lines 285-376). It polls `bookTicker` every **5 seconds** and refetches 15m/1h klines every 60s. On REST-only mode the *entire decision cadence is 5 seconds*, and the context is 15-minute candles. That is not scalping. That is a slow swing bot pretending to be fast.
- `tick.ts` is the exchange timestamp but `signal_age = time.time() - tick.ts` (line 148) is used for recency decay with a 300s half-life — so a 5s-stale REST tick is treated as ~fresh, masking the real staleness.

**Verdict:** The feed is competently built but the *signal it feeds* is minute-scale. Calling this "low-latency real-time scalping" is inaccurate. It is low-latency *data* on a high-latency *decision*.

### 1.2 Bias (bias.py) — the signal
- `read_bias()` = 40% mtf_ema (trend) + 25% flow_delta + 20% book_pressure + 10% risk_regime + 5% breadth.
- `book_pressure` (line 80-94) is derived from `bid/ask` distance on a `@bookTicker` event — but `@bookTicker` only gives **best bid/ask price**, NOT size. The code itself notes "Without size, use price distance" (line 91). So "book pressure" is actually just `(mid-bid)/spread` — a near-constant ~0 on a tight spread. **It carries almost no real information.** This is a fake signal component.
- `flow_delta` comes from `ctx.flow_delta` — but grep shows `flow_delta` is never actually populated anywhere in the reviewed path (no `ctx.flow_delta =` assignment found). **It is permanently 0.** Another fake component.
- `breadth` (`ctx.alt_breadth`) — likewise never set in the observed code. **Permanently 0.**
- So the *entire* bias reduces to: `0.40 × mtf_ema + 0.25 × 0 + 0.20 × ~0 + 0.10 × risk_regime + 0.05 × 0` = **40% EMA cross + 10% risk_regime.** A two-component lagging indicator.

**Verdict:** 65% of the "conviction" engine is dead weight (unpopulated fields). The live signal is an EMA cross with a tiny risk overlay. This is the most basic possible trend-following signal — the exact thing millions of bots run, and the exact thing that gets crowded.

### 1.3 Scanner (scanner.py) — the entry
- `scan()` checks bias direction, computes `detect_structure()`, runs `wave_quality_pass`, returns a Candidate. It is a thin wrapper. No problem here except it inherits the weak bias.

### 1.4 Gate (gate.py) — selectivity
- Floors: `MIN_BIAS_STRENGTH 0.30`, `CONF_ENTRY_FLOOR 0.12`, `ADX_FLOOR 18`, `STRUCTURE_SCORE_FLOOR 0.12`.
- These are *low* by design (iter-10 tried raising them and got 0 trades). Low floors = the bot trades on weak signals = it is a *noise trader* on flat tape. That is fine for survival but it is not edge.

### 1.5 Manager (manager.py) — sizing, exits, fees
- **Sizing is broken for a small account (the min-notional trap).** `notional = wallet.notional_for(price)` (line 132) computes `RISK_PCT(0.20) × balance = $2` intended, then line 160 clamps: `notion = max(min_notional=5, min(notion, balance))`. On a $10 account that forces **$5 notional per wave = 50% of the account**, 2.5× the intended risk. The "survival sizing" comment is wrong — it *over*-sizes relative to risk intent.
- **Leverage 3x** (line 141). With $5 notional that is $1.67 margin. Fine, but it means R is tiny and fees dominate.
- **Exits** (evaluate_exit): TP at 2×ATR (line 198), partial at +0.5R/0.9R, reversal at peak≥0.2R & live<0, hard loss-cut at -0.5R, bias flip, conf collapse, anchor hit, max_age 900s. This is a *reasonable* exit stack. The problem is the entries: the bot rarely reaches TP because the signal is weak and the window (900s) is short relative to 15m-candle smoothing.
- **Fees charged correctly now** (iter-9): `charge_open_fee` only after the wave is accepted (line 215). Good. But it is *taker* on both sides (paper_wallet fee_rate 0.0004). Real cost.

### 1.6 Engine (engine.py) — orchestration
- Warmup (iter-10): 90s no-op at start. Good hygiene.
- `on_tick` runs the full scan+open per (pair, side) every tick. With the live-dup guard (iter-9) this no longer fee-bleeds. Good.
- **Cooldown = 600s** (line 23). After any close, the same (pair, side) cannot re-enter for 10 minutes. On a 15m-candle signal that is reasonable, but it means the bot can do at most ~1 trade per pair per 10 min. **Max ~90 trades/hour across 15 pairs, but realistically ~8-16 in a session.** That is NOT high-frequency. It is low-frequency by construction.

---

## 2. The Core Strategic Error (and why val is right)

Val's instinct: *"if millions of users do bot trading and these millions of bots do the same, the price will go different."*

This is **correct and well-known in quant finance**. It is called:
- **Signal crowding** — when many agents trade the same signal, the signal becomes self-fulfilling in the short term (they move the price) then mean-reverts (they all exit together). Net: the latecomer (this bot, which reacts in seconds-minutes) buys the spike and sells the dump.
- **Adverse selection** — taker orders (this bot uses takers) always trade *against* someone with more information or lower latency. The maker earns the spread; the taker pays it. At 0.04% taker × 2 = 0.08% per round trip, the bot must be right *more than 0.08% of notional* just to break even on fees, before any edge.
- **Latency arbitrage** — the bots that win are the ones *inside the exchange* (co-located, maker orders, or directly reading the order book depth). A retail bot in a Docker container in Tencent Cloud, reading public klines, is at the **bottom** of the latency stack.

So a directional taker bot on a public signal is the *worst possible* architecture for "grow the balance fast." It is structurally a loser.

---

## 3. What Actually Grows a Small Balance (the "think different" part)

Val mentioned: *"some arbitrage bot do buy and sell at once."* That is the unlock. Three strategy classes that do NOT require predicting direction and DO capture microstructure edge:

### 3.1 Market-making / spread capture (the "buy and sell at once" idea)
- Post a **maker** bid and ask around mid. Capture the bid-ask spread. You do not predict direction; you earn the fee rebate + spread from whoever trades against you.
- Binance **maker fee = 0.02%** (vs taker 0.04-0.05%). At scale maker can even be negative (rebate). The bot would *earn* fees instead of paying them.
- Risk: inventory risk (price moves away from your quotes). Managed by skewing quotes, tight inventory caps, and fast cancellation.
- **This is the lowest-latency, highest-win-rate class available to a retail bot** — IF it can cancel/reprice fast enough. The current feed.py WS can support it; the signal logic must be replaced with a quote engine.

### 3.2 Triangular / cross-exchange arbitrage
- Exploit price differences of the same asset across venues or pairs (e.g. BTC/USDT vs ETH/BTC vs ETH/USDT). "Buy and sell at once" = atomic arbitrage, near-zero directional risk.
- Requires reading multiple order books and executing fast. On a single exchange triangular arb is thin but real; cross-exchange needs multiple WS connections.
- Win rate is effectively 100% on filled arbs (you only fill when the math is positive). The risk is *execution* (one leg fails, you're left with directional exposure) and latency (someone fills before you).

### 3.3 Order-flow imbalance / micro-structure scalping
- Read the **full depth** (not just best bid/ask — `depth20@100ms` or `diff.book` streams) and trade the *pressure*, not the EMA. When aggressive buy flow consumes the ask ladder, fade the move or ride the micro-sweep.
- This is still directional but operates on **sub-second** timescales where the millions-of-bots crowding is *not* yet priced in (it takes them seconds to react). It is the closest legitimate "real-time scalping" to what val wants.
- Requires `depth` streams (currently NOT subscribed — only `bookTicker` best bid/ask, which has no size) and a per-tick decision loop with <100ms reaction.

### 3.4 What the current bot is NOT
It is none of the above. It is a **lagging trend-follower on a taker fill**. That is the one strategy guaranteed to lose to the crowd.

---

## 4. Latency & Reality Budget (honest numbers)

| Layer | Current bot | What "fast scalping" needs |
|---|---|---|
| Data | Binance WS, 120 streams, single socket | WS + depth streams, possibly multiple sockets |
| Signal recompute | 15m/1h EMA (updates every 15-60 min) | per-tick from order book |
| Decision cadence | per tick (good) but on stale signal | per tick on fresh signal |
| Order type | **taker** (pays 0.04% ×2) | **maker** (earns/cheap 0.02%) |
| Reaction time | seconds (Python asyncio, single proc) | <100ms desirable |
| Trade frequency | ~1 per pair per 10 min (cooldown) | 10-100s per pair per min (MM) |
| Account size | $10, 50% per wave (clamp bug) | small ok for MM (spread capture) |
| Win rate target | ~50% (coin flip) | 55-70% (MM spread) or ~100% (arb fills) |

The single biggest lever: **switch from taker to maker.** It flips the fee sign and removes the need to "be right" directionally.

---

## 5. Concrete Rebuild Path (if val wants to actually pursue growth)

This is a proposal, not yet code. Three phases:

**Phase A — Make the current bot honest (1 day, low risk)**
- Fix the min-notional clamp so it sizes to true risk (e.g. notion = min($2 intended, balance, but never >20% of balance). Actually for MM you want small.)
- Populate `flow_delta` and `breadth` OR delete them from the blend (stop pretending).
- Subscribe to `@depth20` streams and compute *real* book imbalance (with size).
- Switch fills to **maker** where possible (post limit at touch, cancel if not filled in X ms).

**Phase B — Market-maker core (the "buy and sell at once" engine)**
- Replace `scanner`/`bias` entry logic with a `quoter`: for N liquid pairs, post maker bid/ask at ±spread around mid. Track inventory. Skew quotes to flatten inventory. Cancel on adverse move.
- Use depth streams for mid + queue position. Use the existing `FeedMux` + `paper_wallet` (extend wallet to track maker rebates).
- This captures spread, earns maker fees, win rate dominated by spread capture (high), directional risk small and hedged by inventory skew.

**Phase C — Arb layer (optional, higher complexity)**
- Triangular arb scanner across the 15 pairs reading all depth books; fire only when (buy+sell+sell) nets positive after fees. Maintain both legs atomically.
- Higher latency bar; start on single-exchange triangular before cross-exchange.

**What NOT to do:** keep tuning EMA floors, TP distances, warmups. Those optimize a losing strategy. The edge is not in the parameters; it is in the *strategy class*.

---

## 6. Risk / catastrophic-loss assessment (per session objective)

- Current bot: capped loss per wave at -0.5R (iter-8), max 8 concurrent waves, wallet halts at $0. Catastrophic loss is *structurally prevented* — good. But "no catastrophic loss" ≠ "grows." It will grind to ~$0 slowly via fees if the signal has no edge (which it doesn't).
- A maker/MM bot has *inventory risk*: if it posts bids into a falling knife, it gets filled and the price keeps dropping. Must cap inventory and cancel fast. This is the new catastrophic-loss surface to design against. The existing `KillSwitch`/`ModeGuard` infra can be reused.

---

## 7. Recommendation

1. **Stop iterating on the directional taker bot as a "growth" engine.** It is a survival demo, and a good one (fees fixed, warmup, footer, safe). Keep it as the *paper baseline / risk sandbox*.
2. **Build a maker/market-making module** (`wave/mm.py`) as the actual growth engine, reusing `FeedMux` (add depth streams), `paper_wallet` (add maker rebate accounting), and the risk guards. This is the legitimate interpretation of val's "buy and sell at once."
3. **Treat the autonomous-loop cron as a parameter tuner for the MM module**, not the taker bot.
4. **Be honest in notifications**: the taker bot's "win rate" is a coin flip; an MM bot's "win rate" is real spread capture.

The goal "grow the balance no matter win or loss" is only achievable by **earning the spread / rebate**, not by predicting the crowd. Val already knew this. The code should reflect it.

---

*End of review (Part A). Pause the autonomous cron (done) before any rebuild so measurement is clean.*

---

# PART B — Enriched Research (market microstructure, grounded in sources)

This section supersedes the earlier "just switch to maker and you win" suggestion.
Further research shows that advice is **wrong for a naive bot**. The truth is
more interesting and more honest.

## B.1 The Market Maker's Dilemma (empirical, Binance, 2025)

A 2025 paper (Shestopaloff; Oxford-Man + Queen Mary; arXiv 2502.18625),
*Navigating the Fill Probability vs. Post-Fill Returns Trade-Off*, studies
exactly the strategy we considered, on exactly our venue (Binance). Findings:

- **Fill probability is NEGATIVELY correlated with post-fill returns.** The
  more likely your resting maker order is to be filled, the worse the price
  moves for you after. This is textbook **adverse selection**: you get filled
  when an informed trader wants the other side.
- **The naive MM strategy loses ~0.44 bp per round-trip net of rebates**, at
  high frequency, with a poor Sharpe. The author's words: *"the naive market
  making strategy is thus a recipe for poverty — heaven help the starry-eyed
  novice traders, fresh from academia, who, seduced by maker rebates, attempt
  to implement this strategy in practice."*
- **On Binance the spread is virtually always ONE TICK wide**, except
  fleetingly after price changes, whereupon there is *fierce competition to
  close the spread immediately*. So there is almost no spread to capture; the
  rebate is the only edge, and it is tiny.
- **Adverse selection increases with opposite-side queue size** (Q_top^opp).
  The paper quantifies post-fill markout returns by queue regime — they are
  predominantly NEGATIVE across all regimes. This is the signal that *separates*
  a smarter MM (queue-aware, flow-aware cancellation) from the naive one.

**Implication for us:** posting a dumb bid/ask and hoping is a losing game
even on maker fees. The edge, if any, is in *when to post, where in the queue,
and when to cancel* — i.e. reading order-flow imbalance and queue position.
That is a different, harder bot than "buy and sell at once."

## B.2 Maker rebates are not free money at retail scale

Binance spot maker rebate tiers (official fee schedule):
- VIP2: -0.0040% (requires 0.15% weekly maker-volume share, or ~$ volume)
- VIP3: -0.0060% (0.50% maker-volume share)
- VIP4: -0.0080% (1.00% maker-volume share)

For **USD-M Futures** (our market), regular maker fee is **0.02%** (no rebate
at retail); taker 0.04% (0.05% without BNB). A $10 paper account trading a few
hundred $/day qualifies for **none** of the rebate tiers. So:
- Our bot pays 0.04% taker × 2 = 0.08%/RT.
- A maker-based bot at our size pays 0.02% × 2 = 0.04%/RT but earns **$0 rebate**.
- The maker bot saves 0.04%/RT in fees vs the taker bot — real, but it does
  NOT flip the strategy positive, because the 0.44 bp/RT adverse-selection
  drag (B.1) dwarfs the fee saving.

**Conclusion:** the fee side is a second-order effect. The first-order effect
is adverse selection, which punishes *both* taker and naive maker.

## B.3 Why directional TA bots lose (the millions-of-bots problem, quantified)

val's intuition — *"if millions of bots do the same, the price goes different"*
— is exactly the academic concept of **signal crowding** and **predatory
trading**:
- Every retail bot reads the same Binance klines → same EMA/RSI → same
  bullish cross. They buy together; the aggregate buy *is* the price move;
  then the same cross on the downside triggers synchronized selling.
- HFT/predatory algorithms *detect* this flow (they see the order book the
  bot only sees as best bid/ask) and **trade ahead / pick off** the slow
  participants (Demos "Hunting Whales"; layering/spoofing literature).
- Result: the late, slow, public-signal taker (our bot) systematically fills
  on the wrong side of the move. This is *exactly* the adverse-selection
  mechanism in B.1, just for trend-following instead of MM.

So the directional bot is not "unlucky" — it is *structurally selected
against*. The crowd is the price, and the bot is always a step behind it.

## B.4 What actually has edge (and what doesn't), for a $10 retail bot

| Strategy | Edge source | Verdict at our scale |
|---|---|---|
| Directional taker (current) | predict crowd move | **Loses** (adverse selection + lag + fees) |
| Naive maker MM (post both sides) | spread + rebate | **Loses** (~0.44 bp/RT adverse selection > rebate) |
| Queue/flow-aware MM | read depth + cancel before adverse fill | **Possible edge**, needs depth streams + <100ms loop |
| Triangular/cross-exchange arb | price dislocation across venues/pairs | **Real edge** where it exists, but thin + latency-bound |
| Latency arb / co-located maker | speed inside exchange | **Impossible** for us (Tencent Cloud, no co-lo) |

The only strategies with a *structural* (not just skill) edge for a non-co-lo
retail bot are **(a) cross-exchange / triangular arbitrage** (exploits real
price differences, not predictions) and **(b) flow/queue-aware execution**
(exploits the *same* microstructure the HFTs use, but from outside — possible
only with full depth data and fast cancellation).

## B.5 Binance depth streams (what we are MISSING for any of this)

Our `feed.py` subscribes to `aggTrade`, `bookTicker` (best bid/ask, **no
size**), `markPrice`, and klines. For MM or flow trading we need:
- `<symbol>@depth<levels>` or `<symbol>@depth` (full diff book) — the
  `diff_book_depth` / `depth` WS streams. These deliver level-2 updates at up
  to **100ms** frequency (`@depth@100ms`). The academy tutorial shows the
  snapshot+diff resync pattern.
- With depth we can compute **real order-flow imbalance** (signed size per
  side) and **queue position** — the actual signals B.1 says separate good
  fills from bad.
- Latency reality: a single multiplexed WS in Tencent Cloud to
  `wss://fapi.binance.com` has RTT of tens of ms. That is fine for MM on
  liquid pairs (where HFTs also operate at ~ms), but we will *lose* the
  front-of-queue race to co-located firms. Acceptable for a learning bot;
  not for profit at scale.

## B.6 Revised recommendation (honest)

1. **The current directional taker bot should stay a paper risk-sandbox.**
   It is safe and well-built; it is not a growth engine. Stop expecting it to
   grow.
2. **Do NOT naively "switch to maker."** Research proves that loses too.
3. **If we want real edge, build ONE of:**
   - **Triangular arb scanner** across the 15 pairs we already track (single
     exchange, atomic, ~100% fill win rate when math is positive). Lowest
     latency bar, clearest edge, matches val's "buy and sell at once."
   - **Flow/queue-aware MM** (Phase B/C from Part A) — but only after adding
     `@depth@100ms` streams and a cancellation policy informed by B.1's queue
     regimes. This is the hard, legitimate "real-time scalping" path.
4. **Reframe the goal.** "Grow the balance no matter win or loss" is only
   achievable by *earning a structural spread or rebate or dislocation*, not
   by predicting the crowd. The bot must become a *liquidity/arb* bot, not a
   *prediction* bot.
5. **Be honest in notifications** about expected expectancy: a flow-aware bot
   wins on fill *quality*, not on a 55% coin-flip.

## B.7 Concrete next-step spec (if val approves)

- Add `depth_streams` to `FeedMux`: `<pair>@depth@100ms` for N liquid pairs.
  Maintain a local book (snapshot + diff resync per Binance academy pattern).
- Prototype `wave/arb.py`: read all 15 pairs' mid from the local books, scan
  for triangular cycles (A→B→C→A) where the product of implied prices > 1 +
  fees + epsilon. Fire only when positive. Start paper.
- Keep `paper_wallet` but add a `maker_rebate` field (0 at our tier) so the
  accounting is honest about rebate reality.
- Reuse `KillSwitch`/`ModeGuard` for inventory/balance limits in the arb bot
  (catastrophic-loss surface = a leg fails and leaves directional exposure).

*This research does not yet change deployed code. It changes the STRATEGY
direction. Pending val's go-ahead before any rebuild. Cron remains paused.*

---

## Appendix — Sources (for traceability)

- Shestopaloff (2025), "Navigating the Fill Probability vs. Post-Fill Returns
  Trade-Off", arXiv:2502.18625 — Market Maker's Dilemma, Binance one-tick
  spread, adverse selection by queue size, naive MM loses 0.44bp/RT.
- Binance official fee schedules (futures 0.02% maker / 0.04% taker retail;
  spot maker rebate -0.004%..-0.008% only VIP2-4).
- Binance Academy, "Local Order Book Tutorial" — depth snapshot + diff resync.
- Binance Developers docs — `<symbol>@depth<levels>` / `<symbol>@depth` WS
  streams, 100ms frequency.
- quantt.co.uk / paybis.com MM guides — spread capture, inventory risk,
  rebate reality for retail, "speed beats rebates for retail."
- Demos "Cracks in the Pipeline" — HFT predatory trading, hunting whales,
  flash-crash amplification.

*End of Part B.*
