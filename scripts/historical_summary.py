"""Extract complete historical trade data from Fly DB for documentation."""
import sqlite3, sys

conn = sqlite3.connect("/data/vaisravana.db")
cur = conn.cursor()

print("=" * 60)
print("VAISRAVANA — HISTORICAL SUMMARY (pre-v0.0.19 clean)")
print("=" * 60)

# ── Overall ──
cur.execute("SELECT COUNT(*), SUM(CASE WHEN win=1 THEN 1 ELSE 0 END), SUM(r_multiple), COALESCE(SUM(pnl_usd),0) FROM trade_logs WHERE ts_fully_closed IS NOT NULL")
row = cur.fetchone()
total, wins, sum_r, sum_pnl = row
losses = total - wins
wr = round(wins/total*100, 1) if total else 0
exp = round(sum_r/total, 3) if total else 0
print(f"\n📊 OVERALL")
print(f"   Closed trades : {total}")
print(f"   Wins          : {wins}  ({wr}%)")
print(f"   Losses        : {losses}  ({100-wr:.1f}%)")
print(f"   Sum R         : {sum_r:.3f}R")
print(f"   Expectancy    : {exp:+.3f}R/trade")
print(f"   PnL (USD)     : ${sum_pnl:.2f}")

# ── By side ──
cur.execute("SELECT side, COUNT(*), SUM(CASE WHEN win=1 THEN 1 ELSE 0 END), SUM(r_multiple), COALESCE(SUM(pnl_usd),0) FROM trade_logs WHERE ts_fully_closed IS NOT NULL GROUP BY side ORDER BY COUNT(*) DESC")
print(f"\n📊 BY SIDE")
rows = cur.fetchall()
for r in rows:
    s, t, w, rr, pnl = r
    wr2 = round(w/t*100, 1) if t else 0
    exp2 = round(rr/t, 3) if t else 0
    print(f"   {s:5s}: {t:3d} closed, {w:2d}W {t-w:2d}L ({wr2:5.1f}%) | ΣR {rr:+.3f} | Exp {exp2:+.3f}R | PnL ${pnl:.2f}")

# ── By pair ──
cur.execute("SELECT pair, COUNT(*), SUM(CASE WHEN win=1 THEN 1 ELSE 0 END), SUM(r_multiple), COALESCE(SUM(pnl_usd),0) FROM trade_logs WHERE ts_fully_closed IS NOT NULL GROUP BY pair ORDER BY COUNT(*) DESC")
print(f"\n📊 BY PAIR (sorted by volume)")
rows = cur.fetchall()
for r in rows:
    p, t, w, rr, pnl = r
    wr2 = round(w/t*100, 1) if t else 0
    exp2 = round(rr/t, 3) if t else 0
    print(f"   {p:14s}: {t:2d} closed, {wr2:5.1f}% WR | ΣR {rr:+.3f} | Exp {exp2:+.3f}R | PnL ${pnl:.2f}")

# ── By strategy (decision_tf) ──
try:
    cur.execute("SELECT decision_tf, COUNT(*), SUM(CASE WHEN win=1 THEN 1 ELSE 0 END), SUM(r_multiple) FROM trade_logs WHERE ts_fully_closed IS NOT NULL GROUP BY decision_tf")
    rows = cur.fetchall()
    if rows:
        print(f"\n📊 BY TIMEFRAME")
        for r in rows:
            tf, t, w, rr = r
            wr2 = round(w/t*100, 1) if t else 0
            exp2 = round(rr/t, 3) if t else 0
            print(f"   {tf:5s}: {t:2d} closed, {wr2:5.1f}% WR | ΣR {rr:+.3f} | Exp {exp2:+.3f}R")
except:
    print("\n📊 BY TIMEFRAME: (no decision_tf column in this version)")

# ── Close reasons ──
cur.execute("SELECT close_reason, COUNT(*), SUM(CASE WHEN win=1 THEN 1 ELSE 0 END), AVG(r_multiple), SUM(r_multiple) FROM trade_logs WHERE ts_fully_closed IS NOT NULL GROUP BY close_reason ORDER BY COUNT(*) DESC")
print(f"\n📊 CLOSE REASONS")
rows = cur.fetchall()
for r in rows:
    cr, cnt, w, avg_r, sum_rr = r
    pct = round(cnt/total*100, 1) if total else 0
    print(f"   {cr:10s}: {cnt:2d} ({pct:5.1f}%) | {w:2d}W {cnt-w:2d}L | avgR {avg_r:+.3f} | ΣR {sum_rr:+.3f}")

# ── R distribution per side ──
cur.execute("SELECT side, r_multiple FROM trade_logs WHERE ts_fully_closed IS NOT NULL AND r_multiple IS NOT NULL")
data = {"BUY": [], "SELL": []}
for s, rv in cur.fetchall():
    if s in data: data[s].append(rv)
print(f"\n📊 R-DISTRIBUTION")
for side in ["BUY", "SELL"]:
    vals = data[side]
    if not vals: continue
    bins = {"<-1R": 0, "-1 to -0.5": 0, "-0.5 to 0": 0, "0 to 0.5": 0, "0.5 to 1": 0, ">1R": 0}
    for v in vals:
        if v < -1: bins["<-1R"] += 1
        elif v < -0.5: bins["-1 to -0.5"] += 1
        elif v < 0: bins["-0.5 to 0"] += 1
        elif v < 0.5: bins["0 to 0.5"] += 1
        elif v < 1.0: bins["0.5 to 1"] += 1
        else: bins[">1R"] += 1
    print(f"   {side} ({len(vals)} trades):")
    for k, v in bins.items():
        print(f"      {k:14s}: {v} ({round(v/len(vals)*100,1)}%)")

# ── Open positions ──
cur.execute("SELECT pair, side, r_multiple, ts_opened FROM trade_logs WHERE ts_fully_closed IS NULL")
opens = cur.fetchall()
print(f"\n📊 OPEN POSITIONS: {len(opens)}")
for r in opens:
    print(f"   {r[0]:14s} {r[1]:5s} R={round(r[2],2) if r[2] else 0:.2f} opened={r[3][:16] if r[3] else '?'}")

# ── Timespan ──
cur.execute("SELECT MIN(ts_fully_closed), MAX(ts_fully_closed) FROM trade_logs WHERE ts_fully_closed IS NOT NULL")
min_ts, max_ts = cur.fetchone()
print(f"\n📊 TIMESPAN")
print(f"   First close   : {min_ts[:19] if min_ts else '?'}")
print(f"   Last close    : {max_ts[:19] if max_ts else '?'}")

# ── Decisions log ──
try:
    cur.execute("SELECT decision, COUNT(*) FROM decisions_log GROUP BY decision ORDER BY COUNT(*) DESC")
    dec = cur.fetchall()
    if dec:
        print(f"\n📊 DECISIONS LOG")
        for d in dec:
            print(f"   {d[0]:12s}: {d[1]}")
    else:
        print(f"\n📊 DECISIONS LOG: empty")
except:
    print(f"\n📊 DECISIONS LOG: (error)")

# ── DB size ──
cur.execute("SELECT COUNT(*) FROM trade_logs")
tl = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM decisions_log")
dl = cur.fetchone()[0]
print(f"\n📊 DB STATE")
print(f"   trade_logs    : {tl} rows")
print(f"   decisions_log : {dl} rows")

# ── Key learning ──
print(f"\n{'='*60}")
print("KEY FINDINGS")
print("="*60)
print("""
1. BUY side was a disaster (23.7% WR, -0.231R) — 63% of all trades were BUY
2. SELL side was profitable (59.1% WR, +0.320R initially) — only 37% of trades
3. The bot was long-biased into a bearish regime — THE root cause
4. 100% of SL closes were losses (22% of all closes) — entries at swing extremes
5. 65% of closes were MAXHOLD at breakeven — no trend support
6. Only 13% of closes reached TP — too few winners vs losers
7. v0.0.19 fixes (directional gate, ADX, vol-SL, trailing stop, cooldown, pair weights)
   are now deployed and active.
""")

conn.close()
