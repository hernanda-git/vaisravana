# Killing the Arbitrage / Market-Making (arb/MM) Thesis — Hard Reasons, Then the Least-Bad Path

**Verdict:** The generic "I'll run a profitable arb/MM desk with a script + some capital" thesis is **dead for any sub-institutional player**. Not because the math is wrong, but because every edge it relies on is either (a) gated behind institutional tier requirements, (b) owned by an HFT latency arms race, or (c) a structural trap (adverse selection) that no amount of code escapes. The only survivable slice is *structural carry* (perpetual funding-rate arb) or *subsidized long-tail MM* — both with real minimum requirements and real residual risk.

---

## PART 1 — WHY THE THESIS DIES (hard reasons, with numbers)

### Kill 1 — The taker-fee wall (proven, not anecdotal)
A 2025 arXiv study ("The Market Maker's Dilemma: Navigating the Fill Probability vs. Post-Fill Returns Trade-Off") measures it directly: a taker-based strategy shows **pre-fee PnL of ~+1 bp per roundtrip**, but *"paying the taker fee on each leg of the roundtrip erodes its profitability completely."*
- Implication: any cross-exchange arb executed as **taker/taker** bleeds by construction. To be profitable you must be a **maker**.

### Kill 2 — Maker = adverse selection ("fill and be killed")
Same paper: maker orders enjoy low fee / rebate, but experience **negative instantaneous price drift and negative expected drift over longer horizons**. You get filled precisely when it's bad for you.
- The rebate **does not compensate** for post-fill losses. This is a structural property of resting liquidity, not a bug a better bot fixes.
- Implication: passive MM "rebate harvesting" is a losing game unless you also have (i) tier-1 rebates and (ii) sophisticated queue/inventory control — both institutional.

### Kill 3 — Cross-exchange arb is an HFT latency arms race
- Harvard / UZH studies (2017–2021): easy arb profits **collapsed**; within-country spreads are now **often <1%**, equalized by competition.
- CoinAPI (2024): crypto "high-frequency arbitrage" requires **sub-millisecond latency + co-located infrastructure** across *every* target venue.
- The prize: *"the prize for being fastest is capturing nearly the entire available spread; the second-fastest might get nothing."*
- Implication: a cloud-VPS / retail setup is **structurally last in line**. You are not early — you are the exit liquidity for the fastest firm.

### Kill 4 — Rebates are gated to $10M+ desks
- Binance top tier: ~1.5 bp taker / −0.5 to +0.5 bp maker — but requires **hundreds of millions $/mo volume + token holdings**.
- Retail/spot default: **10 bps per side, both sides.** Paybis/DWF: meaningful rebates need **$10M+ capital and hundreds of trades daily.**
- Implication: the rebate that *funds* MM is inaccessible to the thesis's assumed operator. You pay 10 bp to play a game where the edge is 1 bp.

### Kill 5 — Inventory & gap/liquidation risk
MM requires holding inventory. Gaps blow through stops; a perp leg needs margin, and **if not cross-margined, one-leg liquidation realizes the loss** while the hedge sits untouched.

### Kill 6 — Venue/custodial risk makes "risk-free" a lie
Withdrawals frozen, insolvency (FTX), API bans, clawbacks, jurisdiction shifts. Custodial crypto arb is **never risk-free** — the counter-party is the exchange.

### Kill 7 — Strategy decay
Any static edge compresses as entrants undercut. The edge is a moving target requiring continuous R&D, not a durable asset you "own."

### Kill 8 — Capital inefficiency
A 10 bp edge on $10k = **$1/trade**. Infra, monitoring, and tax overhead dwarf that at small size. The strategy only prints once notional is large — which re-triggers the tier gates above.

**Net:** the thesis fails on fee structure (Kills 1,4), microstructure (Kill 2), speed (Kill 3), and risk (Kills 5,6,7,8) simultaneously. No single fix recovers it.

---

## PART 2 — THE LEAST-BAD PATH

Ranked by survivability for a smaller operator (not a $10M HFT desk):

### Option A (core least-bad): Perpetual **funding-rate carry** (long spot / short perp, collect funding)
Why it's the least-bad:
- **Not a latency game.** Funding settles every 8h; you don't need to be fastest. The edge is *structural*, driven by persistently one-sided leverage demand (longs pay shorts in bull regimes) and the exchange's need for the mechanism.
- **Near delta-neutral** — price risk is hedged, so it's closer to true "arb" than directional MM.
- Documented (vendor-reported, treat as upper bound): ~**8–18% annualized** in stable regimes; **55–110%** in high-funding bull regimes; round-trip fee drag ~$15–30 on $5k notional.

### Option B (alternative for smaller capital): **Long-tail / newly-listed MM**
Make markets in illiquid or just-listed pairs where competition is thin and exchanges **subsidize** MM via rebate programs / listing incentives.
- Pros: weaker latency competition, fatter rebates.
- Cons: heavier adverse-selection + inventory risk on illiquid assets, exchange **delisting** risk. Higher variance than A.

**Recommendation:** pursue **A as the core**, keep **B** as a satellite only if you already clear A's minimums. Do **not** pursue cross-exchange latency arb or generic taker arb at all.

---

## PART 3 — MINIMUM REQUIREMENTS (for the least-bad path, Option A)

| # | Requirement | Why / hard floor |
|---|-------------|------------------|
| 1 | **Capital ≥ $10k–25k deployed** (absolute fee-negative floor ~$3k; practical floor $10k) | Round-trip fees ~$15–30 on $5k notional → <20% fee drag only above ~$10k. Below $2–3k you are net-negative after fees. |
| 2 | **Cross-margin account** on a top-tier venue (Binance/Bybit/OKX) | Prevents one-leg liquidation from realizing the loss while hedge sits open. |
| 3 | **Fee tier access** (VIP/volume maker rebate, or ≤0.02% futures taker) | Fee drag is the single biggest killer at small size (Kill 4). |
| 4 | **Automation + monitoring** | Funding flips every 8h; need auto-rebalance, margin alerts, drawdown halts. Manual is feasible but dangerous in volatility spikes. |
| 5 | **Risk caps** | Max notional/venue, max drawdown halt, **diversify across 2–3 venues** to cap single-exchange-death risk (Kill 6). |
| 6 | **Legal/tax structure** | Funding income is **ordinary income**; needs an entity + accounting. Not optional at scale. |
| 7 | **Operational security** | API keys (trade-only, no withdraw), withdrawal whitelist, 2FA, warm-wallet hygiene. |
| 8 | **Time** | Mostly monitoring, not full-time — but requires vigilance during volatility when funding spikes and liquidations cluster. |

### Residual risks that still apply (the path is least-bad, not safe):
- **Negative-funding regimes** (bear markets: shorts pay longs) — 2022 hurt many funding arbers; need a flip/exit rule.
- **Exchange insolvency** (FTX wiped funding arbers parked there) — hence multi-venue caps.
- **Gap liquidation** if margin is thin during a wick.
- **Edge compression** — 2025 saw +215% capital deployed into funding arb (Gate, vendor-reported) → expect yield decay.

---

## BOTTOM LINE
- **Kill it:** the generic arb/MM "script + capital" thesis fails on fees, adverse selection, latency, and venue risk at once. Don't build cross-exchange or taker arb.
- **Least-bad:** perpetual funding-rate carry (with long-tail MM as a satellite).
- **Minimum to even attempt it seriously:** ~$10–25k, cross-margin top-tier venue, fee-tier access, automation + hard risk caps, multi-venue diversification, and a tax/legal wrapper. Anything less is either fee-negative or exchanges-risk-concentrated to the point of inevitability.
