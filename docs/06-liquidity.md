# Layer 6 — Liquidity

Ini yang dipakai trader besar. Harga sering bergerak **bukan karena indikator**, tapi karena mencari likuiditas.

## Konsep Liquidity
Likuiditas = tempat order tertunda (stop-loss, take-profit, entry pending) menumpuk. Market cenderung "dihisap" ke tempat itu karena:
- Stop-loss di atas high ditarik saat harga naik → menjadi buy market order yang mendorong harga.
- Begitu tersapu, dorongan habis → harga berbalik.

## Liquidity Grab (Stop Hunt)
```
High
 ^^^^^^^^^^
 stop loss semua orang
        ↑ harga naik sedikit
        → ambil liquidity
        → langsung TURUN
```
1. Harga naik menembus high (menyapu stop buyer / stop-loss seller di atas).
2. Likuiditas terserap.
3. Tanpa dorongan lanjut, harga **langsung turun** (biasanya membentuk CHoCH / false breakout).

Istilah lain: **stop hunt**, **liquidity sweep**.

## Pola yang perlu dikenali (untuk engine likuiditas)
- **Equal highs / equal lows** — dua puncak/dasar sejajar = pool likuiditas.
- **Liquidity sweep** — harga tembus equal high/low lalu balik.
- **Fair Value Gap (FVG)** — celah di antara 3 candle (imbalance) yang cenderung ditutup (ditarik balik) nanti.

## Catatan implementasi (robot)
- Tandai equal highs/lows & cluster stop (di atas resistance / di bawah support).
- Jangan panik ikut breakout yang tipis volume (Layer 4) — bisa jadi sweep.
- Cari entry setelah sweep selesai + muncul rejection candle (Layer 2) + CHoCH (Layer 1).
