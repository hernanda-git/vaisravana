# Sistem Dua-Bot: Trader Aktif + Bot Koreksi (Sentinel)

Dokumen induk untuk bot yang **auto-correction, auto-improve, auto-review, auto-evaluate**.

## Konsep

```
        ┌──────────────────────────────────────────────┐
        │                  MARKET                       │
        └───────────────┬──────────────────────────────┘
                        │ data OHLCV + orderflow
                        ▼
        ┌──────────────────────────────────────────────┐
        │            VAIÅRAVAá¹A-TRADER (AKTIF)              │  ← entry/exit
        │  9 engine + scoring + risk manager            │
        │  MODE DEFAULT: PAPER/UNREAL (lihat 30)        │  ← log semua win/loss per pair×TF
        │  UNIVERSE: all Binance USDT (liquidity-filtered) │  ← 5m/10m/15m shadow
        └───────┬───────────────────────┬──────────────┘
                │ order                  │ telemetry (log)
                ▼                        ▼
        ┌──────────────┐     ┌────────────────────────────────┐
        │  EXCHANGE    │     │  TELEMETRY STORE (trade journal)│
        └──────────────┘     └───────────┬────────────────────┘
                                         │ baca
                                         ▼
        ┌──────────────────────────────────────────────┐
        │        VAIÅRAVAá¹A-SENTINEL (KOREKSI/REVIEW)        │
        │  1. auto-evaluate  → metrik & atribusi          │
        │  2. auto-review    → temukan apa yang salah     │
        │  3. auto-correct   → usulkan param (shadow)     │
        │  4. auto-improve   → promosi kalau shadow menang│
        │  5. DOCUMENT       → tulis apa yg berubah & why │
        └───────────────┬──────────────────────────────┘
                        │ apply parameter (berbatas)
                        ▼
                 (kembali ke VAIÅRAVAá¹A-TRADER)
```

## Dua Peran

| Bot | Nama | Tugas | Bahaya kalau rusak |
|-----|------|-------|--------------------|
| **Aktif** | `VaiÅravaá¹a-Trader` | Eksekusi trading nyata | Rugi trade biasa |
| **Koreksi** | `VaiÅravaá¹a-Sentinel` | Evaluasi, review, koreksi, dokumentasi | Bisa merusak bot aktif kalau tanpa guardrail |

## Prinsip Keamanan (WAJIB)
1. **Sentinel tidak boleh rewriter kode secara bebas.** Ia hanya ubah **parameter surface berbatas** (bobot, threshold, SL/TP multiplier, cooldown, on/off filter).
2. **Semua koreksi diuji di SHADOW** dulu (simulasi, bukan uang nyata) sebelum promosi.
3. **Ada batas perubahan** (mis. bobot tidak boleh berubah > ±10% per siklus).
4. **Rollback otomatis** kalau shadow / live pasca-koreksi memburuk.
5. **Human-approval gate** untuk perubahan besar (bisa di-pass mode "supervised" vs "autonomous").

## Empat Kata Kunci = Empat Fase

| Fase | Dilakukan oleh | Output |
|------|----------------|--------|
| **auto-evaluate** | Sentinel / Eval Engine | Laporan metrik + atribusi per-faktor |
| **auto-review** | Sentinel | Temuan: mana filter/regime yang gagal |
| **auto-correct** | Sentinel | Usulan perubahan param (ke shadow) |
| **auto-improve** | Loop promosi | Param baru dipakai live kalau shadow lebih baik |

## Hubungan dengan dokumen sebelumnya
- `VaiÅravaá¹a-Trader` = implementasi dari `11-bot-architecture.md` (9 engine) + `10-scoring-system.md`.
- Sentinel butuh **telemetry** yang dijelaskan di `22-telemetry.md` — tanpa ini Sentinel buta.
- Evaluasi pakai metrik di `23-evaluation-engine.md`.
- Dokumentasi otomatisnya punya format wajib di `26-documentation-output.md`.

## 9 Engine + 1 Reasoning Layer
Arsitektur `11-bot-architecture.md` punya 9 engine. Di atas itu, sistem dua-bot menambah
**Reasoning Engine** (`29-dynamic-reasoning-5w1h.md`) sebagai "otak" yang tidak terpacu
faktor konstan — ia menyusun skenario 5W1H, membangun hipotesis (termasuk **novel / di luar
daftar `28`**), lalu bertindak lewat guardrail.

```
[9 Engine] → telemetry → [Evaluator 23] → metrik
                                  ↓
                       [Reasoning Engine 29]  ← 5W1H, hipotesis dinamis
                                  ↓
                       [Sentinel 24] → correct/improve → Trader
```

> Tanpa Reasoning Engine, Sentinel cuma "patch angka". Dengan dia, Sentinel **menjelaskan**
> situasi, membedakan situasi baru, dan menambah kamus `28` saat menemukan kategori baru.

## Pemetaan Blind Spot → Dokumen (riset "faktor tak terduga")
Lihat `28-unexpected-factors.md` untuk daftar lengkap. Setiap kelompok sudah di-extend ke doc terkait:

| Kelompok (28) | Masuk ke |
|----------------|----------|
| A. Data integrity | `22-telemetry.md` (event 6), `25` (feed frozen breaker) |
| B. Execution/microstructure | `22-telemetry.md` (event 5), `23` (metrik eksekusi) |
| C. Infra/latency | `22-telemetry.md` (event 6), `25` (crash/restart) |
| D. Exchange risk (ADL/funding/delist) | `22-telemetry.md` (event 7), `25` (breaker baru) |
| E. Riset/backtest validity | `23-evaluation-engine.md` (metrik riset) |
| F. Portfolio risk | `21-active-bot.md` (bound leverage), `25` |
| G. Meta-loop risk (reward hacking, shadow in-sample) | `24` (anti-reward-hacking), `23` (composite health) |
| H. Tata kelola/keamanan | `25` (human-in-loop), `26` (audit trail) |

> **Inti:** 8 layer asli = ALPHA (sinyal). Tapi di production, kerugian terbesar sering
> dari eksekusi + data + exchange + validitas riset + meta-loop. Sentinel harus evaluasi
> **seluruh pipeline**, bukan cuma "apakah sinyal bagus".

---
▶ Lanjut: `21-active-bot.md` (batas apa yang boleh diubah Sentinel).
