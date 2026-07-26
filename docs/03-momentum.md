# Layer 3 — Momentum Candle

Robot jangan hanya melihat **warna** candle. Urutan hijau panjang berturut-turut belum tentu sinyal BUY.

## Jebakan "Hijau Berturut-turut"
```
Green
Green
Green
Green
Huge Green   ← belum tentu BUY
```
Bisa jadi:
- **Sudah overextended** (harga jauh dari rata-rata).
- **Buyer mulai habis** (akumulasi beli terkuras).
- **Whale siap jual** (distribusi diam-diam).

## Deteksi Anomali Body Size

Robot harus mengukur **average body size** dan mencari candle yang menyimpang.

Contoh:
- 20 candle terakhir rata-rata body = **40 point**.
- Tiba-tiba muncul candle body = **200 point**.

Itu **abnormal** (5× rata-rata). Biasanya setelah candle sebesar itu muncul **retracement** (koreksi balik).

```
Avg body (20c) = 40
Spike          = 200  →  Abnormal → waspadai retracement
```

## Cara pakai
- Hitung `avg_body = mean(|close−open|)` dari N candle (mis. 20).
- Flag candle kalau `body > k × avg_body` (k = 3 s.d. 5, sesuaikan aset).
- Candle raksasa di ujung tren = **exhaustion signal**, bukan continuation.
- Gunakan sebagai **filter**: jangan entry BUY tepat setelah spike hijau raksasa di resistance.

## Catatan implementasi (robot)
- Simpan rolling average body size (EMA atau SMA).
- Bandingkan body candle terakhir vs `avg_body × threshold`.
- Gabungkan dengan Layer 1 (struktur) — spike di akhir uptrend = exhaustion; spike di awal breakout = genuine momentum.
