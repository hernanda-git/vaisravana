# Layer 8 — Multi-Timeframe Confirmation

Robot harus menyelaraskan sinyal antar timeframe. Jangan cuma trade di satu chart kecil.

## Contoh Konflik
```
1m    → BUY       ❌ (terlalu noise untuk target WR tinggi)
5m    → BUY       ✓ (default micro-TF)
15m   → SELL      ✓
1h    → SELL      (ikuti HTF)
```
Apakah robot BUY? **Kemungkinan besar JANGAN.**

## Aturan
- Robot sebaiknya **mengikuti timeframe yang lebih besar** (HTF = Higher Timeframe).
- Timeframe kecil (LTF, mis. 1m/5m) dipakai untuk **timing entry**, bukan penentu arah.
- Arah didorong oleh HTF (15m/1h/4h).

## Workflow yang disarankan
1. **HTF** (1h/4h) → tentukan bias (bullish/bearish/range).
2. **MTF** (15m) → cari setup / struktur masuk.
3. **LTF** (1m/5m) → cari entry presisi (candle rejection, liquidity sweep).

Contoh: HTF bullish + MTF pullback ke support + LTF muncul hammer + volume = entry BUY berkualitas.

## Catatan implementasi (robot)
- Analisis berjalan di ≥ 2 timeframe (mis. 15m + 5m, atau 1h + 15m).
- Skor arah HTF diberi bobot lebih (lihat [scoring](10-scoring-system.md), Trend 30%).
- Tolak sinyal LTF yang berlawanan arah HTF (kecuali strategi counter-trend eksplisit).
