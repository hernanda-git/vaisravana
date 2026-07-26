# Bot Aktif — VaiÅravaá¹a-Trader (Parameter Surface)

Sentinel hanya boleh mengubah **parameter surface** yang didefinisikan di sini.
Ini adalah "kontrak" yang menjamin auto-correction tidak merusak logika inti.

## Apa yang BOLEH diubah Sentinel

| Parameter | Tipe | Bound (contoh) | Dampak |
|-----------|------|----------------|--------|
| `weights.trend` | float | 0.20 – 0.40 | Bobot skor tren |
| `weights.momentum` | float | 0.10 – 0.30 | Bobot momentum |
| `weights.volume` | float | 0.05 – 0.25 | Bobot volume |
| `weights.structure` | float | 0.05 – 0.25 | Bobot market structure |
| `weights.liquidity` | float | 0.00 – 0.20 | Bobot likuiditas |
| `weights.atr` | float | 0.00 – 0.15 | Bobot volatilitas |
| `weights.funding_oi` | float | 0.00 – 0.15 | Bobot funding/OI |
| `entry_threshold` | float | 0.85 – 0.92 | Skor min. entry (default **0.90**, high-WR tuned) |
| `watch_threshold` | float | 0.78 – 0.85 | Skor min. watchlist (default 0.80) |
| `sl_atr_mult` | float | 0.8 – 2.0 | Stop loss = k × ATR (default **1.0**, sangat ketat) |
| `tp_atr_mult` | float | 1.0 – 2.0 | Take profit = k × ATR (default **1.05**, R:R ~1.0) |
| `max_leverage` | int | 1 – 3 | Batas leverage (default **2**, cap keras) |
| `cooldown_after_loss` | int (menit) | 0 – 60 | Lock setelah loss (default 10) |
| `daily_loss_limit_pct` | float | 0.3% – 2% | Kill switch harian (default **0.5%**) |
| `risk_per_trade_pct` | float | 0.10% – 0.50% | Risiko per trade utk sizing (default **0.25%**) |
| `max_position_notional_pct` | float | 10% – 60% | Cap notional vs free margin (default 50%) |
| `winrate_gate_pct` | float | 80% – 95% | WR shadow wajib sebelum live (default **85%**) |
| `min_trades_for_promote` | int | 100 – 500 | Min trade unreal per pair×TF (default **200**) |
| `global_max_live_pairs` | int | 1 – 20 | Cap pair×TF live simultan (default **5**) |
| `filter.requement_<name>` | bool | on/off | Nyalakan/matikan filter |
| `regime_params.<regime>.*` | object | per-regime | Param spesifik regime |

> **Syarat konsistensi:** `Σ weights == 1.0`. Sentinel wajib normalisasi ulang setelah mengubah bobot.

## Apa yang TIDAK BOLEH diubah Sentinel
- Logika engine (algoritma deteksi BOS/CHoCH, FVG, dll).
- Kode eksekusi order ke exchange.
- Skema telemetry (struktur log).
- Threshold keselamatan hard (mis. `daily_loss_limit_pct` min 0.5% tidak boleh dihapus).
- Strategi baru yang belum pernah di-shadow.

Perubahan di luar surface ini = butuh **intervensi manusia** (deploy kode baru).

## Mode Operasi Trader (DEFAULT = PAPER/UNREAL)
Sesuai spec konkret `30-concrete-spec.md` — **bot hidup di PAPER dulu**, semua win/loss
dicatat di tabel `trade_logs`. Live hanya setelah gate promosi terpenuhi.

| Mode | Arti |
|------|------|
| `PAPER` (unreal) | **DEFAULT** — simulasi, log win/loss nyata ke DB, tidak ada uang nyata |
| `SHADOW` | Trader kedua jalan paralel dgn param kandidat, tidak eksekusi |
| `LIVE` | Eksekusi uang nyata — HANYA setelah track record PAPER memenuhi gate |

Spesifikasi konkret (symbol, TF, SL/TP, risk) ada di `30-concrete-spec.md`. Doc ini
(`21`) hanya mendefinisikan **apa yang boleh diubah Sentinel**.

## State yang disimpan Trader
- Konfigurasi aktif (snapshot param saat ini).
- Riwayat konfigurasi (versi + siapa yang ubah + alasan).
- Status mode (LIVE/PAPER/SHADOW).
