# Dynamic Reasoning — Berbasis Skenario 5W1H

Paradigma: jangan kunci bot pada **faktor konstan** (if X then Y). Sebaliknya, bot menyusun
**skenario hidup** lewat 5W1H, lalu **menalar secara dinamis** — menghubungkan bukti lintas
layer, membangun cerita kausal, dan menentukan tindakan. Ini menangani situasi **baru**
yang tidak ada di daftar `28`.

> Faktor di `28` itu *kamus*, bukan *aturan*. 5W1H itu *cara berpikir* yang pakai kamus
> tapi bisa juga menemukan kata baru saat diperlukan.

---

## 1. Kenapa tidak boleh statis?

| Reasoning Statis | Reasoning Dinamis (5W1H) |
|------------------|--------------------------|
| "Kalau slippage > 10bps → reject" | "Kenapa slippage naik? Kapan? Di aset mana? Apa penyebabnya — likuiditas tipis atau feed lag?" |
| Gagal di situasi tak terduga | Bangun skenario, cari analogi, adaptasi |
| Over-fit ke aturan | Generalisasi lewat struktur pertanyaan |
| Sentinel cuma patch angka | Sentinel *menjelaskan* lalu bertindak |

---

## 2. Scaffold 5W1H (konteks skenario)

Bot mengisi kerangka ini tiap kali ada anomali / event / keputusan:

| W | Pertanyaan dalam konteks trading | Contoh isian |
|---|----------------------------------|--------------|
| **WHO** | Siapa/apa yang terlibat? (aktor: trader, market maker, exchange, bot sendiri, Sentinel) | "Exchange X melakukan ADL pada posisi long kita" |
| **WHAT** | Apa yang terjadi? (event, gejala, metrik menyimpang) | "Expectancy turun -0.9R di regime high_vol" |
| **WHEN** | Kapan? (waktu, fase sesi, durasi, berulang atau sekali) | "Jam 02:00 UTC, sesi illiquid, berulang 3 hari" |
| **WHERE** | Di mana? (symbol, timeframe, komponen pipeline, venue) | "BTCUSDT 5m, di Risk Manager, venue live" |
| **WHY** | Mengapa? (hipotesis kausal — ini inti nalar) | "Likuiditas tipis + leverage tinggi → slippage cascade" |
| **HOW** | Bagaimana merespons? (tindakan, ukuran, verifikasi) | "Turunkan leverage high_vol, verifikasi di shadow 100 trade" |

Bukan sekadar mengisi — **WHY** memaksa bot mencari penjelasan kausal, bukan cuma korelasi.

---

## 3. Alur Reasoning Dinamis (bukan rule-matching)

```
ANOMALI / EVENT
   │
   ▼
[1] BUILD SCENARIO (isi 5W1H dari telemetry + market ctx)
   │
   ▼
[2] MENTAL MODEL — panggil layer relevan (1..8 + 28) sebagai LENSA,
   │   bukan sebagai aturan. Tanya: "layer mana yang menjelaskan ini?"
   ▼
[3] EVIDENCE GATHER — kumpulkan bukti pendukung & pembantah
   │   (volume, ATR, feed age, fill type, regime, dll)
   ▼
[4] HYPOTHESIS — susun 1-3 cerita kausal. Nilai tiap hipotesis.
   │   H1: ... (prob tinggi)  H2: ... (prob sedang)  H3: ... (out-of-list, novel)
   ▼
[5] ACTION — pilih respons teraman yg menguji hipotesis dominan.
   │   Selalu lewat guardrail (bound, shadow, safety immutable).
   ▼
[6] REVIEW — pasca-tindakan, apakah skenario terbukti? Update dokumentasi.
```

Kunci: langkah [4] **mengizinkan hipotesis di luar daftar 28** (H3) — itulah "dinamis".

---

## 4. Lima Skenario Kerja (5W1H dipakai nyata)

### Skenario 1 — Feed membeku saat berita volatil
- **WHO**: WebSocket exchange mati; bot kita masih "jalan".
- **WHAT**: 3 order entry dieksekusi di harga 90 detik lalu; PnL anomali.
- **WHEN**: Saat rilis CPI (acara berjadwal, volatil).
- **WHERE**: Live venue, komponen data feed.
- **WHY (H1)**: Feed frozen → bot pakai harga stale → entry nyasar. (kamus 28-A)
- **HOW**: Heartbeat detect age>2s → HENTIKAN entry, alarm, failover REST. Rollback posi anomali. Sentinel dokumentasikan sebagai insiden data, bukan salah sinyal.

### Skenario 2 — Shadow menang, Live rugi (meta-loop suspect)
- **WHO**: Sentinel (shadow) vs Trader (live).
- **WHAT**: Shadow expectancy +1.1R, Live -0.4R padahal param sama.
- **WHEN**: Sejak promosi v1.4.5, 2 hari terakhir.
- **WHERE**: Sama symbol/tf, tapi beda jam eksekusi.
- **WHY (H1)**: Shadow pakai data in-sample (bukan validasi sungguhan). (28-G)
       **(H2)**: Slippage live > asumsi shadow (28-B).
       **(H3 novel)**: Exchange ubah fee tier setelah volume naik → taker fee 2× lipat, shadow tidak tahu.
- **HOW**: Tolak promosi lanjutan. Jalankan shadow di **forward/paper jam beda** + masukkan fee riil. Jika H3 benar → tambah "fee tier monitor" ke telemetry (kata baru di kamus).

### Skenario 3 — Funding melonjak + ADL rank naik
- **WHO**: Exchange (funding), market (long squeeze), posisi kita.
- **WHAT**: Funding +0.3%/8j, ADL rank kita naik ke 4/5.
- **WHEN**: Akhir pekan, sesi AS tutup.
- **WHERE**: BTCUSDT perpetual, Risk Manager.
- **WHY (H1)**: Posisi long besar di akhir window funding → kena biaya + rawan ADL. (28-D)
- **HOW**: Tutup sebagian sebelum funding, turunkan leverage di high_vol, notif manusia. Sentinel catat di eval_report bagian exchange-risk.

### Skenario 4 — WinRate naik tapi Profit Factor turun
- **WHO**: Strategi kita (banyak trade kecil menang).
- **WHAT**: WR 68%↑ tapi PF 0.9↓, DD membesar.
- **WHEN**: Sejak Sentinel naikkan entry_threshold (filter ketat → trade lebih sedikit, lebih "aman" tapi TP terlalu jauh).
- **WHERE**: Scoring + TP multiplier.
- **WHY (H1)**: Reward hacking: filter ketat naikkan WR tapi TP tidak tersentuh → R negatif. (28-G)
- **HOW**: Gunakan **Composite Health Score** (bukan WR). Tolak karena Health turun. Sentinel kembalikan tp_atr_mult, bukan ubah threshold lagi.

### Skenario 5 — DIVERGENSI CROSS-VENUE (benar-benar baru, luar daftar 28)
- **WHO**: Exchange A vs Exchange B (kedua terhubung ke bot).
- **WHAT**: Harga BTC di A drop 4% tiba-tiba, di B normal. Sinyal kita (pakai A) trigger SELL panik.
- **WHEN**: 03:14 UTC, 40 detik.
- **WHERE**: Venue A feed, komponen market data.
- **WHY (H1)**: Liquidity grab / wick biasa di A. (28-6)
       **(H2)**: Outage sebagian di A → harga "stuck" lalu gap.
       **(H3 novel)**: A mengalami *partial matching-engine halt* — bukan wick, bukan outage penuh, tapi engine match terhenti sementara sehingga trades tidak terjadi & harga membeku lalu loncat.
- **HOW**: Cek cross-venue consistency (harga B sebagai referensi). Jika A menyimpang > threshold vs B → anggap A corrupt, PAUSE trading di A, pakai B. Sentinel dokumentasikan pola "partial engine halt" sebagai entri kamus BARU (28 akan bertambah dinamis).

> Skenario 5 membuktikan: framework tidak butuh H3 sudah ada di daftar. Bot **menemukan**
> kategori baru lewat reasoning, lalu menambahkannya ke dokumentasi. Itulah "tidak terpacu
> faktor konstan".

---

## 5. Reasoning Engine (lapisan baru di atas Evaluator)

Tambahan ke arsitektur `11` / Sentinel `24`: modul **Reasoning Engine** yang:

1. Menerima event/anomali dari telemetry.
2. Mengisi 5W1H (otomatis dari data + manual kalau ambigu).
3. Menjalankan alur §3 (build → model → evidence → hypothesis → action → review).
4. Mengizinkan hipotesis novel (H3) — tidak dibatasi kamus `28`.
5. Menghasilkan **narrative** yang masuk ke dokumentasi (`26`): "Apa yang terjadi, kenapa, apa tindakan, apa pelajaran".
6. Setiap novel finding → usulkan penambahan ke `28` (peer-review oleh manusia di mode supervised).

### Guardrail Reasoning (biar nggak ngawur)
- Reasoning tetap harus **lewat safety immutable** (daily_loss, kill switch, data-feed monitor tidak boleh dimatikan — `24`/`25`).
- Hipotesis novel tetap diuji di **shadow** sebelum promosi.
- Sentinel harus bisa **menjelaskan** tiap tindakan dalam bahasa manusia (auditability).
- Kalau bukti tidak cukup untuk WHY → default ke **amannya** (pause/reduce), jangan nekat.

---

## 6. Perbedaan dengan dokumen sebelumnya
- `28` = **kamus faktor** (statis, referensi).
- `29` (ini) = **cara bernalar** (dinamis, generatif) yang memakai kamus tapi bisa melampauinya.
- `23` evaluator = hitung metrik. `29` reasoning = **interpretasi** metrik tersebut jadi keputusan.
- `24` Sentinel = eksekutor koreksi. `29` = **otak** Sentinel dalam menentukan *apa* yang dikoreksi.

---
▶ Lanjut: implementasi Reasoning Engine (scaffold kode) atau perluas kamus `28` dari hasil novel finding.
