# Layer 7 — ATR (Average True Range)

ATR sangat penting karena **setiap aset punya volatilitas berbeda**.

> Market BTC berbeda dengan PEPE. ATR membantu robot tahu berapa gerakan **normal** market.

## Fungsi ATR
- ATR = rata-rata rentang gerak harian/periode (true range).
- Memberi ukuran **berapa pip/point yang wajar** untuk SL & TP.

## Contoh Salah Kaprah
```
ATR = 100
Robot pasang TP = 1000   ← TIDAK REALISTIS
```
TP 1000 padahal gerakan normal cuma 100 → harga hampir tak pernah menyentuhnya → win rate rendah, risk/reward palsu.

## Cara pakai yang benar
- SL = beberapa × ATR (mis. 1.5× ATR).
- TP = beberapa × ATR dengan target R:R masuk akal (mis. 2R–3R).
- Filter: jangan entry kalau ATR meledak (volatilitas ekstrem) kecuali strategi memang untuk high-volatility.

## Catatan implementasi (robot)
- Hitung ATR(14) standar.
- Skala SL/TP relatif terhadap ATR, bukan angka tetap → adaptif antar aset & regime.
- Engine volatilitas juga bisa pakai **standard deviation** harga sebagai pelengkap.
