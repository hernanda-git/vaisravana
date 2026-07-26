# Output Dokumentasi Otomatis (apa yang Sentinel tulis)

Sentinel wajib menghasilkan dokumen tiap siklus. Format baku supaya konsisten & bisa dibaca
manusia + mesin. Semua juga masuk ke `results_log` (`30` §4) secara terstruktur.

> **TIDAK ADA sinyal eksternal** — istilah "signal" diganti "decision" (internal).

## 1. `eval_report.md` — hasil auto-evaluate (PER PAIR×TF×SIDE)
```markdown
# Eval Report — 2026-07-26 (window harian)
Portfolio WR: 86% | Expectancy: +0.7R | PF: 1.4 | MaxDD: 1.9%

## Per-Pair×TF Win Rate (gate 85%)
| pair   | tf  | trades | WR   | status |
| BTCUSDT| 5m  | 210    | 87%  | ✓ live |
| BTCUSDT| 15m | 205    | 85%  | ✓ live |
| ETHUSDT| 5m  | 198    | 83%  | ⚠ shadow (belum gate) |
| SOLUSDT| 10m | 150    | 79%  | ✗ disable (di bawah 85%) |

## Per-Faktor WinRate (global)
| faktor | WR | vs baseline |
| trend | 88% | +12 |
| volume | 84% | -8 |
| liquidity | 86% | 0 |
| atr | 83% | -13 |

## Per-Regime Expectancy
| regime | Exp(R) | status |
| trending_bull | +0.8 | ok |
| range | +0.3 | ✓ (di atas 0.2) |
| breakout | +0.4 | ok |
| high_vol | -0.2 | ⚠ kurangi exposure |
```
## False Decisions (bukan false signals)
- False positive (ENTRY→SL): 9/24 (37%)
- False negative (SKIP→harusnya profit): 3
```

## 2. `change_proposal.md` — usulan auto-correct
```markdown
# Change Proposal v1.4.3 (kandidat, SHADOW — BTCUSDT/5m)
Basis: eval_report 2026-07-26

## Perubahan
- weights.volume   0.15 → 0.12  (WR 84% → naik target 85%)
- weights.trend    0.30 → 0.33  (WR 88%, normalisasi)
- tp_atr_mult      1.05 → 1.0   (R:R ~1.0, WR naik)
- regime.range     enabled → false (WR 79% < gate 85%)
- entry_threshold 0.90 → 0.92  (false positive turun)

Σ weights = 1.00 ✓
Bound check: PASS | Rate-limit: 5 changes ≤ 5 ✓

## Prediksi
Shadow WR target ≥ 85%, Exp ≥ +0.7R, DD ≤ 1.9%.
```
> Contoh nilai mengikuti `30-concrete-spec.md`. Boundary leverage maks 3 (`21`),
> jadi jangan pernah contohkan leverage 5. Fokus koreksi: **naikkan WR per (pair×tf×side) ke ≥85%**.

## 3. `changelog.md` — apa yang BENAR diterapkan
```markdown
# Changelog
## v1.4.2 → v1.4.3  (2026-07-26, auto-promosi BTCUSDT/5m)
Diterapkan:
- volume 0.15→0.12, trend 0.30→0.33, tp_atr 1.05→1.0
- range regime OFF (WR 79% < 85%)
- entry_threshold 0.90→0.92
Alasan: volume WR 84%, range WR 79%, FP tinggi
Shadow: WR 87% (≥85% gate), Exp +0.72R (≥live/paper), DD 1.7% (≤limit) → PROMOSI
```

## 4. `postmortem.md` — kalau ada insiden / rollback
```markdown
# Postmortem — ETHUSDT/5m revert ke shadow (2026-07-27)
Insiden: pasca-promosi ETHUSDT/5m, WR jatuh ke 81% dalam 50 trade validasi.
Penyebab: tp_atr_mult 1.0→1.4 tanpa cukup shadow window (baru 30 trade).
Tindakan: REVERT ETHUSDT/5m ke SHADOW, high_vol regime di-disable sementara.
Pelajaran: perubahan multiplier butuh shadow ≥ 100 trade per (pair×tf×side).
```
> Catatan: leverage di cap keras max 3 (`21`), jadi insiden leverage tidak bisa melebihi itu.
> Postmortem harus realistis dalam bound. Gate utama adalah **WR 85% per (pair×tf×side)**.

## 5. `chronicle.md` — LOG KRONOLOGIS (sesuai fundamental project) ⭐
File **append-only, terurut waktu**, di `reports/<YYYY-MM-DD>/chronicle.md`. Setiap entri
mencatat: apa yang **berubah**, apa yang **membaik (improvement)**, dan **ringkasan evaluasi**.
Ini memenuhi request "dokumentasi markdown chronologically on what need to change, what need
to improve, the summary of evaluation".

```markdown
# Chronicle — VaiÅravaá¹a Bot

## 2026-07-26T12:00  [EVALUATION] BTCUSDT/5m
- Eval: WR 87% (≥85%), Exp +0.72R, DD 1.7%. Status: ✓ LIVE.
- Change: tp_atr_mult 1.05→1.0, entry_threshold 0.90→0.92.
- Improve: false-positive 41%→37% setelah threshold naik.
- Reasoning (5W1H): WHY=FP tinggi erosi expectancy; HOW=naikkan gate entry.

## 2026-07-26T18:00  [REVIEW] Portfolio
- Eval: portfolio WR 86%, 4 pair×TF live, 1 disable (SOLUSDT/10m 79%).
- Change: regime.range OFF (kontribusi WR rendah).
- Improve: diversifikasi pair×TF live naik ke 4.
- Summary: stabil, within DD < 3%.

## 2026-07-27T09:00  [CORRECTION] ETHUSDT/5m revert
- Eval: WR jatuh 85%→81% pasca-promosi (50 trade validasi).
- Change: REVERT ke SHADOW; high_vol regime disable sementara.
- Improve: cegah erosi lebih lanjut; pending review 100-trade window.
- Summary: fail-safe bekerja, tidak ada loss material.
```
> `chronicle.md` adalah narasi manusia. Versi terstruktur ada di `results_log`
> (`kind`: EVALUATION/REASONING/THINKING/CORRECTION/IMPROVEMENT/REVIEW).

## Lokasi
Semua file di `C:\Workspace\vaisravana\reports\<YYYY-MM-DD>\`.
Nama file tetap (`eval_report.md`, `change_proposal.md`, `changelog.md`, `postmortem.md`,
`chronicle.md`) agar mudah di-index & di-diff antar hari.

## Siklus Dokumentasi
```
trade EXIT → eval_report (otomatis)        → results_log(kind=EVALUATION)
window rollup → change_proposal (otomatis) → results_log(kind=CORRECTION)
shadow selesai → changelog / postmortem    → results_log(kind=IMPROVEMENT/REVIEW)
setiap entri  → chronicle.md append         → results_log(kind=*)
```
Semua tanpa intervensi manusia (kecuali mode supervised untuk approve).
