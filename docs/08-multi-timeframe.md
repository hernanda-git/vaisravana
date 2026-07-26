# Layer 8 — Multi-Timeframe Confirmation

Robot menyelaraskan analisis antar timeframe. Jangan cuma trade di satu chart kecil.

## Contoh Konflik
```text
5m    → BUY       ✓ (default micro-TF)
10m   → BUY       ✓
15m   → SELL      ✓
1h    → SELL      (ikuti HTF bias)
```
Apakah robot BUY? **Hanya kalau HTF (1h/4h) tidak berlawanan.** Jika HTF bearish,
BUY di LTF ditolak (atau diubah jadi SELL).

> **Tidak ada 1m.** Spesifikasi (`30` §2) memakai **5m / 10m / 15m** sebagai trade-TF.
> 1m terlalu noise untuk target WR ≥85% → dihilangkan.

## Aturan
- Robot **mengikuti HTF** (1h/4h) untuk penentu arah (bias bullish/bearish/range).
- **Trade-TF** (LTF/MTF) = 5m / 10m / 15m → digunakan untuk **timing entry & exit**, bukan arah.
- Arah didorong oleh HTF; LTF hanya mencari presisi masuk (candle rejection, liquidity sweep).

## Workflow
1. **HTF** (1h/4h) → tentukan bias (bullish / bearish / range).
2. **MTF** (15m) → cari setup / struktur masuk.
3. **LTF** (5m/10m) → entry presisi (candle rejection, liquidity sweep).

Contoh LONG: HTF bullish + MTF pullback ke support + LTF muncul bullish candle + volume = BUY berkualitas.
Contoh SHORT: HTF bearish + MTF rally ke resistance + LTF muncul bearish candle + volume = SELL berkualitas.

## Catatan implementasi (robot)
- Analisis berjalan di ≥ 2 timeframe (mis. 1h + 15m + 5m).
- Skor arah HTF diberi bobot lebih (lihat [scoring](10-scoring-system.md), Trend 30%).
- Tolak sinyal LTF yang berlawanan arah HTF (kecuali strategi counter-trend eksplisit, yang
  tetap butuh WR ≥85% di shadow).
