import sqlite3, json
c = sqlite3.connect('/data/vaisravana.db')
cur = c.cursor()

print("=== AGGREGATE ===")
n = cur.execute('SELECT COUNT(*) FROM trade_logs').fetchone()[0]
w = cur.execute('SELECT COUNT(*) FROM trade_logs WHERE win=1').fetchone()[0]
r_sum = cur.execute('SELECT COALESCE(SUM(r_multiple),0) FROM trade_logs WHERE r_multiple IS NOT NULL').fetchone()[0]
print(f"n={n} wins={w} WR={w/n*100:.1f}% sumR={r_sum:.2f} expR/trade={r_sum/n:.3f}")

print("\n=== R:R ACHIEVED (tp_dist/sl_dist per trade) ===")
# TP win => +tp_dist/sl_dist ; SL loss => -1 ; MAXHOLD => realized r_multiple
rows = cur.execute('SELECT close_reason, r_multiple FROM trade_logs WHERE r_multiple IS NOT NULL').fetchall()
from collections import defaultdict
by_reason = defaultdict(list)
for rsn, rm in rows:
    by_reason[rsn].append(rm)
for rsn, vals in by_reason.items():
    avg = sum(vals)/len(vals)
    print(f"{rsn:10s} n={len(vals):3d} avgR={avg:+.3f} min={min(vals):+.3f} max={max(vals):+.3f}")

print("\n=== PER-PAIR (WR, expR, pf, n) ===")
for pair in [r[0] for r in cur.execute('SELECT DISTINCT pair FROM trade_logs')]:
    rs = cur.execute('SELECT win, r_multiple, close_reason FROM trade_logs WHERE pair=?', (pair,)).fetchall()
    nn=len(rs); ww=sum(1 for x in rs if x[0]); 
    rs_ok=[x[1] for x in rs if x[1] is not None]
    exp=sum(rs_ok)/nn if rs_ok else 0
    wins_r=sum(x[1] for x in rs if x[0] and x[1] and x[1]>0)
    loss_r=sum(-x[1] for x in rs if (not x[0]) and x[1] and x[1]<0)
    pf = (wins_r/loss_r) if loss_r>0 else 0
    print(f"{pair:14s} n={nn:3d} WR={ww/nn*100:5.1f}% expR={exp:+.3f} PF={pf:.2f}")

print("\n=== CLOSE REASON MIX (whole book) ===")
tot=cur.execute('SELECT COUNT(*) FROM trade_logs').fetchone()[0]
for r in cur.execute('SELECT close_reason, COUNT(*), SUM(win) FROM trade_logs GROUP BY close_reason'):
    nn=r[1]; print(f"{str(r[0]):10s} n={nn:3d} ({nn/tot*100:4.1f}%) wins={r[2]} WR={ (r[2] or 0)/nn*100 if nn else 0:5.1f}%")

print("\n=== DB SIZE + INDEXES (speed) ===")
sz = cur.execute("SELECT page_count*page_size/1024.0/1024.0 FROM pragma_page_count(), pragma_page_size()").fetchone()[0]
print(f"DB size MB={sz:.2f}")
for t in ['trade_logs','decisions_log','exec_events','system_health','results_log']:
    cnt = cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    idx = [r[0] for r in cur.execute(f'SELECT name FROM sqlite_master WHERE type="index" AND tbl_name="{t}"')]
    print(f"{t:16s} rows={cnt:6d} indexes={idx}")
