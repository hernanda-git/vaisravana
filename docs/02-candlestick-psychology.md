# Layer 2 — Candlestick Psychology

Setiap candle punya arti. Candle bukan cuma warna — ia menceritakan **siapa yang menang** (buyer vs seller) selama periode itu.

## Tipe Dasar

### Bullish Candle
```
Open
  │
  │
  │
Close
```
Buyer menang. **Semakin besar body, semakin kuat momentum** buyer.

### Bearish Candle
```
Close
  │
  │
  │
Open
```
Seller menang. Semakin besar body, semakin kuat tekanan seller.

### Doji
```
Open == Close
```
Buyer dan seller seimbang. Biasanya tanda market **sedang ragu** (indecision). Sering muncul di puncak/pangkalan atau sebelum breakout besar.

## Pola Reversal

### Hammer
```
     Body
      ██
      ██
      │
      │
      │
```
- Seller sempat menekan (sumbu bawah panjang).
- Buyer mengambil alih, tutup dekat open/high.
- **Bullish reversal** — terutama kalau muncul di support.

### Shooting Star
```
      │
      │
      │
      ██
      ██
     Body
```
- Kebalikan hammer (sumbu atas panjang).
- Buyer dorong naik, seller tarik turun, tutup dekat open/low.
- **Bearish** — terutama kalau muncul di resistance.

## Prinsip
- **Body** = kekuatan pihak pemenang.
- **Sumbu (wick)** = rejection / penolakan harga di area itu.
- Sumbu panjang ke satu arah = ada yang "ditolak" di situ (sering jadi petunjuk liquidity / support-resistance).

## Catatan implementasi (robot)
- Hitung body size = |close − open|.
- Hitung wick ratio = panjang sumbu / total range.
- Hammer/shooting star = body kecil + 1 wick panjang (≥ 2× body) + posisi wick benar (bawah untuk hammer).
