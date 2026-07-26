# Analisis Candle yang Lebih Cerdas

Daripada aturan tunggal yang rapuh:

```
Hammer  →  BUY        ❌ (terlalu simpel, sering false)
```

Gunakan **konfluensi** (beberapa bukti saling menguatkan):

```
Hammer
  + di support
  + volume naik
  + RSI oversold
  + trend HTF bullish
  + ATR normal
  = BUY              ✅ (jauh lebih kuat)
```

Semakin banyak faktor yang selaras, semakin tinggi probabilitas. Ini inti dari pendekatan berbasis bukti ganda.

---

# Decision Tree Robot (Entry Checklist)

Gunakan sebagai gate bertingkat. SETIAP langkah harus lolos sebelum ke langkah berikutnya.

```
Trend?
  ↓
Bullish?
  ↓
Price di support?
  ↓
Bullish candle muncul?
  ↓
Volume naik?
  ↓
Momentum cukup?        (bukan spike exhaustion — Lihat Layer 3)
  ↓
Spread aman?           (biaya/slippage wajar, liquiditas cukup)
  ↓
OPEN BUY
```

Untuk SELL, balikkan logika (downtrend + resistance + bearish candle + volume naik + dst).

> Versi konkret dari decision tree ini (dengan nilai spread guard, LIMIT order, ATR
> normal, funding/ADL check) ada di `30-concrete-spec.md` §3 (Pre-entry checks) —
> gunakan itu sebagai implementasi final, doc ini hanya konsep.

## Mengapa berbentuk pohon, bukan aturan tunggal
- Aturan tunggal ("kalau hammer → buy") mudah false-positive di regime salah.
- Gate bertingkat memaksa **multiple confirmation** → filter noise & fake signal.
- Setiap cabang gagal = skip, bukan entry.
