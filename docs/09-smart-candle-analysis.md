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
Tentukan arah dari regime + bias HTF (1h/4h):
  ├─ Bullish (uptrend + support / setelah liquidity sweep + HH/HL)
  │    + Bullish candle di LTF (BUKAN exhaustion spike — Layer 3)
  │    + Volume > avg × 1.3
  │    + Momentum cukup
  │    + Spread < 5 bps
  │    + ATR normal, Funding tidak ekstrem, ADL < 4
  │         └─ OPEN BUY  (SL di bawah, TP di atas)
  │
  └─ Bearish (downtrend + resistance / setelah liquidity sweep up + LH/LL)
       + Bearish candle di LTF (BUKAN exhaustion spike — Layer 3)
       + Volume > avg × 1.3
       + Momentum cukup (ke bawah)
       + Spread < 5 bps
       + ATR normal, Funding tidak ekstrem, ADL < 4
            └─ OPEN SELL / SHORT  (SL di atas, TP di bawah)
```
> **SIMETRI WAJIB:** SHORT adalah jalur *first-class*, bukan kebalikan long yang
> ditambal. Setiap kondisi long punya pasangan bearishnya. Sistem futures Binance
> bidirectional → WR ≥85% harus dihitung & digate **per (pair, tf, side)**, bukan
> hanya per (pair, tf). Sentinel dan evaluator menganggap BUY dan SELL sebagai dua
> regime eksekusi terpisah dengan counter masing-masing (`trade_logs.side`,
> `decisions_log` tidak membedakan — decision=ENTRY berlaku untuk kedua arah).

> Versi konkret dari decision tree ini (dengan nilai spread guard, LIMIT order, ATR
> normal, funding/ADL check) ada di `30-concrete-spec.md` §3 (Pre-entry checks) —
> gunakan itu sebagai implementasi final, doc ini hanya konsep.

## Mengapa berbentuk pohon, bukan aturan tunggal
- Aturan tunggal ("kalau hammer → buy") mudah false-positive di regime salah.
- Gate bertingkat memaksa **multiple confirmation** → filter noise & fake signal.
- Setiap cabang gagal = skip, bukan entry.
