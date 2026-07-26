"""Project Vaiśravaṇa — HONEST out-of-sample backtest (doc 40 §2 / doc 41).

Differences from run_backtest_real.py (the previous "honest on paper" run):
  1. Multi-bar hold is REAL: MAX_HOLD_BARS defaults to 60 (≈1h on 1m), not a single
     next-bar gamble. Configurable via --max-hold.
  2. Taker entry fee by default (the 1m "jump" cadence is marketable → taker), not the
     optimistic maker-entry assumption. Configurable via --fees entry,tp,exit.
  3. Reports EXPECTANCY (R) and PROFIT FACTOR per (pair,tf,side), not just WR —
     because an 85% WR with 1.05R TP / 1R SL is a guaranteed loss after fees (doc 40 §2.2).
  4. Runs In-Sample vs Out-of-Sample split and prints the OOS delta so we never mistake
     curve-fit for edge.

Real klines live in data/*.csv (fetched 2026-07-26). If missing, the script synthesizes
a deterministic mean-reverting series so CI can run it without network (flagged clearly).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from backtest import BacktestHarness, split, report_markdown  # noqa: E402
from config import default_surface  # noqa: E402
from marketdata import Candle  # noqa: E402
from db import init_db  # noqa: E402

try:
    from run_backtest_real import load, state_factory_mtf  # reuse real-data loader
except Exception:  # allow standalone run without the real-data module
    load = None
    state_factory_mtf = None


PAIRS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
CTX_TFS = ["5m", "15m"]
DEC_TF = "1m"


def synth(pair: str, tf: str, n: int = 1500, seed: int = 7) -> list[Candle]:
    """Deterministic mean-reverting series so CI has an edge-free baseline."""
    import math
    candles = []
    price = 100.0 + hash((pair, tf)) % 50
    for i in range(n):
        shock = math.sin(i / 11.0 + seed) * 0.4 + math.sin(i / 3.0) * 0.15
        price = max(1.0, price * (1 + 0.001 * shock))
        o = price
        c = price * (1 + 0.0008 * math.sin(i / 7.0))
        h = max(o, c) * (1 + 0.0012 * abs(math.sin(i / 5.0)))
        l = min(o, c) * (1 - 0.0012 * abs(math.cos(i / 5.0)))
        ts = i * 60_000
        candles.append(Candle(o=round(o, 2), h=round(h, 2), l=round(l, 2),
                              c=round(c, 2), v=1000.0, ts=ts))
    return candles


def get(pair: str, tf: str, maxbars: int = 1500) -> list[Candle]:
    if load is not None:
        try:
            c = load(pair, tf)
            return c[-maxbars:]
        except FileNotFoundError:
            pass
    return synth(pair, tf, maxbars)


def run() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-hold", type=int, default=60,
                    help="max bars before MAXHOLD (60 ≈ 1h on 1m). 1 = old gamble mode.")
    ap.add_argument("--fees", type=str, default="0.0005,0.0002,0.0005",
                    help="entry,tp,exit fees (taker,tp_maker,exit). VIP0 = 5,2,5 bps.")
    ap.add_argument("--lev", type=int, default=2)
    ap.add_argument("--oos", type=float, default=0.3)
    args = ap.parse_args()

    entry_f, tp_f, exit_f = (float(x) for x in args.fees.split(","))
    surface = default_surface()
    surface.max_leverage = args.lev

    (ROOT / "reports").mkdir(exist_ok=True)
    full, ins, oos = [], [], []
    synth_note = "REAL klines" if load else "SYNTH (no klines present — edge-free baseline)"

    # backtest each decision TF with its HTF context so we see WHERE the strategy
    # actually engages (doc 40 §2: 1m barely fires; 5m/15m is where structure forms).
    tf_contexts = {
        "1m": ["5m", "15m"],
        "5m": ["15m", "1h"],
        "15m": ["1h", "4h"],
    }
    from marketcontext import build_context, ContextSeries
    from marketdata import Candle as _C

    def closes(cs):
        return [c.c for c in cs]

    for pair in PAIRS:
        for dec_tf in ("1m", "5m", "15m"):
            ctx_tfs = tf_contexts[dec_tf]
            ctx = {c: get(pair, c) for c in ctx_tfs}
            dec = get(pair, dec_tf)
            btc = get("BTCUSDT", "1h")
            basket = [closes(get(q, "1h")) for q in PAIRS if q != pair]
            basket = [b for b in basket if len(b) >= 50]
            dec_closes = closes(dec)

            def factory(candles, i, _p=pair, _dec=dec_closes, _btc=closes(btc),
                        _basket=basket, _ctx=ctx, _dtf=dec_tf):
                # state_factory_mtf(pair, tf, ctx) returns the INNER factory(candles,i)
                inner = (state_factory_mtf(_p, _dtf, _ctx) if state_factory_mtf
                         else lambda c, j: build_state_mtf(_p, c, j, {}))
                st = inner(candles, i)
                # offline relational context from the precomputed series
                cs = ContextSeries(
                    btc=_btc, pair=_dec, alt_basket=_basket,
                    ltf=_dec, mtf=_dec, htf=_dec, dominance=[],
                )
                mc = build_context(cs, lookback=30)
                st.btc_bias = mc.btc_bias
                st.risk_regime = mc.risk_regime
                st.dominance_delta = mc.dominance_delta
                st.alt_rs_btc = mc.alt_rs_btc
                st.alt_breadth = mc.alt_breadth
                st.ltf_bias = mc.ltf_bias
                st.mtf_bias = mc.mtf_bias
                st.htf_bias2 = mc.htf_bias
                st.mtf_confluence = mc.mtf_confluence
                st.pullback_to_anchor = mc.pullback_to_anchor
                return st

            n = len(dec)
            i0 = int(n * (1 - args.oos))
            ins_series, oos_series = dec[:i0], dec[i0:n]
            for tag, series in (("full", dec), ("ins", ins_series), ("oos", oos_series)):
                conn = init_db(":memory:")
                h = BacktestHarness(conn, factory, surface=surface,
                                    max_hold_bars=args.max_hold,
                                    fees=(entry_f, tp_f, exit_f))
                st = h.run(pair, dec_tf, series)
                conn.close()
                store = full if tag == "full" else ins if tag == "ins" else oos
                store.append(st)
                print(f"{pair} {dec_tf} {tag}: bars={st.candles} entries={st.entries} "
                      f"TP={st.tp_exits} SL={st.sl_exits} MH={st.maxhold_exits} "
                      f"fees=${st.fees_usd:.2f}")

    md = [
        "# HONEST OOS Backtest — Vaiśravaṇa",
        "",
        f"- Data: {synth_note}",
        f"- max_hold_bars = {args.max_hold} (60 ≈ 1h on 1m; old mode was 1)",
        f"- fees (entry,tp,exit) = {entry_f*1e4:.2f}/{tp_f*1e4:.2f}/{exit_f*1e4:.2f} bps "
        f"(VIP0 taker entry)",
        f"- leverage = {args.lev}x · surface sl/atr={surface.sl_atr_mult} tp/atr={surface.tp_atr_mult}",
        f"- OOS split = {args.oos:.0%} · decision TFs tested: 1m, 5m, 15m (with HTF context)",
        "",
        "## FULL sample", "", report_markdown(full),
        "## IN-SAMPLE (70%)", "", report_markdown(ins),
        "## OUT-OF-SAMPLE (30%)", "", report_markdown(oos),
        "",
        "## Verdict (doc 40 §2)",
        "- WR alone is NOT evidence. With 1.05R TP / 1R SL you need ~95% hit-rate to "
        "break even after fees — an 85% gate is a guaranteed loser.",
        "- Compare OOS expectancy vs IN-SAMPLE. A real edge survives OOS; curve-fit does not.",
        "- If entries≈0 on 1m: the 0.90 threshold + 1m cadence is too sparse; 5m/15m is "
        "where structure forms, so evaluate promotion there, not on 1m.",
    ]
    out = ROOT / "reports" / "backtest_honest.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"\nreport → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
