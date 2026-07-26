# Concrete Spec — Stability-First, High-Win-Rate (≥85%), Multi-Timeframe Shadow

> **Instance of `ARCHITECTURE.md`.** Authoritative *values* for the system. If another
> doc disagrees on a number, this file (and `21-active-bot.md` for bounds) wins.

**Target (from architecture §1):**
1. **TIME-SENSITIVE ACCURACY** — decision < 200ms, fill < 2s.
2. **STABILITY** — max DD < 3% (unreal & live).
3. **HIGH WIN RATE ≥ 85%** — per (pair, tf, SIDE) in shadow before any live.
4. **MICRO-TIMEFRAME** — trade windows **5m / 10m / 15m**.
5. **ALL BINANCE PAIRS** — universe = all USDT perpetuals, liquidity-filtered.
6. **SHADOW-FIRST** — record every win/loss on unreal before live.

---

## 1. Operating Mode (default = UNREAL)

| Mode | Arti | Kapan |
|------|------|-------|
| `PAPER` (unreal) | Simulasi; **setiap win/loss per (pair×tf×side)** dicatat | **DEFAULT** |
| `SHADOW` | Param kandidat per (pair×tf×side), tak eksekusi | Uji koreksi Sentinel |
| `LIVE` | Uang nyata, **per (pair×tf×side)** yang lolos gate | Hanya setelah gate §6 |

> Unreal-first: bot menghidupkan shadow trader per (pair×tf×side). Live menyala **per (pair×tf×side)**
> (tidak semua sekaligus) hanya kalau gate terpenuhi.

---

## 2. Universe & Timeframe (konkret)

| Item | Nilai | Catatan |
|------|-------|---------|
| Exchange | **Binance** (USDT perpetual / futures) | Semua pair tersedia |
| Universe | **All USDT perps**, lalu **liquidity filter** | drop avg spread > 5bps atau 24h vol < ambang |
| Trade TF | **5m, 10m, 15m** | micro-timeframe, bukan 1m (noise↓, WR↑) |
| Bias TF | 1h + 4h | Penentu arah (Layer 8) |
| ATR period | 14 (di trade TF) | Volatilitas lokal |
| History | 200 candle trade TF, 300 bias TF | Cukup untuk engine |
| Symbol resolution | **exchangeInfo mapping** | user pair → exchange symbol (termasuk 1000x: BONKUSDT→1000BONKUSDT) |

**Liquidity filter (bukan hard cap 2 coin):** memenuhi "all pairs available" sambil
menjaga stabilitas — pair tipis otomatis tidak di-shadow. Pair baru masuk otomatis;
delist/expiry keluar otomatis (`28-D`).

**All-pairs reality (dari `32-listener-lessons.md`):** Binance punya kontrak **1000x**
(BONK/PEPE/SHIB/FLOKI) — quantity integer `stepSize=1`, `minNotional` $5, dan
`LIMIT SELL di bawah market BUKAN SL valid` (langsung terisi). Wajib: mapping symbol,
rounding per-filter, SL pakai conditional STOP (reduceOnly) + fallback mark-price polling.

---

## 3. Entry / Exit (konkret, high-WR tuned)

### Scoring (reuse `10`, threshold NAIK untuk WR tinggi)
- `entry_threshold` = **0.90** (vs 0.82 sebelumnya) → hanya entry A+ confluence.
- `watch_threshold` = 0.80.

### Stop / Target (relatif ATR — Layer 7)
| Param | Nilai | Keterangan |
|-------|-------|------------|
| `sl_atr_mult` | **1.0** | SL sangat ketat (scalp presisi) |
| `tp_atr_mult` | **1.0–1.1** | R:R ~1.0 → akumulasi win kecil, WR tinggi |
| Trailing | aktif setelah +0.6R, lock 0.5R | Amankan profit |
| Max hold | **15m trade → max 15m, 10m → 10m, 5m → 5m** | Window = TF |
| Take-profit juga bisa = level logis terdekat (S/R, FVG fill) |

### Gate A — Pre-scoring (murah, no engine cost) — `28`/`25`
- Idempotency: 1 entry per decision (`correlation_id` unik).
- Per-pair cooldown (jangan over-trade pair yang sama beruntun).
- Pair lolos liquidity-filter / di whitelist.
- Spread < 5 bps (`28-B`).

### Gate B — Post-scoring, pre-execution (hard clamp, engine TDK bisa override) — `25`
- Clamp size ke `risk_usd`; enforce `max_leverage` ≤ 2.
- `daily_loss_limit` ≤ 0.5%; margin ≤ 50% free.
- **SL arah benar** (LONG→SL di bawah, SHORT→di atas) — tolak kalau terbalik.
- reduceOnly pada semua close order (cegah accidental flip).

### Pre-entry confluence (SEMUA wajib — Decision Tree `09`, versi konkret)

Dua jalur **simetris** — SHORT adalah first-class, bukan kebalikan long.

```text
Tentukan arah dari regime + bias HTF (1h/4h):

[BUY / LONG]
  Bias 1h/4h bullish
  + HTF di support / setelah liquidity sweep ke bawah
  + Bullish candle di LTF (BUKAN exhaustion spike — Layer 3)
  + Volume > avg × 1.3
  + Spread < 5 bps              ← krusial multi-pair
  + ATR normal (bukan spike ekstrem)
  + Funding tidak ekstrem
  + ADL rank < 4
  + Bukan window maintenance / delist
  + Pair sudah punya shadow WR ≥ 85% (atau masih fase akumulasi ≥200 trade)
  = ENTRY LONG (PAPER dulu)  →  lewati Gate A + Gate B
    SL di bawah entry, TP di atas (R:R ~1.0)

[SELL / SHORT]   ← pasangan simetris dari LONG
  Bias 1h/4h bearish
  + HTF di resistance / setelah liquidity sweep ke atas
  + Bearish candle di LTF (BUKAN exhaustion spike — Layer 3)
  + Volume > avg × 1.3
  + Spread < 5 bps
  + ATR normal (bukan spike ekstrem)
  + Funding tidak ekstrem
  + ADL rank < 4
  + Bukan window maintenance / delist
  + Pair sudah punya shadow WR ≥ 85% (atau masih fase akumulasi ≥200 trade)
  = ENTRY SHORT (PAPER dulu)  →  lewati Gate A + Gate B
    SL di atas entry, TP di bawah (R:R ~1.0)
```
> **Gate WR per (pair, tf, SIDE):** WR ≥85%, expectancy >+0.2R, DD<3% dihitung
> **terpisah untuk LONG dan SHORT** (futures bidirectional). Promosi LIVE juga per
> (pair, tf, side). `decisions_log.decision = ENTRY` berlaku untuk kedua arah;
> `trade_logs.side = BUY | SELL` mencatat arah aktual.

### Slippage & spread guard (eksekusi multi-pair)
- Skip entry kalau `spread_bps > 5` (per-pair ambang).
- Estimasi fill: `last ± spread/2`.
- **LIMIT order** di sekitar mid (maker) — hindari taker-fee + slippage;
  kalau tidak terisi 2s → cancel, evaluasi ulang (jangan chase).
- **Validate → Repair → Resubmit-once** (`28-B`, dari `32`): sebelum kirim, jalankan
  `validate_order` (precision, min/max price, minQty, minNotional, integer lots).
  Kalau reject: re-derive qty/price dari filter exchange, revalidate, resubmit **1x**.
  Masih invalid → `VALIDATION_SKIP` (jangan dikirim). LLM/reasoning TDK di path repair.

### Position Sizing (risk-based — konkret)
```text
risk_usd      = equity × risk_per_trade      # default 0.25%
sl_distance   = |entry − sl_price|
position_size = risk_usd / sl_distance
notional      = position_size × entry × leverage  (≤ 50% free margin, lev ≤ 2)
```
- `risk_per_trade_pct` default **0.25%**; turun ke 0.15% kalau DD mendekati limit.
- Cap: `position_size × entry × leverage ≤ 50% free margin`.
- **Rounding per-filter** (`28-B`): load `tickSize`/`stepSize`/`minNotional` nyata per
  symbol (exchangeInfo); round price→tickSize, qty→stepSize (integer lots); loop sampai
  `qty × price ≥ minNotional`.

### Position Monitor (background loop, 10s — `25`/`11` §8, dari `32`)
- **SL dual-mechanism:** conditional STOP (reduceOnly) primary + mark-price polling backup
  (untuk 1000x di mana conditional diblokir `-4120`).
- **Self-heal:** kalau SL/TP hilang di exchange tapi posisi masih open → re-place 1x/session.
- **Orphan detection:** posisi tanpa order & age > 30m → verify exchange (source of truth).
- **Time-based exit:** hold > max-hold (15m/10m/5m) → market close.
- **Notify on close:** kirim event ke `exec_events` + `trade_logs` (PnL, reason, closed-by).

---

## 4. Log Everything — Skema Wajib (konkret)

Setiap event → tabel di DB. **`pair` dan `tf` jadi kunci shard (per-pair×TF).**
**TIDAK ADA sinyal eksternal** — bot memutuskan sendiri (internal decision) lalu langsung
masuk posisi. `decisions_log` menggantikan `signals_log` lama (rekam keputusan + confidence %).

### `trade_logs` (WAJIB — "record all win/loss on unreal", lifecycle lengkap)
Satu baris per trade yang **sudah masuk posisi** (internal decision → immediate entry).
Mencatat kapan di-fill, kapan TP, kapan fully closed/closed, win/lose, dan akumulasi win%/loss%.
```sql
CREATE TABLE trade_logs (
  trade_id       TEXT PRIMARY KEY,
  correlation_id TEXT,            -- trace ID (decision→order→fill→tp→close) [32-L5]
  pair           TEXT, tf TEXT,   -- shard per-pair×TF
  side           TEXT,            -- BUY/SELL
  -- lifecycle timestamps
  ts_opened      TIMESTAMPTZ,    -- posisi masuk (market/limit fill)
  ts_filled      TIMESTAMPTZ,    -- saat order tereksekusi penuh
  ts_tp_hit      TIMESTAMPTZ,    -- saat TP (atau TP1) tercapai — NULL kalau tidak
  ts_partial_close TIMESTAMPTZ,  -- saat sebagian ditutup (TP1 50%) — NULL kalau tidak
  ts_fully_closed TIMESTAMPTZ,   -- posisi seluruhnya tertutup
  ts_closed      TIMESTAMPTZ,    -- sinonim close final (alias ts_fully_closed untuk query)
  -- hasil
  win            INTEGER,         -- 1 = win, 0 = lose (boolean, sesuai request)
  loss           INTEGER,         -- 1 = lose, 0 = win (boolean komplemen win)
  win_pct        REAL,            -- % menang kumulatif per (pair×tf×side) saat trade ini
  loss_pct       REAL,            -- % kalah kumulatif per (pair×tf×side) saat trade ini
  pnl_usd        REAL, pnl_pct REAL, r_multiple REAL,
  entry_price    REAL, exit_price REAL,
  size           REAL, leverage REAL,
  sl_price       REAL, tp_price REAL,
  close_reason   TEXT,            -- TP/SL/TRAILING/STRUCTURE/MAXHOLD/PARTIAL
  hold_min       REAL, mfe_r REAL, mae_r REAL,
  spread_bps     REAL, fill_type TEXT, regime TEXT,
  decision_id    TEXT,            -- FK → decisions_log.id
  scores_json    TEXT, config_ver TEXT, notes TEXT
);
```
> **SETIAP trade (menang ATAUPUN kalah) wajib masuk.** `win`/`loss` boolean, `win_pct`/
> `loss_pct` di-update (rolling per (pair×tf×side)) tiap trade close. Ini basis auto-evaluate + promosi.

### `decisions_log` (keputusan internal + confidence %, pengganti signals_log)
Bot memutuskan sendiri → rekam keputusan + **persen confidence**. Ini menggantikan konsep
"signal" eksternal.
```sql
CREATE TABLE decisions_log (
  id            TEXT PRIMARY KEY,
  correlation_id TEXT,            -- [32-L5]
  ts            TIMESTAMPTZ,
  pair          TEXT, tf TEXT,    -- shard per-pair×TF
  regime        TEXT,
  scores_json   TEXT,              -- 7 faktor (trend/momentum/volume/structure/liquidity/atr/funding)
  total_score   REAL,              -- 0..1
  confidence_pct REAL,             -- % confidence (0..100) — diminta user
  decision      TEXT,              -- ENTRY / SKIP / WATCH
  gate_a_pass   INTEGER, gate_b_pass INTEGER,  -- dua-lapis gate [32-L1]
  reason        TEXT, config_ver TEXT
);
```
> `confidence_pct` = turunan dari `total_score` × konteks (mis. `total_score×100`, atau
> kalau engine yakin tinggi di regime terbukti → naik). Dicatat di sini karena trade sudah
> "masuk" (keputusan internal, bukan sinyal luar).

### `results_log` (HISTORIS — evaluasi, reasoning, thinking, correction, improvement, review)
Satu baris per siklus meta-loop. Menyimpan jejak panjang: apa yang dievaluasi, kenapa
(5W1H reasoning), apa yang dikoreksi/diperbaiki, dan ringkasan review.
```sql
CREATE TABLE results_log (
  id            INTEGER PRIMARY KEY,
  ts            TIMESTAMPTZ,
  cycle         TEXT,              -- id siklus (mis. 2026-07-26T12:00)
  pair          TEXT, tf TEXT,      -- NULL = portfolio-wide
  -- jenis catatan
  kind          TEXT,              -- EVALUATION / REASONING / THINKING / CORRECTION / IMPROVEMENT / REVIEW
  content_json  TEXT,               -- detail terstruktur
  -- ringkasan khusus (query-friendly)
  eval_summary  TEXT,               -- ringkasan evaluasi (WR, expectancy, DD)
  reasoning_5w1h TEXT,             -- scaffold 5W1H (WHO/WHAT/WHEN/WHERE/WHY/HOW)
  thinking      TEXT,               -- chain-of-thought / hipotesis (H1/H2/H3)
  correction    TEXT,               -- apa yang diubah (param diff)
  improvement   TEXT,               -- apa yang membaik (metrik sebelum→sesudah)
  review        TEXT,               -- kesimpulan Sentinel / manusia
  config_ver_from TEXT, config_ver_to TEXT,
  approved_by   TEXT               -- autonomous / human
);
```
> Ini memenuhi request: **historically** mencatat evaluation, reasoning, thinking,
> correction, improvement, review — semua dalam satu tabel terurut waktu.

### `exec_events`, `system_health` (konkret, dari `22` + `32-L5`)
```sql
CREATE TABLE exec_events (
  id            INTEGER PRIMARY KEY,
  correlation_id TEXT,
  ts            TIMESTAMPTZ,
  pair          TEXT, tf TEXT,
  event         TEXT,              -- ORDER_SENT / FILL / TP_PLACED / SL_PLACED / VALIDATION_SKIP / REPAIR
  order_type    TEXT, side TEXT,
  price         REAL, qty REAL,
  status        TEXT,              -- PENDING/FILLED/CANCELED/FAILED/VALIDATION_SKIP
  error_cat     TEXT,              -- AUTH/RATE/SERVER/NETWORK [32-L7]
  latency_ms    INTEGER, config_ver TEXT
);

CREATE TABLE system_health (
  id            INTEGER PRIMARY KEY,
  ts            TIMESTAMPTZ,
  correlation_id TEXT,             -- bisa NULL (periodic)
  check         TEXT,              -- exchange/db/symbol_registry/health_reporter
  status        TEXT,              -- OK/WARN/FAIL
  detail        TEXT
);
```
> `correlation_id` mengalir di seluruh pipeline (`32-L5`): satu trade bisa di-trace penuh
> lewat `SELECT * FROM exec_events WHERE correlation_id=?` dst. Basis auto-review Sentinel
> (`24`) & postmortem (`26`).

> **Storage note (implementation):** doc columns use `TIMESTAMPTZ` conceptually; in SQLite
> the timestamp columns are stored as `TEXT` (ISO-8601). The `system_health.check` column is
> a SQLite reserved word, so it is quoted as `"check"` in DDL (`src/db.py`). Column names/
> semantics otherwise unchanged. Logger TIDAK BOLEH gagal silently → alarm + hentikan entry.
> Jangan purge tabel.

---

## 5. Auto Evaluate (konkret, tiap trade, PER PAIR×TF×SIDE)

Trigger: setiap `trade_logs` close → evaluator (`23`) update **per (pair, tf, side)**.

> **SIDE-aware:** LONG dan SHORT dihitung sebagai dua counter terpisah. WR ≥85%,
> expectancy, DD, dll harus lolos **masing-masing untuk BUY dan SELL** — tidak
> digabung. Ini krusial karena kondisi pasar bullish/bearish tidak simetris.

| Metrik | Target (stability + high WR) |
|--------|------------------------------|
| **Win Rate (per pair×tf×side)** | **≥ 85%** ← headline gate |
| Expectancy (R) | > +0.2R |
| Profit Factor | > 1.20 |
| Max Drawdown (akumulasi unreal) | < 3% |
| Sharpe (R) | > 0.5 |
| Fill rate | > 95% |
| Avg slippage (bps) | < 5 |

Rolling window **200 trade per (pair, tf, side)** + harian. Output: `eval_report.md` (`26`).

---

## 6. Promotion Gate (PAPER → LIVE, per pair×TF×SIDE)

Live untuk **satu (pair, tf, SIDE)** HANYA kalau semua terpenuhi (di PAPER):
- Minimal **200 trade unreal** untuk (pair, tf, side) itu.
- **Win Rate ≥ 85%** selama 200 trade tersebut **untuk side tersebut**.
- Expectancy > +0.2R.
- Max DD < 3%.
- Profit Factor > 1.3.
- `system_health` bersih (tidak ada insiden data/eksekusi).
- Peer-review manusia (mode supervised) menyetujui.

> LONG dan SHORT dipromosikan **independen**. Mis. BTCUSDT/5m LONG lulus gate tapi
> SHORT belum → hanya LONG yang LIVE; SHORT tetap di shadow sampai lolos.

**Post-live monitoring:** kalau WR (pair, tf, side) jatuh < 85% selama window validasi →
Sentinel revert ke shadow atau disable. Portfolio WR dijaga lewat pruning.

---

## 7. Stability-First Risk Posture (konkret `25`)

| Guard | Nilai |
|-------|-------|
| `max_leverage` | **2x** (cap keras) |
| `daily_loss_limit_pct` | **0.5%** (unreal & live) → tembus = PAPER + alarm |
| `risk_per_trade_pct` | **0.25%** |
| `cooldown_after_loss` | **10 menit** |
| `max_open_positions` | **1 per (pair×tf×side)** (tidak stacking) |
| `global_max_exposure` | **cap total notional** (mis. 5 pair×TF live sekaligus) |
| `losing_streak_limit` | 5 → cooldown 30 menit |
| Kill switch | drawdown harian / ADL ≥4 / feed frozen / maintenance / delist |
| Human alert | tiap promosi, rollback, kill-switch, insiden |

---

## 8. Multi-Timeframe Shadow Engine (detail `ARCHITECTURE.md` §5)

```text
for each pair P in universe (all Binance USDT, liquidity-filtered):
  for each TF in {5m, 10m, 15m}:
    ShadowTrader(P, TF):          # mengevaluasi DUA side secara independen
       - state & scores independent per SIDE (LONG counter & SHORT counter terpisah)
       - log every unreal trade → trade_logs(pair=P, tf=TF, side=BUY|SELL)
       - EVALUATE WR per (P, TF, SIDE)
       - if WR ≥ 85% over ≥200 trades (side itu) AND gate §6 → promote LIVE(P,TF,SIDE)
       - if WR < 85% after promotion → revert/disable that side
```
Isolasi: (pair×TF×side) buruk tidak merusak lainnya. Sentinel bisa disable 1 baris saja.

---

## 9. Alur Konkret

```text
[setiap candle close per pair×TF (shadow), untuk kedua SIDE]
  → engines → scores → decisions_log (decision=ENTRY, side=BUY|SELL)
  → jika ENTRY & semua check lolos (Gate A + Gate B):
       LIMIT order (PAPER) → exec_events → trade_logs(open, side)
[exit: TP/SL/trailing/maxhold]
  → trade_logs update (pnl, r, win/loss)
  → AUTO-EVALUATE per (pair, tf, SIDE) (rolling 200)
[window 200 trade / harian]
  → eval_report → Sentinel REASON(5W1H) → review → correct(shadow) → promote
[gate §6 (per side) + approve manusia]
  → LIVE untuk (pair, tf, SIDE) itu (shadow tetap jalan sebagai baseline)
```

---

## 10. Mengapa desain ini memenuhi goal

- **+85% WR:** threshold 0.90 + hanya regime terbukti + R:R ~1.0 + per-pair×TF gate.
- **Stability:** lev 2x, daily 0.5%, risk 0.25%, DD<3%, pruned pair×TF.
- **Micro-TF:** 5/10/15m — cepat tapi tidak se-noise 1m.
- **All Binance pairs:** universe penuh + liquidity filter (bukan hard 2 coin).
- **Shadow-first:** semua win/loss di unreal dulu; live per-pair×TF setelah gate.
- **Logged everything:** tiap event persist (`22`/`30` §4).

---
▶ Implementasi: `ARCHITECTURE.md` → doc ini → `22` schema → `23` evaluator (per pair×tf×side) → `27` loop.
