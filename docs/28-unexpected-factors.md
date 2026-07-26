# Faktor yang Tidak Terduga / Tidak Disadari (Blind Spots)

> **Enrichment:** pola production-proven dari `learnernoearner-listener` sudah di-merge ke
> grup B (eksekusi) & D (exchange) — lihat `32-listener-lessons.md` (1000x contract,
> validate→repair→resubmit-once, error categorization). Doc ini adalah kamus referensi.

Riset blind spot. Bot trading futures biasanya hancur **bukan** karena indikator buruk,
tapi karena faktor **eksekusi, data, infrastruktur, exchange, validitas riset, & meta-loop**
yang tak terlihat di teori candlestick.

Setiap item diberi: **dampak**, **deteksi**, **mitigasi**.

---

## A. DATA INTEGRITY (mata rantai paling sering rusak)

| Faktor | Dampak | Deteksi | Mitigasi |
|--------|--------|---------|----------|
| **Stale / frozen feed** (websocket mati tapi app jalan) | Bot trading pakai harga kemarin → order nyasar | Cek age(last_update) > N detik → alarm | Heartbeat + failover ke REST poll |
| **Clock drift** (jam lokal vs exchange beda) | Timestamp salah → salah urut, salah regime | NTP offset > 2s → alarm | Sync NTP berkala, pakai exchange ts |
| **Missing candles / gap** (maintenance, drop koneksi) | Indikator corrupt (SMA/ATR salah hitung) | Jumlah candle < expected per window | Re-fetch history, isi gap, jangan eksekusi saat gap |
| **OHLC aggregation salah** | Wick palsu → false liquidity sweep | Bandingkan kline vs trade-by-trade | Gunakan trade aggregation sendiri, bukan kline mentah |
| **Feed paper ≠ live** | Backtest bagus, live rugi | Diff metrik feed A vs B | Satu sumber data untuk sim & live |
| **Point-in-time error** | Indikator lihat data masa depan | Audit tiap field "kapan tersedia" | Tidak ada field close di candle belum selesai |

## B. EXECUTION / MICROSTRUCTURE

| Faktor | Dampak | Deteksi | Mitigasi |
|--------|--------|---------|----------|
| **Slippage riil > ekspektasi** | Expectancy turun drastis | realized_slippage vs assumed | Catat slippage tiap fill, feed ke evaluator |
| **Maker vs Taker fee** | Strategi kira dapet rebate, kena fee | fill_type != expected | Cek order type; limit belum tentu maker |
| **Partial fill** | Posisi setengah → SL/TP salah hitung | filled_qty < order_qty | State machine order, tunggu full/timeout |
| **Order rejected** (harga gerak, margin kurang, limit posisi) | Entry kelewat / posisi ngambang | status == REJECTED | Retry logic + fallback, log alasan |
| **Order stuck / unack** | Pikir open, padahal nggak | no ack dalam T ms | Timeout + query status, jangan double-send |
| **Thin book market order** | Fill di harga jauh | spread lebar saat eksekusi | Cek spread (Layer decision tree: "spread aman?") |
| **Queue position (limit order)** | Limit nggak keisi saat harga lewat | priority tidak dapat | Estimasi fill prob, fallback ke market |
| **1000x contract mapping** (BONK/PEPE/SHIB/FLOKI) | Symbol & quantity salah → reject/posi ngaco | lookup `exchangeInfo` gagal | SymbolRegistry: user pair → exchange symbol (1000BONKUSDT), qty integer stepSize=1 |
| **LIMIT SELL di bawah market = BUKAN SL** | SL "valid" langsung terisi → posi tertutup instan | posisi close saat baru buka | SL pakai conditional STOP (reduceOnly), bukan LIMIT asal |
| **Conditional order diblokir (-4120)** | STOP/TP gagal ditempatkan | HTTP -4120 | Fallback: position-manager polling mark price → market close saat breach |
| **Precision / minNotional (-1111)** | Order reject low-price coin | filter cache miss | Lazy-load filter on miss; round price→tickSize, qty→stepSize, loop `qty×price ≥ minNotional` |
| **Validate → Repair → Resubmit-once** | Repair non-deterministik / LLM ikut reparasi | repair path ambigu | Pipeline tetap: validate_order → kalau reject, re-derive dari filter, revalidate, resubmit **1x**; masih invalid → `VALIDATION_SKIP`. Reasoning/LLM TDK di path repair |
| **Error categorization** | Retry salah jenis → loss waktu / auth leak | tak terklasifikasi | `401/403` AUTH→fail-fast (jgn retry); `429` RATE_LIMIT→backoff; `5xx` SERVER→retry; network→`PENDING`; order fail→`FAILED`+reason |

## C. INFRASTRUKTUR / LATENCY

| Faktor | Dampak | Deteksi | Mitigasi |
|--------|--------|---------|----------|
| **Network latency ke exchange** | Sinyal telat → entry di harga lain | RTT > threshold | Region dekat exchange, ret/cache |
| **Process crash / OOM / restart** | Posisi terbuka tanpa manajemen | App down | Supervisor (systemd), restart otomatis + recovery state |
| **Cloud spot reclaim / instance kill** | Bot mati tiba-tiba | Instance terminated | Dedicated/stable instance, multi-AZ |
| **DNS / connection pool exhaust** | Gagal konek beruntun | Error rate naik | Pool limit, backoff, retry jeda |
| **NTP / time sync** | Lihat A.Clock drift | offset monitor | systemd-timesyncd |

## D. EXCHANGE-SPECIFIC RISK (futures unik)

| Faktor | Dampak | Deteksi | Mitigasi |
|--------|--------|---------|----------|
| **Auto-Deleverage (ADL)** | Posisi ditutup paksa lawan arah, di harga buruk | rank ADL tinggi | Hindari posi besar di akhir, monitor ADL indicator |
| **Funding rate spike** | Hold long saat funding + tinggi = rugi periodik | funding rate API | Tutup sebelum funding kalau ekstrem, atau net-fee model |
| **Liquidation cascade / socialized loss** | Waktu stres, slippage ekstrem, loss sosial | Funding/vol anomali | Kurangi leverage di high_vol, hindari saat berita |
| **Mark price ≠ last price** | SL kena karena wick mark price, bukan last | SL pakai mark | Pahami SL engine exchange, pakai last atau mark sesuai |
| **Exchange freeze / insolvency** (FTX-style) | Dana & posi hilang | News / withdraw suspend | Diversifikasi exchange, withdraw profit rutin |
| **API rate limit (429 / weight)** | Request ditolak → data/order gagal | HTTP 429 | Weight budget, cache, backoff eksponensial |
| **IP ban** | Bot diskonek total | Ban notice | Rotasi proxy hati-hati, jaga request hygiene |
| **Symbol delist / contract expiry** | Posisi force-close | Announcement API | Filter symbol berumur pendek, netPosition sebelum expiry |
| **Maintenance window** | Tidak bisa order | Schedule exchange | Kalender maintenance, pause bot |

## E. VALIDITAS RISET / BACKTEST (kenapa sim bagus tapi live rugi)

| Bias | Penjelasan | Mitigasi |
|------|------------|----------|
| **Look-ahead bias** | Pakai data yang belum tersedia saat itu | Audit ketersediaan tiap field (A) |
| **Overfitting / curve-fitting** | Param pas di hist, gagal live | Walk-forward, out-of-sample, shrinkage |
| **Survivorship bias** | Hanya trade coin yang "selamat" | Pakai universe delisted juga |
| **Non-stationarity / model decay** | Regime berubah → param usang | Sentinel re-eval berkala, regime detector |
| **Biaya transaksi diabaikan** | Net negatif setelah fee | Selalu masukkan fee+slippage di sim |
| **Multiple-comparison (p-hack)** | Coba 1000 param, yang 1 "signifikan" kebetulan | Penalty complexity, confirmasi OOS |
| **OOS degradation** | Performa turun di data baru | Monitor live vs backtest gap |

## F. RISIKO POSISI / PORTOFOLIO (level atas)

| Faktor | Dampak | Mitigasi |
|--------|--------|----------|
| **Insufficient margin saat add** | Gagal scale-in | Cek free margin pra-order |
| **Korelasi lintas symbol** | Kira diversifikasi, padahal semua BTC-correlated | Hitung correlation matrix, batasi eksposur correlated |
| **Leverage decay / compounding** | Saldo turun cepat saat loss beruntun | Daily loss limit (sudah ada) + portfolio VaR |
| **Funding bleed sideways** | Hold lama di range = rugi fee+funding | Batasi max hold time |
| **Concentration** | Semua bot/akun di 1 symbol | Diversifikasi, cap per-symbol |

## G. META-LOOP RISK (bahaya khusus sistem dua-bot kita)

Ini yang PALING penting karena sistem kita punya auto-correct:

| Risiko | Penjelasan | Mitigasi |
|--------|------------|----------|
| **Reward hacking / metric gaming** | Sentinel optimalkan WinRate tapi hancurkan Profit Factor | Evaluasi pakai **komposit** (PF + DD + expectancy), bukan 1 metrik |
| **Overfit ke window terakhir** | Sentinel kejar noise terkini → local optimum | Window cukup panjang, regularization, cooldown perubahan |
| **Oscillation / lupa config bagus** | Naik-turun terus antar versi | Rate-limit + bound (sudah di 25), deteksi osilasi |
| **Shadow == Live data = in-sample!** | Shadow pakai data sama → bukan validasi sungguhan | Shadow butuh **forward** testing / paper, beda jam, atau sim eksekusi realistis |
| **Simulated slippage terlalu optimis** | Shadow menang, live rugi | Pakai slippage riil historis di sim |
| **Disabling safety filter musiman** | Sentinel matiin filter yang kebetulan "rugi" kemarin tapi krusial saat crash | Filter safety (daily_loss, kill switch) TIDAK boleh diubah Sentinel |
| **Black-swan blindness** | Loop otomatis nggak kenal event ekstrem | Circuit breaker event-driven + human alert wajib |
| **Sentinel confidence trap** | Manusia stop awas karena "bot awasi bot" | Tetap ada notifikasi + periodic human review |

## H. TATA KELOLA / KEAMANAN / LEGAL

| Faktor | Mitigasi |
|--------|----------|
| **API key leak** | Read-only key terpisah, IP whitelist, vault secret |
| **Multi-account copy-paste error** | Namespace config per akun, lint |
| **No runbook / disaster recovery** | Tulis runbook: cara kill, rollback, restore state |
| **Alert fatigue** | Prioritas alert, jangan spam; ringkasan harian |
| **Tax / compliance** | Log PnL per trade (sudah di telemetry), export laporan |
| **Over-trust automation** | Mode observe-only berkala, human audit trail |

---

## Catatan: kamus ini hidup, bukan final

Daftar di atas adalah **kamus referensi**, bukan aturan kaku. Bot/Sentinel menggunakan
**Reasoning Engine (5W1H)** dari `29-dynamic-reasoning-5w1h.md` yang boleh menghasilkan
**hipotesis novel (H3) di luar daftar ini**. Tiap novel finding yang terbukti → diajukan
penambahan entri ke kamus ini (peer-review manusia di mode supervised).

Jadi: `28` = apa yang *sudah* kita tahu. `29` = cara bot *menemukan* yang belum kita tahu.
Bot tidak boleh terpacu hanya pada faktor konstan di sini — itu sebabnya `29` ada.
