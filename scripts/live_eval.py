"""Live DB evaluation of Vaisravana PAPER bot."""
import sqlite3, sys

conn = sqlite3.connect("/data/vaisravana.db")
cur = conn.cursor()

# --- Overall ---
cur.execute("SELECT COUNT(*), SUM(CASE WHEN win=1 THEN 1 ELSE 0 END), SUM(r_multiple) FROM trade_logs WHERE ts_fully_closed IS NOT NULL")
row = cur.fetchone()
total, wins, sum_r = row
wr = round(wins/total*100, 1) if total else 0
exp = round(sum_r/total, 3) if total else 0
print(f"OVERALL: closed={total} wins={wins} WR={wr}% sumR={round(sum_r,3)} EXP={exp}R")

# --- By side ---
cur.execute("SELECT side, COUNT(*), SUM(CASE WHEN win=1 THEN 1 ELSE 0 END), SUM(r_multiple) FROM trade_logs WHERE ts_fully_closed IS NOT NULL GROUP BY side")
print("BY SIDE:")
for r in cur.fetchall():
    s, t, w, rr = r
    wr2 = round(w/t*100, 1) if t else 0
    exp2 = round(rr/t, 3) if t else 0
    print(f"  {s}: closed={t} wins={w} WR={wr2}% sumR={round(rr,3)} EXP={exp2}R")

# --- By pair ---
cur.execute("SELECT pair, COUNT(*), SUM(CASE WHEN win=1 THEN 1 ELSE 0 END), SUM(r_multiple) FROM trade_logs WHERE ts_fully_closed IS NOT NULL GROUP BY pair ORDER BY COUNT(*) DESC")
print("BY PAIR:")
for r in cur.fetchall():
    p, t, w, rr = r
    wr2 = round(w/t*100, 1) if t else 0
    exp2 = round(rr/t, 3) if t else 0
    print(f"  {p}: closed={t} wins={w} WR={wr2}% EXP={exp2}R")

# --- Close reasons ---
cur.execute("SELECT close_reason, COUNT(*), SUM(CASE WHEN win=1 THEN 1 ELSE 0 END), AVG(r_multiple) FROM trade_logs WHERE ts_fully_closed IS NOT NULL GROUP BY close_reason")
print("CLOSE REASONS:")
for r in cur.fetchall():
    cr, cnt, w, avg_r = r
    print(f"  {cr}: cnt={cnt} wins={w} avgR={round(avg_r,3) if avg_r else 0}")

# --- R-distribution by side ---
cur.execute("SELECT side, r_multiple FROM trade_logs WHERE ts_fully_closed IS NOT NULL AND r_multiple IS NOT NULL")
side_r = {"BUY": [], "SELL": []}
for s, rv in cur.fetchall():
    if s in side_r:
        side_r[s].append(rv)

for side in ["BUY", "SELL"]:
    vals = side_r[side]
    if not vals:
        continue
    big_loss = sum(1 for x in vals if x < -0.5)
    small_loss = sum(1 for x in vals if -0.5 <= x < 0)
    small_win = sum(1 for x in vals if 0 <= x < 0.3)
    big_win = sum(1 for x in vals if x >= 0.3)
    print(f"{side} R-dist: total={len(vals)} big_loss(< -0.5R)={big_loss} small_loss={small_loss} small_win={small_win} big_win(>=0.3R)={big_win}")

# --- Open positions ---
cur.execute("SELECT pair, side, r_multiple, ts_opened FROM trade_logs WHERE ts_fully_closed IS NULL")
opens = cur.fetchall()
print(f"OPEN: {len(opens)} positions")
for r in opens:
    print(f"  {r[0]} {r[1]} R={round(r[2],2) if r[2] else 0} opened={r[3][:16] if r[3] else '?'}")

# --- Timespan ---
cur.execute("SELECT MIN(ts_fully_closed), MAX(ts_fully_closed), COUNT(*) FROM trade_logs WHERE ts_fully_closed IS NOT NULL")
min_ts, max_ts, cnt = cur.fetchone()
print(f"TIMESPAN: {min_ts[:19] if min_ts else '?'} -> {max_ts[:19] if max_ts else '?'} ({cnt} trades)")

# --- Open/close ratio ---
cur.execute("SELECT COUNT(*) FROM trade_logs WHERE ts_fully_closed IS NULL")
oc = cur.fetchone()[0]
print(f"OPEN/CLOSED: {oc} open / {total} closed = {round(oc/total*100,1) if total else 0}% open ratio")

conn.close()
