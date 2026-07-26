# Glossary & Cross-Reference — VaiÅravaá¹a Trading Bot

Daftar istilah + pemetaan tiap konsep ke dokumen sumber. Dipakai agar tidak ada
istilah mengambang antar doc.

## Istilah Kunci

| Istilah | Arti | Sumber |
|---------|------|--------|
| **VaiÅravaá¹a-Trader** | Bot aktif (eksekusi). Default PAPER. | `20`, `21`, `30` |
| **VaiÅravaá¹a-Sentinel** | Bot koreksi (eval/review/correct/improve + reason). | `20`, `24`, `29` |
| **Reasoning Engine** | Modul 5W1H (layer ke-10, "otak" Sentinel). | `29` |
| **Unreal / PAPER** | Mode simulasi; semua win/loss dicatat, tanpa uang nyata. | `21`, `30` |
| **SHADOW** | Param kandidat jalan paralel, tidak eksekusi. | `24`, `25`, `30` |
| **LIVE** | Uang nyata; hanya setelah gate `30` §6. | `30` |
| **Parameter surface** | Param yang BOLEH diubah Sentinel (berbatas). | `21` |
| **Composite Health Score** | Metrik gabungan cegah reward hacking. | `23`, `24` |
| **BOS / CHoCH** | Break of Structure / Change of Character. | `01`, `11` |
| **FVG** | Fair Value Gap (imbalance 3 candle). | `06`, `11` |
| **Liquidity grab / sweep** | Harga sapu stop/likuiditas lalu berbalik. | `06` |
| **ADL** | Auto-Deleverage (exchange tutup paksa). | `28-D`, `30` |
| **Funding rate** | Biaya hold posi per interval (perpetual). | `28-D`, `30` |
| **ATR** | Average True Range — volatilitas. | `07` |
| **R-Multiple** | Profit dibagi risk (SL). R:R ~1.5 target. | `10`, `30` |
| **Spread guard** | Skip entry kalau spread > 3bps (low-TF krusial). | `30` |
| **Limit order (maker)** | Order di sekitar mid, hindari taker-fee/slippage. | `30` |
| **Position sizing (risk-based)** | `size = risk_usd / sl_distance`. | `30`, `21` |
| **Kill switch** | Hentikan entry/tutup posi saat kondisi bahaya. | `25`, `30` |
| **Rollback** | Kembali ke config versi sebelumnya. | `25` |
| **5W1H** | WHO/WHAT/WHEN/WHERE/WHY/HOW — scaffold reasoning. | `29` |
| **H3 (novel)** | Hipotesis di luar kamus `28`. | `29` |
| **Win-Rate gate** | **WR ≥ 85% per pair×TF** di shadow sebelum live. | `30` §6, `23`, `26` |
| **ShadowTrader(P,TF)** | Shadow trader independen per pair×TF. | `30` §8, `ARCHITECTURE.md` §5 |
| **Universe (all pairs)** | Semua Binance USDT perp, liquidity-filtered. | `30` §2, `ARCHITECTURE.md` §5 |
| **Two-Layer Gate** | Gate A (pre-scoring) + Gate B (post-scoring hard clamp). | `25`, `30` §3, `32` |
| **decisions_log** | Keputusan internal (pengganti signal) + `confidence_pct`. | `30` §4, `22` |
| **trade_logs** | Trade yang masuk posisi: ts_filled/tp/closed, win/loss bool, win%/loss%. | `30` §4, `22` |
| **results_log** | Historis: evaluation/reasoning/thinking/correction/improvement/review. | `30` §4, `26` |
| **correlation_id** | Trace ID mengalir sepanjang pipeline. | `22`, `30` §4, `32` |
| **Position Monitor** | Background loop 10s: SL dual, self-heal, orphan. | `30` §3, `25`, `32` |
| **1000x contract** | Binance meme-coin (BONK/PEPE/SHIB/FLOKI) butuh mapping+rounding khusus. | `28-B`, `30` §2/§3, `32` |

## Pemetaan Dokumen (dependency)

```
01-11  (edukasi 8 layer + arsitektur 9 engine + scoring)
   │
   ▼
20  overview dua-bot ──┬── 21 parameter surface (bound)
   │                   ├── 22 telemetry (skema log)
   │                   ├── 23 evaluation (metrik + composite health)
   │                   ├── 24 sentinel (reason→review→correct→improve)
   │                   ├── 25 safety (shadow/bound/rollback/kill-switch)
   │                   ├── 26 documentation output (4 file format)
   │                   ├── 27 feedback loop
   │                   ├── 28 blind spots (kamus)
   │                   ├── 29 dynamic reasoning (5W1H)
   │                   └── 30 concrete spec (INSTANSIASI FINAL, stability-first)
```

**Aturan rujukan:** `30` adalah sumber nilai konkret (default, bound, skema).
`21` adalah bound resmi. Semua contoh di `23/24/26` harus sesuai nilai `30`/`21`.

## Open Questions / Belum Diputus (untuk implementasi)
1. **Exchange** — sudah diputus: **Binance** (semua USDT perpetual). ✓
2. **Timeframe** — sudah diputus: **5m / 10m / 15m**. ✓
3. **Target WR** — sudah diputus: **≥ 85% per pair×TF** di shadow. ✓
4. **Universe** — semua pair, tapi butuh **liquidity filter threshold** pasti (spread/vol).
5. **DB** — SQLite (lokal) vs Postgres (multi-instance). `30` sebutkan dua-duanya.
6. **Bahasa** — Python disarankan (cepat); Go kalau latency kritis.
7. **Notifikasi channel** — Telegram/Discord.
8. **Backtest engine** — framework terpisah utk validasi sebelum PAPER.
9. **Fee tier pasti** per pair (pengaruhi expectancy & maker-ratio).
10. **global_max_live_pairs** default 5 — bisa disesuaikan saat live testing.

> Doc ini hidup: update saat keputusan di atas diambil.
