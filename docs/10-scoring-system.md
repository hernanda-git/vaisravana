# Sistem Skor Sinyal Futures

Pendekatan berbasis **skor** lebih tahan terhadap kondisi pasar yang berubah daripada aturan tunggal.

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

Total = 100%.

## Contoh Perhitungan

| Faktor | Skor (0–maks) | Kontribusi |
|--------|---------------|------------|
| Trend | 28 / 30 | 28 |
| Momentum | 17 / 20 | 17 |
| Volume | 10 / 15 | 10 |
| Structure | 13 / 15 | 13 |
| Liquidity | 8 / 10 | 8 |
| ATR | 5 / 5 | 5 |
| OI | 5 / 5 | 5 |
| **Total** | | **86** |

## Threshold Keputusan

> Default dari `30-concrete-spec.md` (high-WR tuned). Per-pair×TF dievaluasi independen.

| Total Skor | Tindakan |
|------------|----------|
| **> 0.90** | **Entry** (A+ confluence — untuk capai WR ≥85%) |
| **0.80–0.90** | **Watchlist** (pantau) |
| **< 0.80** | **Skip** |

Selain skor, promosi ke live butuh **Win Rate ≥ 85% per pair×TF** over ≥200 trade unreal
(lihat `30` §6). Threshold 0.90 sengaja tinggi: hanya entry berkualitas sangat tinggi
yang lolos, mendukung target win-rate tinggi.

## Cara menghitung skor per faktor (contoh)
- **Trend (0–30):** HTF bullish + struktur HH/HL = tinggi; sideways = menengah; bearish = rendah.
- **Momentum (0–20):** candle sesuai arah + bukan exhaustion spike = tinggi.
- **Volume (0–15):** volume > avg × 1.5 = penuh; di bawah avg = rendah.
- **Structure (0–15):** ada BOS/CHoCH mendukung = tinggi; netral = menengah.
- **Liquidity (0–10):** entry setelah sweep selesai = tinggi; entry ke likuiditas mentah = rendah.
- **ATR (0–5):** volatilitas wajar untuk ukuran posisi = penuh; ekstrem = kurangi.
- **Funding/OI (0–5):** funding tidak extremes berlawanan = aman; OI naik wajar = positif.

## Keunggulan
- Bisa **adaptif**: kalau pasar ranging, factor trend turun otomatis → score turun → skip.
- Threshold bisa di-backtest & di-tune per aset.
- Menghindari over-trading karena butuh konfluensi buat tembus 80.
