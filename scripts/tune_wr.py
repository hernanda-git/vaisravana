"""Grid-search scalping params on the honest backtest to maximize WR + expectancy.

Sweeps (entry_threshold, tp_atr_mult, sl_atr_mult). Reports aggregate WR / expectancy /
PF / +EV pair count per combo. Goal: find combo with WR >= 56% AND expectancy > 0.

Run: python scripts/tune_wr.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import eval_honest as E
from config import default_profiles, default_surface


def run_combo(entry, tp, sl, maxhold=60):
    surface = default_surface()
    profile = default_profiles()["scalping"]
    profile.entry_threshold = entry
    profile.tp_atr_mult = tp
    profile.sl_atr_mult = sl
    rows = []
    for pair in E.PAIRS:
        dpair = E.SYM_MAP.get(pair, pair)
        if not (ROOT / "data" / "klines" / f"{dpair}_1m.json").exists():
            continue
        try:
            trades = E.run_pair(dpair, surface, profile, maxhold)
        except Exception:
            continue
        s = E.summarize(pair, trades)
        if s:
            rows.append(s)
    if not rows:
        return None
    tot = sum(r["n"] for r in rows)
    wins = sum(round(r["n"] * r["wr"] / 100.0) for r in rows)
    wr = 100.0 * wins / tot
    exp = sum(r["n"] * r["exp"] for r in rows) / tot
    pos = sum(1 for r in rows if r["exp"] > 0)
    return dict(tot=tot, wr=wr, exp=exp, pos=pos, npairs=len(rows))


def main():
    # Focused grid: keep R:R >= 2:1 (owner floor), sweep entry bar + SL/TP scales.
    entries = [0.60, 0.64, 0.68, 0.72]
    # (tp, sl) pairs all give R:R = 2.0
    tpsl = [(2.0, 1.0), (2.5, 1.25), (3.0, 1.5), (2.25, 1.125)]
    print(f"{'entry':>6} {'tp':>5} {'sl':>5} {'RR':>5} {'N':>6} {'WR%':>7} {'Exp':>8} {'+EV':>5}")
    print("-" * 52)
    results = []
    for tp, sl in tpsl:
        rr = tp / sl
        for entry in entries:
            r = run_combo(entry, tp, sl)
            if r:
                results.append((entry, tp, sl, rr, r))
                print(f"{entry:>6.2f} {tp:>5.2f} {sl:>5.2f} {rr:>5.2f} "
                      f"{r['tot']:>6} {r['wr']:>7.1f} {r['exp']:>+8.3f} {r['pos']:>3}/{r['npairs']}")
    best = [r for r in results if r[4]["wr"] >= 56.0 and r[4]["exp"] > 0]
    best.sort(key=lambda x: (x[4]["exp"], x[4]["wr"]), reverse=True)
    print("\n=== COMBOS WITH WR>=56% AND +EV (ranked by expectancy) ===")
    for entry, tp, sl, rr, r in best[:10]:
        print(f"entry={entry:.2f} tp={tp:.2f} sl={sl:.2f} RR={rr:.2f} "
              f"WR={r['wr']:.1f}% exp={r['exp']:+.3f}R +EV={r['pos']}/{r['npairs']}")
    if not best:
        print("none met WR>=56% & +EV simultaneously. Showing top by expectancy:")
        results.sort(key=lambda x: x[4]["exp"], reverse=True)
        for entry, tp, sl, rr, r in results[:5]:
            print(f"entry={entry:.2f} tp={tp:.2f} sl={sl:.2f} RR={rr:.2f} "
                  f"WR={r['wr']:.1f}% exp={r['exp']:+.3f}R +EV={r['pos']}/{r['npairs']}")


if __name__ == "__main__":
    main()
