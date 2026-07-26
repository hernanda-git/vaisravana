# Feedback Loop — Orkestrasi

Cara keempat fase (evaluate → review → correct → improve) berputar secara otomatis.

## Loop Harian (default cadence — PAPER-first)
```text
┌─ TRADE (PAPER / UNREAL) ──────────┐
│ 9 engine → score → decision       │
│ log telemetry per event           │
└──────────┬────────────────────────┘
           │ trade EXIT (unreal)
           ▼
   [EVAL ENGINE] auto-evaluate (rolling 200 trade + harian)
           │ rollup window / event trigger
           ▼
   [SENTINEL] auto-review → eval_report.md
           │ temukan anomali
           ▼
   [SENTINEL] auto-correct → change_proposal.md
           │ apply ke SHADOW
           ▼
   [SHADOW] jalan window uji
           │ Shadow ≥ Live/Paper-baseline?
           ├── YA → promosi → changelog.md → config_version++
           └── TIDAK → buang diff / postmortem.md → rollback
           │
           ▼
   (kembali ke TRADE PAPER dengan config baru)
           │
   [GATE §6 30-concrete-spec.md terpenuhi + approve manusia]
           ▼
   LIVE diaktifkan **untuk (pair, tf, SIDE) itu** (PAPER/SHADOW tetap jalan paralel sebagai baseline)
```

> Di fase awal, belum ada Live — Shadow dibandingkan vs **Paper baseline** (`30` §6).
> Live hanya menyala setelah gate promosi. Lihat `30-concrete-spec.md`.

## Trigger (kapan loop berjalan)
| Trigger | Frekuensi | Contoh |
|---------|-----------|--------|
| Tiap trade EXIT | realtime | update metrik |
| Window rollup | harian / 200 trade | panggil review |
| Regime shift | event | re-eval bobot regime |
| Drawdown event | event | circuit breaker + review paksa |
| Losing streak | event | naikkan cooldown |

## Konvergensi & Anti-Runaway
- Sentinel tidak mengubah param tiap trade (overfit). Hanya di window rollup.
- Rate-limit + bound cegah osilasi (naik-turun terus).
- Jika metrik stabil (expectancy flat ≥ 2 window) → Sentinel bisa "istirahat" (no-change proposal) untuk hindari over-tuning.

## Mode Operasi Loop
| Mode | Deskripsi |
|------|-----------|
| `autonomous` | Loop penuh tanpa approve manusia (guardrail tetap jalan) |
| `supervised` | Promosi besar butuh approve manusia |
| `observe-only` | Sentinel evaluasi & dokumentasi, TIDAK apply perubahan (buat debugging) |

## Metrik Kesehatan Loop itu sendiri
Sentinel juga evaluasi dirinya:
- Apakah proposal terakhir benar-benar memperbaiki (bukan cuma noise)?
- Apakah terlalu sering rollback? (tanda bound terlalu longgar / window terlalu pendek)
→ Dokumentasikan di `postmortem.md` bila perlu.
