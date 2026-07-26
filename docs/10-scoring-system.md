# Sistem Skor Sinyal Futures (Bidirectional)

Pendekatan berbasis **skor** lebih tahan terhadap kondisi pasar yang berubah daripada aturan tunggal.
Karena futures Binance **bidirectional**, sistem menghasilkan **DUA skor terpisah**:
`long_score` (untuk BUY) dan `short_score` (untuk SELL). Kedua jalur **simetris**.

## Bobot Faktor

| Faktor | Bobot | Sumber layer |
|--------|-------|--------------|
| Trend | 30% | Layer 1 + Layer 8 (HTF) |
| Momentum | 20% | Layer 3 |
| Volume | 15% | Layer 4 |
| Market Structure | 15% | Layer 1 (BOS/CHoCH) |
| Liquidity | 10% | Layer 6 |
| Volatility (ATR) | 5% | Layer 7 |
| Funding / OI | 5% | Data derivatif |

Total = 100%. `Σ weights == 1.0` (dijaga Sentinel, `21`).

## Dua Skor: LONG vs SHORT

Setiap faktor dihitung **untuk kedua arah**:

| Faktor | `long_score` tinggi saat | `short_score` tinggi saat |
|--------|--------------------------|----------------------------|
| Trend | HTF bullish + HH/HL | HTF bearish + LH/LL |
| Momentum | candle bullish, bukan exhaustion | candle bearish, bukan exhaustion |
| Volume | volume naik (konfirmasi move) | volume naik (konfirmasi move) |
| Structure | BOS/CHoCH bullish | BOS/CHoCH bearish |
| Liquidity | entry setelah sweep bawah selesai | entry setelah sweep atas selesai |
| ATR | volatilitas wajar | volatilitas wajar |
| Funding/OI | funding tidak extremes berlawanan arah | funding tidak extremes berlawanan arah |

```text
long_score  = Σ (weight_i × factor_i_long)     # 0..1
short_score = Σ (weight_i × factor_i_short)    # 0..1
# pilih arah:
if long_score  > 0.90 and long_score  ≥ short_score : decision = ENTRY, side = BUY
if short_score > 0.90 and short_score ≥ long_score  : decision = ENTRY, side = SELL
elif max(long_score, short_score) in 0.80..0.90       : WATCH
else                                                          : SKIP
```
> **Tidak ada bias arah:** `short_score` bukan "kebalikan long". Kedua dihitung dari
> faktor yang sama dengan polaritas berlawanan. WR ≥85% digate **per (pair, tf, side)**.

## Threshold Keputusan

> Default dari `30-concrete-spec.md` (high-WR tuned). Per-(pair×TF×side) dievaluasi independen.

| Total Skor (arah terpilih) | Tindakan |
|----------------------------|----------|
| **> 0.90** | **Entry** (A+ confluence — untuk capai WR ≥85%) |
| **0.80–0.90** | **Watchlist** (pantau) |
| **< 0.80** | **Skip** |

Selain skor, promosi ke live butuh **Win Rate ≥ 85% per (pair, tf, side)** over ≥200 trade
unreal (lihat `30` §6). Threshold 0.90 sengaja tinggi: hanya entry berkualitas sangat tinggi
yang lolos, mendukung target win-rate tinggi.

## Cara menghitung skor per faktor (contoh, per arah)
- **Trend:** bullish + HH/HL → `long_score` tinggi, `short_score` rendah; bearish → sebaliknya; sideways → keduanya menengah.
- **Momentum:** candle sesuai arah + bukan exhaustion spike = tinggi (untuk arah itu).
- **Volume:** volume > avg × 1.3 = penuh untuk kedua arah (konfirmasi).
- **Structure:** BOS/CHoCH mendukung arah → tinggi untuk arah itu.
- **Liquidity:** entry setelah sweep selesai (bawah untuk long, atas untuk short) = tinggi.
- **ATR:** volatilitas wajar untuk ukuran posisi = penuh; ekstrem = kurangi.
- **Funding/OI:** funding tidak extremes berlawanan arah = aman untuk kedua arah.

## Keunggulan
- Bisa **adaptif**: kalau pasar ranging, faktor trend turun otomatis → score turun → skip.
- **Bidirectional**: menangkap peluang turun (SHORT) tanpa menunggu sinyal eksternal.
- Threshold bisa di-backtest & di-tune per aset.
- Menghindari over-trading karena butuh konfluensi buat tembus 0.90.
