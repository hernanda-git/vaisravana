import sqlite3
c = sqlite3.connect('/data/vaisravana.db')
print('TABLES:', [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
if 'open_positions' in tabs:
    print('=== OPEN POSITIONS ===')
    for r in c.execute('SELECT pair, side, tf, entry_price, sl_price, tp_price FROM open_positions'):
        print(r)
print('=== SIDE BREAKDOWN (closed) ===')
for r in c.execute('SELECT side, COUNT(*), SUM(win) FROM trade_logs GROUP BY side'):
    n=r[1]; print(r[0], 'n=',n,'WR=%.1f%%' % (r[2]/n*100 if r[2] else 0))
print('=== PAIR BREAKDOWN (closed) ===')
for r in c.execute('SELECT pair, COUNT(*), SUM(win) FROM trade_logs GROUP BY pair'):
    n=r[1]; print(r[0], 'n=',n,'WR=%.1f%%' % (r[2]/n*100 if r[2] else 0))
