# Arsitektur Bot Berlapis (Production-Grade)

Daripada sekadar membaca candle, desain sistem sebagai **kumpulan engine independen** yang masing-masing memberi skor, lalu digabung.

> Robot tidak bergantung pada satu indikator atau satu pola candle, tetapi membuat keputusan berdasarkan gabungan beberapa bukti yang saling menguatkan.

## 9 Engine

```
┌─────────────────────────────────────────────┐
│            TRADE SCORING ENGINE             │  ← agregat semua skor
│                  ↓ threshold                │
│            RISK MANAGER                     │  ← sizing, SL, trailing,
│                                             │     cooldown, daily loss
└─────────────────────────────────────────────┘
        ▲ (feed skor dari engine di bawah)
┌──────────┬──────────┬──────────┬──────────┐
│ Regime   │ Structure│ Liquidity│ Candle   │
│ Detector │ Engine   │ Engine   │ & PA     │
├──────────┼──────────┼──────────┼──────────┤
│ Volume   │ Volatil. │ Multi-TF │          │
│ Engine   │ Engine   │ Confirm  │          │
└──────────┴──────────┴──────────┴──────────┘
```

### 1. Market Regime Detector
Mengklasifikasikan market: **trending / ranging / breakout / high-volatility**.
Menentukan mode strategi yang aktif.

### 2. Market Structure Engine
Mendeteksi **Higher High, Higher Low, Lower High, Lower Low**, plus
**Break of Structure (BOS)** dan **Change of Character (CHoCH)**.
→ Sumber utama bias arah.

### 3. Liquidity Engine
Mengidentifikasi **equal highs/lows, stop hunt, liquidity sweep, fair value gap (FVG)**.
→ Hindari entry ke jebakan, cari entry setelah sweep.

### 4. Candle & Price Action Engine
Mengenali pola candle (engulfing, pin bar, inside bar, hammer/shooting star)
serta **menghitung kualitas momentum candle** (body size vs rata-rata → exhaustion).

### 5. Volume Engine
Menganalisis volume, **delta** (jika tersedia), dan **anomali aktivitas**.
→ Validasi keaslian gerakan.

### 6. Volatility Engine
Menggunakan **ATR** dan **standard deviation** untuk menentukan
ukuran stop loss, target profit, dan position sizing adaptif.

### 7. Multi-Timeframe Confirmation
Menyelaraskan sinyal HTF (arah) dan LTF (timing).
→ Tolak sinyal LTF yang berlawanan HTF.

### 8. Risk Manager
Mono-tugas kritis:
- **Position sizing** (berbasis % equity / ATR)
- **Leverage** (dibatasi per regime)
- **Stop loss** & **trailing stop**
- **Cooldown setelah loss** (hindari revenge trade)
- **Batas kerugian harian** (kill switch)

### 9. Trade Scoring Engine
Setiap engine di atas mengembalikan skor (lihat [scoring system](10-scoring-system.md)).
Robot **hanya entry kalau total skor > threshold** (mis. 80).

## Alur Data (runtime)
1. Kumpulkan data OHLCV + orderflow (delta/OI/funding) dari exchange.
2. Setiap engine proses data → keluarkan sub-skor.
3. Scoring Engine agregat → total score + arah.
4. Risk Manager cek: apakah score cukup? apakah dalam cooldown? apakah sudah hit daily loss limit?
5. Kalau lolos → hitung size/SL/TP via Volatility + Risk Manager → **OPEN**.
6. Post-entry: trailing stop, monitoring, exit by TP/SL/structure break.

## Mengapa desain ini tangguh
- **Tidak single-point-of-failure**: satu indikator salah ≠ rugi besar, karena butuh konfluensi.
- **Adaptif**: regime detector mengubah bobot/strategi saat pasar berubah.
- **Terukur**: setiap keputusan punya skor → bisa di-backtest & di-tuning.
- **Aman**: Risk Manager sebagai gerbang terakhir (daily loss, cooldown).
- **Isolasi per-pair×TF**: tiap ShadowTrader independen (`30` §8) → pair buruk tidak merusak lainnya.

## Langkah Implementasi (sarannya)
Mulai dari: arsitektur (`ARCHITECTURE.md`) → `30-concrete-spec.md` → algoritma entry/exit
→ risk management → position sizing → **backtesting** → lalu **adaptive AI scoring** agar
mendekati cara trader profesional mengambil keputusan, bukan sekadar bot berbasis indikator.
