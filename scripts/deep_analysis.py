"""Deep analysis v0.0.19 — why all trades were BUY and losing."""
import sqlite3, sys
from collections import Counter

conn = sqlite3.connect("/data/vaisravana.db")
cur = conn.cursor()

print("="*65)
print("DEEP ANALYSIS — v0.0.19 Fresh Run (34 trades, 100% BUY)")
print("="*65)

# 1. Score distribution of ENTRY decisions
print("\n1️⃣  ENTRY SCORE DISTRIBUTION")
cur.execute("SELECT total_score, confidence_pct, pair FROM decisions_log WHERE decision='ENTRY'")
scores = cur.fetchall()
if scores:
    scores_f = [s[0] for s in scores]
    print(f"   Count: {len(scores_f)}")
    print(f"   Min: {min(scores_f):.3f}")
    print(f"   Max: {max(scores_f):.3f}")
    print(f"   Avg: {sum(scores_f)/len(scores_f):.3f}")
    print(f"   Median: {sorted(scores_f)[len(scores_f)//2]:.3f}")
    print(f"   Score buckets:")
    b = Counter()
    for s in scores_f:
        if s < 0.55: b["<0.55"] += 1
        elif s < 0.60: b["0.55-0.60"] += 1
        elif s < 0.65: b["0.60-0.65"] += 1
        elif s < 0.70: b["0.65-0.70"] += 1
        elif s < 0.80: b["0.70-0.80"] += 1
        else: b[">0.80"] += 1
    for bk in sorted(b.keys()):
        print(f"      {bk}: {b[bk]} ({round(b[bk]/len(scores_f)*100,1)}%)")

# 2. GATED reasons — what blocked the rest?
print("\n2️⃣  GATED DECISIONS — REASON ANALYSIS")
cur.execute("SELECT pair, tf, reason FROM decisions_log WHERE decision='GATED' AND reason IS NOT NULL")
reasons_raw = cur.fetchall()
reasons = [r[2] for r in reasons_raw]
if reasons:
    print(f"   Total GATED: {len(reasons)}")
    # Categorize
    cats = Counter()
    for r in reasons:
        if "BUY blocked" in r: cats["BUY_blocked"] += 1
        elif "SELL blocked" in r: cats["SELL_blocked"] += 1
        elif "bleeding" in r: cats["side_bleeding"] += 1
        elif "pullback" in r: cats["no_pullback"] += 1
        elif "ADX" in r: cats["ADX_blocked"] += 1
        elif "threshold" in r: cats["per_side_threshold"] += 1
        elif "cooldown" in r: cats["cooldown"] += 1
        else: cats["other"] += 1
    for k, v in cats.most_common():
        print(f"   {k:25s}: {v}")

# 3. GATED by specific gate
print("\n3️⃣  GATED — BUY vs SELL breakdown")
buy_blocked = sum(1 for r in reasons if "BUY blocked" in r or "BUY" in r and "blocked" in r)
sell_blocked = sum(1 for r in reasons if "SELL blocked" in r or "SELL" in r and "blocked" in r)
print(f"   BUY attempts blocked: {buy_blocked}")
print(f"   SELL attempts blocked: {sell_blocked}")
print(f"   Other blocks: {len(reasons) - buy_blocked - sell_blocked}")

# 4. SUPPRESSED decisions (side-bleed gate)
cur.execute("SELECT reason FROM decisions_log WHERE decision='SUPPRESSED'")
suppressed = cur.fetchall()
sto = Counter()
for r in suppressed:
    if r[0]:
        for key in ["BUY", "SELL", "bleeding"]:
            if key in r[0]: sto[key] += 1
print(f"\n4️⃣  SUPPRESSED (side-bleed gate): {len(suppressed)}")
for k, v in sto.most_common():
    print(f"   {k}: {v}")

# 5. WATCH decisions — the score range
print(f"\n5️⃣  WATCH SCORE RANGE")
cur.execute("SELECT total_score, pair FROM decisions_log WHERE decision='WATCH'")
watch = cur.fetchall()
if watch:
    ws = [w[0] for w in watch]
    print(f"   Count: {len(ws)}")
    print(f"   Range: {min(ws):.3f} — {max(ws):.3f}")
    print(f"   Avg: {sum(ws)/len(ws):.3f}")

# 6. Winning trades analysis — what went right?
print(f"\n6️⃣  WINNING TRADES — R & REASON")
cur.execute("SELECT pair, r_multiple, close_reason FROM trade_logs WHERE win=1 AND ts_fully_closed IS NOT NULL")
wins = cur.fetchall()
if wins:
    print(f"   {len(wins)} winners:")
    for w in wins:
        print(f"     {w[0]:14s} R={round(w[1],3):.3f} ({w[2]})")

# 7. Losing trades analysis — what went wrong?
print(f"\n7️⃣  LOSING TRADES — R & REASON")
cur.execute("SELECT pair, side, r_multiple, close_reason FROM trade_logs WHERE win=0 AND ts_fully_closed IS NOT NULL")
losses = cur.fetchall()
if losses:
    print(f"   {len(losses)} losses:")
    for w in losses:
        print(f"     {w[0]:14s} {w[1]:5s} R={round(w[2],3):.3f} ({w[3]})")

# 8. MAXHOLD duration (time between open and close)
print(f"\n8️⃣  MAXHOLD DURATION")
cur.execute("""
    SELECT pair, side, ts_opened, ts_fully_closed FROM trade_logs 
    WHERE close_reason='MAXHOLD' AND ts_fully_closed IS NOT NULL
""")
maxholds = cur.fetchall()
if maxholds:
    from datetime import datetime
    durations = []
    for r in maxholds:
        try:
            op = datetime.fromisoformat(r[2].replace('Z','+00:00'))
            cl = datetime.fromisoformat(r[3].replace('Z','+00:00'))
            durations.append((cl - op).total_seconds() / 60)
        except: pass
    if durations:
        print(f"   Count: {len(durations)}")
        print(f"   Avg duration: {sum(durations)/len(durations):.1f} min")
        print(f"   Min: {min(durations):.1f} min, Max: {max(durations):.1f} min")

# 9. Correlation of scores with outcomes
print(f"\n9️⃣  SCORE vs OUTCOME CORRELATION")
cur.execute("""
    SELECT d.total_score, t.win, t.r_multiple 
    FROM decisions_log d JOIN trade_logs t ON d.pair=t.pair AND d.correlation_id=t.correlation_id
    WHERE d.decision='ENTRY' AND t.ts_fully_closed IS NOT NULL
""")
corr = cur.fetchall()
if corr:
    wins_by_score = {">0.70": [], "0.65-0.70": [], "0.60-0.65": [], "<0.60": []}
    for sc, win, r in corr:
        if sc > 0.70: wins_by_score[">0.70"].append((win, r))
        elif sc > 0.65: wins_by_score["0.65-0.70"].append((win, r))
        elif sc > 0.60: wins_by_score["0.60-0.65"].append((win, r))
        else: wins_by_score["<0.60"].append((win, r))
    for bk, vals in wins_by_score.items():
        if vals:
            wr = round(sum(1 for v in vals if v[0])/len(vals)*100,1)
            avg_r = round(sum(v[1] for v in vals)/len(vals),3) if vals else 0
            print(f"   Score {bk:12s}: {len(vals)} trades, WR {wr}%, avgR {avg_r}")

conn.close()
print()
