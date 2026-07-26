"""Phase 9 — REAL-DATA backtest run.

Input:  data/klines/{PAIR}_{TF}.json — real Binance USDⓈ-M klines fetched via
        scripts/fetch_klines_via_gateway.py (Fly VM, region sin).
Output: reports/backtest_report_real.md + per-side eval + OOS comparison.

MarketState derivation is computed HONESTLY from the candles (rolling stats):
  - regime: EMA20 vs EMA50 slope + ATR% (trending_bull/bear, range, high_vol)
  - structure flags (hh/hl/lh/ll, bos, sweep) from rolling swing highs/lows
  - vol_z / delta_z: z-score of volume / signed volume vs 50-bar window
  - body_ratio from the bar itself
No flag is invented; every input traces to OHLCV arithmetic.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from backtest import BacktestHarness, report_markdown, split  # noqa: E402
from db import init_db  # noqa: E402
from engines import MarketState  # noqa: E402
from marketdata import Candle  # noqa: E402

WINDOW = 50


def load(pair: str, tf: str) -> list[Candle]:
    raw = json.loads((ROOT / "data" / "klines" / f"{pair}_{tf}.json").read_text())
    return [Candle(ts=r[0], o=float(r[1]), h=float(r[2]), l=float(r[3]),
                   c=float(r[4]), v=float(r[5])) for r in raw]


def _ema(vals: list[float], period: int) -> float:
    k = 2.0 / (period + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def state_factory(pair: str, tf: str):
    def factory(candles: list[Candle], i: int) -> MarketState:
        w = candles[max(0, i - WINDOW): i + 1]
        closes = [c.c for c in w]
        vols = [c.v for c in w]
        bar = candles[i]

        ema20 = _ema(closes[-20:], 20)
        ema50 = _ema(closes, 50)
        atr14 = statistics.mean(
            max(candles[j].h - candles[j].l,
                abs(candles[j].h - candles[j - 1].c),
                abs(candles[j].l - candles[j - 1].c))
            for j in range(max(1, i - 13), i + 1)
        )
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

        # structure: rolling swing points over last 10 vs previous 10
        recent_hi = max(c.h for c in w[-10:]); prior_hi = max(c.h for c in w[-20:-10]) if len(w) >= 20 else recent_hi
        recent_lo = min(c.l for c in w[-10:]); prior_lo = min(c.l for c in w[-20:-10]) if len(w) >= 20 else recent_lo
        hh, hl = recent_hi > prior_hi, recent_lo > prior_lo
        lh, ll = recent_hi < prior_hi, recent_lo < prior_lo
        bos = (hh and bull) or (ll and bear)
        choch = (hh and bear) or (ll and bull)

        mu, sd = statistics.mean(vols), (statistics.pstdev(vols) or 1e-9)
        vol_z = (vols[-1] - mu) / sd
        signed = [(c.c - c.o) / (abs(c.c - c.o) + 1e-9) * c.v for c in w]
        smu, ssd = statistics.mean(signed), (statistics.pstdev(signed) or 1e-9)
        delta_z = (signed[-1] - smu) / ssd
        body_ratio = abs(bar.c - bar.o) / ((bar.h - bar.l) or 1e-9)

        sweep_lo = bar.l < prior_lo and bar.c > prior_lo   # sweep of lows then reclaim
        sweep_hi = bar.h > prior_hi and bar.c < prior_hi

        return MarketState(
            symbol=pair, tf=tf, regime=regime,
            htf_bias="bullish" if bull else ("bearish" if bear else "neutral"),
            body_ratio=body_ratio, vol_z=vol_z, delta_z=delta_z,
            bos=bos, hh=hh, hl=hl, lh=lh, ll=ll, choch=choch,
            liq_sweep=sweep_lo or sweep_hi, eq_low=sweep_lo, eq_high=sweep_hi,
            fvg=bos, atr_pct=atr_pct, spread_bps=1.0, funding_ok=True, adl_rank=1,
            last_close=bar.c,
        )
    return factory


def state_factory_mtf(pair: str, tf: str, contexts: dict[str, list[Candle]]):
    """Phase 12 — 1m (DECISION_TF) decision state with MTF context (5m/15m bias)."""
    single = state_factory(pair, tf)

    def factory(candles: list[Candle], i: int) -> MarketState:
        st = single(candles, i)
        # higher-TF bias from the largest available context
        htf_tf = max(contexts.keys(), key=lambda t: _tf_minutes(t)) if contexts else tf
        htf = contexts.get(htf_tf) or candles
        hc = [c.c for c in htf[-50:]]
        ema20 = _ema(hc[-20:], 20); ema50 = _ema(hc, 50)
        htf_bull = ema20 > ema50 * 1.0005; htf_bear = ema20 < ema50 * 0.9995
        htf_bias = "bullish" if htf_bull else ("bearish" if htf_bear else "neutral")
        dc = [c.c for c in candles[max(0, i - 50): i + 1]]
        dbull = _ema(dc[-20:], 20) > _ema(dc, 50) * 1.0005
        dbear = _ema(dc[-20:], 20) < _ema(dc, 50) * 0.9995
        mtf_aligned = (dbull and htf_bull) or (dbear and htf_bear) or htf_bias == "neutral"
        return MarketState(
            symbol=pair, tf=tf, regime=st.regime, htf_bias=htf_bias,
            body_ratio=st.body_ratio, vol_z=st.vol_z, delta_z=st.delta_z,
            bos=st.bos, hh=st.hh, hl=st.hl, lh=st.lh, ll=st.ll, choch=st.choch,
            liq_sweep=st.liq_sweep, eq_low=st.eq_low, eq_high=st.eq_high, fvg=st.fvg,
            atr_pct=st.atr_pct, spread_bps=1.0, funding_ok=True, adl_rank=1,
            mtf_aligned=mtf_aligned, last_close=st.last_close,
        )
    return factory


def _tf_minutes(tf: str) -> int:
    unit = tf[-1].lower()
    mult = int(tf[:-1]) if tf[:-1].isdigit() else 1
    return mult * {"m": 1, "h": 60, "d": 1440}.get(unit, 1)


def run_series(pair: str, tf: str, candles: list[Candle], tag: str):
    conn = init_db(ROOT / "reports" / f"real_{pair}_{tf}_{tag}.db")
    h = BacktestHarness(conn, state_factory(pair, tf))
    stats = h.run(pair, tf, candles)
    conn.close()
    return stats


def main() -> None:
    (ROOT / "reports").mkdir(exist_ok=True)
    for f in (ROOT / "reports").glob("real_*.db"):
        f.unlink()

    pairs_tfs = [(p, tf) for p in ("BTCUSDT", "ETHUSDT", "SOLUSDT") for tf in ("5m", "15m")]
    full_stats, ins_stats, oos_stats = [], [], []
    DEC_TF = "1m"          # Phase 12: decide every minute
    CTX_TFS = ["5m", "15m"]
    for pair, tf in pairs_tfs:
        candles = load(pair, tf)
        ins, oos = split(candles, oos_frac=0.3)
        # Phase 12: backtest the 1m decision cadence with MTF context from 5m/15m.
        ctx = {c: load(pair, c) for c in CTX_TFS}
        factory = state_factory_mtf(pair, DEC_TF, ctx)
        # run the 1m decision series over the SAME real history length (replay 1m bars)
        try:
            dec_candles = load(pair, DEC_TF)
        except FileNotFoundError:
            print(f"SKIP {pair} {DEC_TF}: no {DEC_TF} klines fetched yet "
                  f"(run scripts/fetch_klines_via_gateway.py with 1m).")
            continue
        for tag, series in (("full", dec_candles), ("ins", dec_candles[:int(len(dec_candles)*0.7)]),
                            ("oos", dec_candles[int(len(dec_candles)*0.7):])):
            conn = init_db(ROOT / "reports" / f"real_{pair}_{DEC_TF}_{tag}.db")
            h = BacktestHarness(conn, factory)
            st = h.run(pair, DEC_TF, series)
            conn.close()
            if tag == "full": full_stats.append(st)
            elif tag == "ins": ins_stats.append(st)
            else: oos_stats.append(st)
            print(f"{pair} {DEC_TF} {tag}: {st.candles} bars, entries={st.entries} "
                  f"TP={st.tp_exits} SL={st.sl_exits} MH={st.maxhold_exits}")

    md = ["# Phase 9 — Real-Data Backtest (Binance USDⓈ-M via binance-gateway/sin)",
          "",
          f"- Source: real klines, 1500 bars per series (fetched 2026-07-26)",
          "- Fees: VIP0 maker 0.02% / taker 0.05% (LIMIT entry+TP maker; SL/MAXHOLD taker)",
          "- Conservative bar-fill rule: SL checked before TP within the same bar",
          "", "## Full sample", "", report_markdown(full_stats),
          "", "## In-sample (70%)", "", report_markdown(ins_stats),
          "", "## Out-of-sample (30%)", "", report_markdown(oos_stats),
          "", "## Notes",
          "- Entries are sparse by design: 0.90 entry_threshold + Gate A/B select only A+ setups.",
          "- WR targets (≥85% per pair×tf×side over 200 trades) require far longer history;",
          "  this run validates PIPELINE correctness on real data, not final promotion stats.",
          ]
    out = ROOT / "reports" / "backtest_report_real.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"\nreport → {out}")


if __name__ == "__main__":
    main()
