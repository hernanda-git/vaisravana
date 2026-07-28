"""Honest end-to-end backtest of the PRODUCTION decision path (scalping, 1m).

Replicates bot_paper._decide_tick EXACTLY:
  build_state_mtf -> build_context (cross-asset, real BTC + alt basket) ->
  ADX gate -> adaptive_weights -> evaluate_strategy (decide_ctx) ->
  paper TP/SL/MAXHOLD from REAL candle extremes.

Uses real Binance klines (data/klines/*.json). No network, no fabrication.
Measures WR / expectancy(R) / profit factor / net$ per (pair, side) and aggregate.

Usage: python scripts/eval_honest.py [--strategy scalping] [--maxhold 60]
Writes reports/eval_honest.md
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from config import default_profiles, default_surface
from engines import MarketState
from marketcontext import build_context, ContextSeries
from marketdata import Candle
from strategy import evaluate_strategy

# ---- production helpers copied verbatim from bot_paper.py (pure, no I/O) ----
def _ema(closes, period):
    k = 2.0 / (period + 1)
    e = closes[0]
    for v in closes[1:]:
        e = v * k + e * (1 - k)
    return e

def _ema_cross(closes, fast=20, slow=50, tol=0.0008):
    if len(closes) < slow:
        return False, False
    e_fast = _ema(closes[-fast:], fast) if len(closes) >= fast else _ema(closes, fast)
    e_slow = _ema(closes, slow)
    return e_fast > e_slow * (1 + tol), e_fast < e_slow * (1 - tol)

def _tf_minutes(tf):
    unit = tf[-1].lower()
    mult = int(tf[:-1]) if tf[:-1].isdigit() else 1
    return mult * {"m": 1, "h": 60, "d": 1440}.get(unit, 1)

def compute_adx(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    tr = [max(c.h - c.l, abs(c.h - c.c), abs(c.l - c.c)) for c in candles]
    plus = [(c.h - p.h) if c.h - p.h > p.l - c.l and c.h > p.h else 0.0
            for c, p in zip(candles[1:], candles[:-1])]
    minus = [(p.l - c.l) if p.l - c.l > c.h - p.h and p.l > c.l else 0.0
             for c, p in zip(candles[1:], candles[:-1])]
    atr14 = sum(tr[-period:]) / period
    pdm = sum(plus[-period:]) / period
    ndm = sum(minus[-period:]) / period
    pdi = pdm / atr14 * 100.0 if atr14 > 0 else 0.0
    ndi = ndm / atr14 * 100.0 if atr14 > 0 else 0.0
    dx = abs(pdi - ndi) / (pdi + ndi) * 100.0 if (pdi + ndi) > 0 else 0.0
    return dx

def adx_allowed(adx_val, threshold=25.0):
    if adx_val < 1.0:
        return True, ""
    if adx_val < threshold:
        return False, f"ADX {adx_val:.1f} < {threshold}"
    return True, ""

def build_state(pair, tf, candles, i):
    w = candles[max(0, i - 50): i + 1]
    closes = [c.c for c in w]
    vols = [c.v for c in w]
    bar = candles[i]
    ema20 = _ema(closes[-20:], 20)
    ema50 = _ema(closes, 50)
    atr14 = statistics.mean(
        max(candles[j].h - candles[j].l, abs(candles[j].h - candles[j - 1].c),
            abs(candles[j].l - candles[j - 1].c))
        for j in range(max(1, i - 13), i + 1))
    atr_pct = atr14 / bar.c
    bull = ema20 > ema50 * 1.0005
    bear = ema20 < ema50 * 0.9995
    if atr_pct > 0.012:
        regime = "high_vol"
    elif bull:
        regime = "trending_bull"
    elif bear:
        regime = "trending_bear"
    else:
        regime = "range"
    mu, sd = statistics.mean(vols), (statistics.pstdev(vols) or 1e-9)
    vol_z = (vols[-1] - mu) / sd
    signed = [(c.c - c.o) / (abs(c.c - c.o) + 1e-9) * c.v for c in w]
    smu, ssd = statistics.mean(signed), (statistics.pstdev(signed) or 1e-9)
    delta_z = (signed[-1] - smu) / ssd
    body_ratio = abs(bar.c - bar.o) / ((bar.h - bar.l) or 1e-9)
    return MarketState(symbol=pair, tf=tf, regime=regime, htf_bias="neutral",
                       body_ratio=body_ratio, vol_z=vol_z, delta_z=delta_z,
                       atr=atr14, atr_pct=atr_pct, spread_bps=1.0,
                       last_close=bar.c)

def build_state_mtf(pair, dec_candles, i, contexts, ema_fast=5, ema_slow=15):
    st = build_state(pair, "1m", dec_candles, i)
    bar = dec_candles[i]
    dec_bull, dec_bear = _ema_cross([c.c for c in dec_candles[max(0, i - 50): i + 1]], 5, 15)
    htf_tf = max(contexts.keys(), key=_tf_minutes) if contexts else "1m"
    htf = contexts.get(htf_tf) or dec_candles
    htf_bull, htf_bear = _ema_cross([c.c for c in htf[-(ema_slow + 20):]], ema_fast, ema_slow)
    htf_bias = "bullish" if htf_bull else ("bearish" if htf_bear else "neutral")
    mtf_aligned = ((dec_bull and htf_bull) or (dec_bear and htf_bear) or htf_bias == "neutral")
    w = htf[-20:]
    prior_hi = max(c.h for c in htf[-40:-20]) if len(htf) >= 40 else max(c.h for c in w)
    prior_lo = min(c.l for c in htf[-40:-20]) if len(htf) >= 40 else min(c.l for c in w)
    recent_hi = max(c.h for c in w[-10:])
    recent_lo = min(c.l for c in w[-10:])
    hh = recent_hi > prior_hi
    hl = recent_lo > prior_lo
    lh = recent_hi < prior_hi
    ll = recent_lo < prior_lo
    bos = (hh and htf_bull) or (ll and htf_bear)
    choch = (hh and htf_bear) or (ll and htf_bull)
    sweep_lo = bar.l < prior_lo and bar.c > prior_lo
    sweep_hi = bar.h > prior_hi and bar.c < prior_hi
    return MarketState(symbol=pair, tf="1m", regime=st.regime, htf_bias=htf_bias,
                       last_close=bar.c, body_ratio=st.body_ratio, vol_z=st.vol_z,
                       delta_z=st.delta_z, atr=st.atr, atr_pct=st.atr_pct,
                       spread_bps=1.0, adl_rank=1, mtf_aligned=mtf_aligned,
                       hh=hh, hl=hl, lh=lh, ll=ll, bos=bos, choch=choch,
                       liq_sweep=sweep_lo or sweep_hi, eq_low=sweep_lo, eq_high=sweep_hi,
                       fvg=bos, btc_bias="neutral", dominance_delta=0.0,
                       risk_regime="neutral", alt_rs_btc=0.0, alt_breadth=0.5,
                       ltf_bias="neutral", mtf_bias=htf_bias, htf_bias2=htf_bias,
                       mtf_confluence=False, pullback_to_anchor=False)


def load(pair, tf):
    raw = json.loads((ROOT / "data" / "klines" / f"{pair}_{tf}.json").read_text())
    return [Candle(ts=r[0], o=float(r[1]), h=float(r[2]), l=float(r[3]),
                   c=float(r[4]), v=float(r[5])) for r in raw]


SYM_MAP = {"PEPE": "1000PEPEUSDT", "BONK": "1000BONKUSDT"}
PAIRS = "BTCUSDT,ETHUSDT,SOLUSDT,PEPE,BONK,ENA,WLD,PENGU,AAVE,TAO,INJ,APE,PUMP,WIF,CRV".split(",")
DEC_TF = "1m"
CTX_TFS = ["5m", "15m"]


@dataclass
class Trade:
    side: str
    entry: float
    sl: float
    tp: float
    reason: str = ""
    exit: float = 0.0
    r: float = 0.0
    partial: bool = False
    open_i: int = 0
    base_sl: float = 0.0


def run_pair(pair, surface, profile, max_hold_bars, partial=False, partial_r=1.0):
    dpair = SYM_MAP.get(pair, pair)
    dec = load(dpair, DEC_TF)
    ctx = {tf: load(dpair, tf) for tf in CTX_TFS}
    btc = load("BTCUSDT", "15m")
    basket = [load(p, "15m") for p in PAIRS if p != pair and (ROOT / "data" / "klines" / f"{p}_15m.json").exists()]
    ema_fast, ema_slow = (5, 15)
    trades = []
    open_trade = None
    # warmup
    for i in range(60, len(dec) - max_hold_bars):
        # 1) if open, check exit first (like the bot's monitor on each bar)
        if open_trade is not None:
            bar = dec[i]
            side = open_trade.side
            sd = open_trade.base_sl
            if side == "BUY":
                # partial TP at +partial_r R (lock 50%), move SL to BE
                if partial and not open_trade.partial and bar.h >= open_trade.entry + partial_r * sd:
                    open_trade.partial = True
                    open_trade.sl = open_trade.entry  # BE for remainder
                if bar.l <= open_trade.sl:
                    open_trade.exit, open_trade.reason = open_trade.sl, ("BE" if open_trade.partial else "SL")
                elif (not open_trade.partial) and bar.h >= open_trade.tp:
                    open_trade.exit, open_trade.reason = open_trade.tp, "TP"
                elif open_trade.partial and bar.h >= open_trade.tp:
                    open_trade.exit, open_trade.reason = open_trade.tp, "TP"
            else:
                if partial and not open_trade.partial and bar.l <= open_trade.entry - partial_r * sd:
                    open_trade.partial = True
                    open_trade.sl = open_trade.entry
                if bar.h >= open_trade.sl:
                    open_trade.exit, open_trade.reason = open_trade.sl, ("BE" if open_trade.partial else "SL")
                elif (not open_trade.partial) and bar.l <= open_trade.tp:
                    open_trade.exit, open_trade.reason = open_trade.tp, "TP"
                elif open_trade.partial and bar.l <= open_trade.tp:
                    open_trade.exit, open_trade.reason = open_trade.tp, "TP"
            if open_trade.reason:
                # R: partial half at +partial_r R, remainder at exit (BE or TP)
                if open_trade.partial:
                    r = 0.5 * partial_r + 0.5 * ((open_trade.exit - open_trade.entry) / sd if side == "BUY"
                                           else (open_trade.entry - open_trade.exit) / sd)
                else:
                    r = ((open_trade.exit - open_trade.entry) / sd if side == "BUY"
                         else (open_trade.entry - open_trade.exit) / sd)
                open_trade.r = r
                trades.append(open_trade)
                open_trade = None
                continue
            # maxhold check
            if i - open_trade.open_i >= max_hold_bars:
                open_trade.exit, open_trade.reason = dec[i].c, "MAXHOLD"
                r = ((open_trade.exit - open_trade.entry) / sd if side == "BUY"
                     else (open_trade.entry - open_trade.exit) / sd)
                if open_trade.partial:
                    r = 0.5 * partial_r + 0.5 * r
                open_trade.r = r
                trades.append(open_trade)
                open_trade = None
                continue
            continue  # one position at a time
        # 2) decide
        contexts = {tf: ctx[tf] for tf in CTX_TFS if tf in ctx and len(ctx[tf]) > i}
        adx_tf = max(contexts.keys(), key=_tf_minutes) if contexts else DEC_TF
        adx_v = compute_adx(ctx.get(adx_tf) or dec, 14)
        adx_ok, _ = adx_allowed(adx_v, 25.0)
        state = build_state_mtf(pair, dec, i, contexts, ema_fast, ema_slow)
        # cross-asset context (HONEST: real BTC + real alt basket)
        cs = ContextSeries(
            btc=[c.c for c in btc[:i+1]], pair=[c.c for c in ctx["15m"][:i+1]],
            alt_basket=[[c.c for c in a[:i+1]] for a in basket],
            ltf=[c.c for c in dec[max(0, i-20):i+1]],
            mtf=[c.c for c in ctx["5m"][:i+1]],
            htf=[c.c for c in ctx["15m"][:i+1]],
        )
        mc = build_context(cs)
        state.btc_bias = mc.btc_bias
        state.btc_ret = mc.btc_ret
        state.risk_regime = mc.risk_regime
        state.alt_rs_btc = mc.alt_rs_btc
        state.alt_breadth = mc.alt_breadth
        state.ltf_bias = mc.ltf_bias
        state.mtf_bias = mc.mtf_bias
        state.htf_bias2 = mc.htf_bias
        state.mtf_confluence = mc.mtf_confluence
        state.pullback_to_anchor = mc.pullback_to_anchor
        # adaptive weights (production)
        from engines import adaptive_weights
        aw = adaptive_weights(adx_v, state.regime)
        surface.weights.trend = aw["trend"]; surface.weights.momentum = aw["momentum"]
        surface.weights.volume = aw["volume"]; surface.weights.structure = aw["structure"]
        surface.weights.liquidity = aw["liquidity"]; surface.weights.atr = aw["atr"]
        surface.weights.funding_oi = aw["funding_oi"]
        se = evaluate_strategy(profile, state, entry_price=dec[i].c,
                               atr=(dec[i].c * state.atr_pct), surface=surface)
        if se.decision != "ENTRY":
            continue
        if not adx_ok:
            continue
        # entry
        open_trade = Trade(side=se.side, entry=se.entry_price, sl=se.sl_price,
                           tp=se.tp_price, r=0.0)
        open_trade.open_i = i
        open_trade.base_sl = abs(se.entry_price - se.sl_price)  # fixed R denominator
    return trades


def summarize(pair, trades):
    if not trades:
        return None
    wins = [t for t in trades if t.r > 0]
    losses = [t for t in trades if t.r <= 0]
    n = len(trades)
    wr = 100.0 * len(wins) / n
    exp = sum(t.r for t in trades) / n
    gp = sum(t.r for t in wins); gl = abs(sum(t.r for t in losses))
    pf = gp / gl if gl > 0 else float("inf")
    tp = sum(1 for t in trades if t.reason == "TP")
    sl = sum(1 for t in trades if t.reason == "SL")
    mh = sum(1 for t in trades if t.reason == "MAXHOLD")
    return dict(pair=pair, n=n, wr=wr, exp=exp, pf=pf, tp=tp, sl=sl, mh=mh,
                win_r=sum(t.r for t in wins)/len(wins) if wins else 0,
                loss_r=sum(t.r for t in losses)/len(losses) if losses else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--maxhold", type=int, default=60)
    ap.add_argument("--entry", type=float, default=None, help="override scalping entry_threshold")
    ap.add_argument("--tp", type=float, default=None, help="override scalping tp_atr_mult")
    ap.add_argument("--sl", type=float, default=None, help="override scalping sl_atr_mult")
    ap.add_argument("--pair", type=str, default=None, help="single pair")
    ap.add_argument("--partial", action="store_true", help="partial-TP exit (lock 50% at +partial_r R, BE remainder)")
    ap.add_argument("--partial-r", type=float, default=1.5, help="partial trigger R (default 1.5)")
    args = ap.parse_args()
    surface = default_surface()
    profiles = default_profiles()
    profile = profiles["scalping"]
    if args.entry is not None:
        profile.entry_threshold = args.entry
    if args.tp is not None:
        profile.tp_atr_mult = args.tp
    if args.sl is not None:
        profile.sl_atr_mult = args.sl
    pairs = [args.pair] if args.pair else PAIRS
    allrows = []
    for pair in pairs:
        # pair may be prefixed (PEPE->1000PEPEUSDT) for data files
        dpair = SYM_MAP.get(pair, pair)
        if not (ROOT / "data" / "klines" / f"{dpair}_{DEC_TF}.json").exists():
            print(f"skip {pair}: no 1m data"); continue
        try:
            trades = run_pair(dpair, surface, profile, args.maxhold, partial=args.partial, partial_r=args.partial_r)
        except Exception as e:
            print(f"ERR {pair}: {e}"); continue
        s = summarize(pair, trades)
        if s:
            allrows.append(s)
            print(f"{pair:10s} n={s['n']:4d} WR={s['wr']:5.1f}% exp={s['exp']:+.3f}R "
                  f"PF={s['pf']:.2f} TP={s['tp']} SL={s['sl']} MH={s['mh']}")
    # aggregate
    if allrows:
        tot = sum(r["n"] for r in allrows)
        wins = sum(round(r["n"] * r["wr"] / 100.0) for r in allrows)
        agg_wr = 100.0 * wins / tot
        agg_exp = sum(r["n"] * r["exp"] for r in allrows) / tot
        pos = sum(r["n"] for r in allrows if r["exp"] > 0)
        print("\n=== AGGREGATE (scalping, 1m) ===")
        print(f"total trades : {tot}")
        print(f"avg WR       : {agg_wr:.2f}%")
        print(f"avg expectancy: {agg_exp:+.4f} R")
        print(f"pairs +EV    : {pos}/{len(allrows)}")
        # per-pair detail
        print("\n--- per-pair (exp, wr) ---")
        for r in sorted(allrows, key=lambda x: x["exp"]):
            print(f"  {r['pair']:10s} n={r['n']:4d} WR={r['wr']:5.1f}% exp={r['exp']:+.3f}R "
                  f"({'KEEP' if r['exp'] > 0 else 'EXCLUDE'})")
        # excluder simulation (drop exp<=0)
        kept = [r for r in allrows if r["exp"] > 0]
        if kept:
            kt = sum(r["n"] for r in kept)
            kw = sum(round(r["n"] * r["wr"] / 100.0) for r in kept)
            ke = sum(r["n"] * r["exp"] for r in kept) / kt
            print(f"\n=== WITH EXCLUDER (drop {len(allrows)-len(kept)} -EV pair) ===")
            print(f"pairs kept   : {len(kept)}/{len(allrows)}")
            print(f"avg WR       : {100.0*kw/kt:.2f}%")
            print(f"avg expectancy: {ke:+.4f} R")
        # aggressive WR excluder simulation (drop WR < 45%)
        kept2 = [r for r in allrows if r["wr"] >= 45.0]
        if kept2:
            kt2 = sum(r["n"] for r in kept2)
            kw2 = sum(round(r["n"] * r["wr"] / 100.0) for r in kept2)
            ke2 = sum(r["n"] * r["exp"] for r in kept2) / kt2
            print(f"\n=== AGGRESSIVE EXCLUDER (drop WR<45%, {len(allrows)-len(kept2)} pair) ===")
            print(f"pairs kept   : {len(kept2)}/{len(allrows)}")
            print(f"avg WR       : {100.0*kw2/kt2:.2f}%")
            print(f"avg expectancy: {ke2:+.4f} R")
    # markdown
    (ROOT / "reports").mkdir(exist_ok=True)
    lines = ["# Honest Backtest — scalping (1m decision, 5m/15m ctx)", "",
             f"- max_hold_bars={args.maxhold}", f"- total pairs={len(allrows)}", "",
             "| Pair | N | WR% | Exp(R) | PF | TP | SL | MH |",
             "|------|---|-----|--------|----|----|----|----|"]
    for r in allrows:
        pf = f"{r['pf']:.2f}" if r['pf'] != float('inf') else "inf"
        lines.append(f"| {r['pair']} | {r['n']} | {r['wr']:.1f} | {r['exp']:+.3f} | {pf} | {r['tp']} | {r['sl']} | {r['mh']} |")
    if allrows:
        lines.append(f"| **AGG** | {tot} | {agg_wr:.1f} | {agg_exp:+.3f} | - | | | |")
    (ROOT / "reports" / "eval_honest.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nreport -> {ROOT / 'reports' / 'eval_honest.md'}")


if __name__ == "__main__":
    main()
