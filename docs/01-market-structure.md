# Layer 1 — Market Structure (Paling Penting)

Ini fondasi. Robot **harus** tahu market sedang apa sebelum menjalankan indikator apa pun.

> Kalau robot belum bisa membedakan struktur pasar, indikator apa pun biasanya akan sering rugi.

## 5 Kondisi Market

| Kondisi | Ciri | Aksi biasa |
|---------|------|-----------|
| **Uptrend** | Higher High + Higher Low berulang | Cari BUY (dip) |
| **Downtrend** | Lower High + Lower Low berulang | Cari SELL (bounce) |
| **Sideways / Range** | Harga memantul dalam box | Tunggu breakout (BOS) |
| **Breakout** | Tembus level penting dgn volume | Ikut arah break |
| **Fake Breakout** | Tembus lalu langsung mundur | Jangan ikut; waspadai reversal |

## Pola Pengenalan

### Uptrend
```
Higher High
Higher Low
Higher High
Higher Low
   → UPTREND
```
Harga membuat puncak yang makin tinggi dan dasar yang makin tinggi.

### Downtrend
```
Lower High
Lower Low
Lower High
Lower Low
   → DOWNTREND
```
Harga membuat puncak yang makin rendah dan dasar yang makin rendah.

## Mengapa ini urutan pertama

Struktur pasar menentukan **bias arah**. Indikator momentum (RSI, MACD) hanya berguna kalau arahnya selaras dengan struktur. Di uptrend, RSI "overbought" sering gagal karena tren kuat; di sideways, RSI berbalik di extrem lebih reliable.

## Catatan implementasi (robot)
- Simpan N swing high / swing low terakhir.
- Bandingkan tinggi rendahnya untuk klasifikasi tren.
- Deteksi **Break of Structure (BOS)** = harga menembus swing high/low terakhir → konfirmasi pergantian arah mikro.
- Deteksi **Change of Character (CHoCH)** = pertama kali struktur berbalik setelah range → sinyal awal reversal.
