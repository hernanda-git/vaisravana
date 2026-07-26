# VaiÅravaá¹a-Sentinel — auto-review + auto-correct

Bot kedua. Baca evaluasi → cari apa yang salah → usulkan & terapkan koreksi (di shadow dulu).

## Fase 0 — REASON (baru, sebelum review)
Sebelum auto-review, Sentinel menjalankan **Reasoning Engine** (`29-dynamic-reasoning-5w1h.md`):
1. Ambil anomali dari evaluator → isi **5W1H** (WHO/WHAT/WHEN/WHERE/WHY/HOW).
2. Bangun hipotesis: H1 (dari kamus `28`), H2, dan **H3 novel** (di luar daftar).
3. Pilih respons teraman yang **menguji** hipotesis dominan.
4. Kalau H3 benar → usulkan penambahan entri ke `28` (peer-review manusia di supervised).

Ini mencegah Sentinel terpacu faktor konstan: ia bisa mengenali situasi **baru** yang tak
ada di checklist, lalu mendokumentasikannya sebagai pengetahuan baru.

Lihat `29` untuk 5 skenario kerja (feed freeze, shadow≠live, funding/ADL, reward hacking,
cross-venue divergence) yang menunjukkan reasoning dinamis vs rule statis.
Dari `eval_report`, Sentinel menjawab:
1. Faktor mana dengan win rate < 50%? → kandidat turun bobot / matikan filter.
2. Regime mana dengan expectancy negatif? → disable regime itu atau turunkan exposure.
3. Apakah TP/SL pas? (lihat Trade Efficiency / MFE) → kalau TP terlalu jauh, turunkan `tp_atr_mult`.
4. False-negative tinggi di filter X? → longgarkan filter X.
5. Drawdown tinggi? → naikkan `sl_atr_mult` atau turunkan `max_leverage` / `daily_loss_limit`.
6. Apakah skor threshold terlalu rendah (banyak entry rugi)? → naikkan `entry_threshold`.

## Fase 2 — auto-correct (usulan parameter)
Sentinel menghasilkan **diff konfigurasi**, bukan ubah kode:

```text
CHANGE PROPOSAL v1.4.3 (kandidat, SHADOW)
  weights.volume      0.15 → 0.12   (WR 84% → turun, butuh naik ke 85%)
  weights.trend       0.30 → 0.33   (WR 88%, normalisasi)
  tp_atr_mult         1.05 → 1.0    (TP sering tdk tersentuh, R:R ~1.0)
  regime.range.enabled false        (WR 79% di bawah gate 85%)
  entry_threshold     0.90 → 0.92   (false positive tinggi)
  => Σ weights = 1.00 ✓
```
> Nilai awal mengikuti `30-concrete-spec.md` (entry 0.90, tp 1.05, WR gate 85%).
> Koreksi ke arah **naikkan WR per (pair×tf×side)**, bukan cuma expectancy.

Aturan aman koreksi:
- Perubahan bobot per siklus ≤ ±10% dari nilai saat ini.
- Threshold tidak boleh keluar bound (`21-active-bot.md`).
- Maksimal N perubahan per siklus (mis. 4) agar mudah dilacak sebab-akibat.

## Fase 3 — SHADOW test (wajib)
Diff diterapkan ke **trader SHADOW** (param kandidat, tidak eksekusi nyata).
Sentinel bandingkan selama window uji (mis. 50 trade / 3 hari):
- Shadow expectancy vs **Live expectancy** (atau vs **Paper baseline** bila Live belum aktif — sesuai `30` §6).
- Shadow max DD vs Live/Paper DD.
→ Hanya promosi kalau Shadow **tidak lebih buruk** (expectancy ≥ baseline, DD ≤ baseline).

## Fase 4 — auto-improve (promosi)
Kalau Shadow lolos:
- Promosi diff ke konfigurasi LIVE (`config_version` naik).
- Catat di riwayat konfigurasi.
Kalau gagal:
- Buang diff, kembalikan ke versi sebelumnya (rollback).
- Sentinel dokumentasikan kenapa gagal (pelajaran).

## Fase 5 — DOCUMENT
Sentinel tulis otomatis (lihat `26-documentation-output.md`):
- `eval_report.md` (hasil evaluasi)
- `change_proposal.md` (apa yang diusulkan + alasan)
- `changelog.md` (apa yang benar-benar diterapkan)
- `postmortem.md` (kalau ada insiden / rollback)

## Guardrail Eksekusi
| Kondisi | Tindakan Sentinel |
|---------|-------------------|
| Drawdown harian tembus limit | Hentikan promosi, mode PAPER, alert manusia |
| 3x rollback berturut | Stop auto-correct, tunggu review manusia |
| Shadow lebih buruk | Jangan promosi, simpan sebagai pelajaran |
| Perubahan di luar surface | Tolak, minta intervensi manusia |
| **Metrik eksekusi buruk** (reject↑, slippage↑) | JANGAN ubah bobot — arahkan ke perbaikan infra (`28` kelompok B/C) |
| **Composite Health turun meski WinRate naik** | Tolak promosi (cegah reward hacking) |
| **Shadow sama data dgn Live** | Tolak — butuh forward/paper test sungguhan (`28` kelompok G) |
| **Filter safety mau dimatikan** | TOLAK keras — daily_loss/kill switch tidak boleh disentuh Sentinel |

## Anti-Reward-Hacking (BARU — lihat `28` kelompok G)
Sentinel dirancang agar **tidak bisa mengoptimalkan metrik tunggal**:
- Evaluasi pakai **Composite Health Score**, bukan WinRate mentah.
- Perubahan yang naikkan WinRate tapi turunkan Profit Factor / naikkan DD → **ditolak**.
- Parameter churn diawasi: kalau Sentinel ubah config terlalu sering (osilasi) → rate-limit diperketat.

## Validation yang Sebenarnya (BARU)
Shadow test yang memakai **data yang sama** dengan live bukan validasi.
- Gunakan forward testing / paper di jam berbeda, atau sim eksekusi dengan slippage riil historis.
- Bandingkan Shadow Health vs Live Health, bukan cuma expectancy.

## Catatan: Di mana AI/LLM duduk?
Sentinel boleh pakai LLM untuk **menyusun narasi review & dokumentasi** (fase 5),
tapi **keputusan angka** tetap dari evaluasi statistik + bound. Jangan biarkan LLM
menentukan param sembarangan tanpa shadow-test. (Mode "autonomous" = tanpa approval
manusia; "supervised" = perubahan besar butuh approve.)
