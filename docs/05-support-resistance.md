# Layer 5 — Support & Resistance

Robot harus tahu **area penting** di chart, bukan cuma harga sekarang.

## Konsep
- **Support** = area harga di mana buyer berulang kali masuk → harga cenderung mantul naik.
- **Resistance** = area harga di mana seller berulang kali muncul → harga cenderung ditolak turun.

## Contoh
```
100  ────────────  ditolak 8 kali
100  ────────────  → 100 = RESISTANCE kuat
```
Semakin sering suatu level ditolak (semakin banyak "test"), semakin kuat level itu.

## Breakout Validation
Kalau harga akhirnya **breakout** level tersebut, ia baru dianggap valid kalau:
- **Volume besar** (lihat Layer 4), DAN
- **Close di luar level** (bukan cuma sumbu/wick), DAN
- (opsional) ada retest yang bertahan di atas level → konfirmasi jadi support baru.

## Catatan implementasi (robot)
- Simpan level S/R dari swing high/low + zona konsolidasi.
- Beri "weight" tiap level berdasar jumlah test & volume saat test.
- Hindari entry melawan level kuat; cari entry **saat harga menyentuh support dalam tren naik** (buy the dip).
- Sering overlap dengan [Layer 6 Liquidity](06-liquidity.md): level S/R = tempat stop-loss orang menumpuk.
