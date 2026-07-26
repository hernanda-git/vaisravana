# Layer 4 — Volume Confirmation

Ini sering dilupakan, padahal penting untuk memvalidasi candle.

## Aturan Dasar

| Skenario | Validitas |
|----------|-----------|
| Bullish candle + **volume naik** | Lebih valid (buyer sungguhan) |
| Bullish candle + **volume kecil** | Lebih lemah (bisa fake / lacks conviction) |
| Bearish candle + **volume naik** | Tekanan seller nyata |
| Breakout + **volume besar** | Breakout valid |
| Breakout + **volume tipis** | Waspadai fake breakout |

## Prinsip
Volume = **jumlah partisipasi**. Candle besar tanpa volume = gerakan kosong (mudah dibalik). Candle besar dengan volume = ada dana nyata di baliknya.

## Catatan implementasi (robot)
- Bandingkan volume candle vs `avg_volume` (20–50 periode).
- Breakout dianggap valid hanya kalau `volume > avg_volume × 1.5` (atau threshold).
- Untuk aset dengan data orderflow: gunakan **volume delta** (buy volume − sell volume) bila tersedia — lebih tajam dari volume mentah.
- Lihat juga [docs/06-liquidity.md](06-liquidity.md) — volume besar sering muncul pas liquidity di-grab.
