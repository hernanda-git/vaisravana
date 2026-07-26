# Keamanan — Shadow, Bound, Rollback

Lapisan pelindung agar "auto-correction" tidak jadi "auto-destroy".

## 1. Shadow Mode
- Trader SHADOW jalan dengan konfigurasi kandidat, **tanpa eksekusi order nyata**.
- Bandingkan metrik Shadow vs Live selama window uji.
- Promosi hanya jika Shadow ≥ Live (expectancy, DD).
- Biaya: butuh duplikasi pipeline data + compute kecil. Worth it.

| Bound | Contoh salah | Benar (sesuai `21`) |
|-------|--------------|---------------------|
| `entry_threshold` | 0.70–0.90 | **0.85–0.92** (default 0.90) |

## 2. Two-Layer Safety Gate (dari `32-listener-lessons.md`)

Sama seperti listener: pembatas dibagi dua lapis supaya murah + tidak bisa di-override.

**Gate A — Pre-scoring (murah, tidak pakai engine):**
- Idempotency (`correlation_id` unik → 1 entry per decision, bukan per signal).
- Per-pair cooldown (cegah over-trade pair sama beruntun).
- Pair lolos liquidity-filter / whitelist.
- Spread < ambang per-pair (`28-B`).

**Gate B — Post-scoring, pre-execution (hard clamp — 9-engine score TIDAK bisa override):**
- Clamp size ke `risk_usd`; `max_leverage` ≤ 2.
- `daily_loss_limit` ≤ 0.5%; margin ≤ 50% free.
- **SL arah benar** (LONG→di bawah, SHORT→di atas) — tolak kalau terbalik (cegah SL/TP hallucinated).
- `reduceOnly` pada semua close order (cegah accidental flip).

> Sentinel tidak boleh menyentuh Gate B (lihat `24` guardrail).

---

## 2b. Position Monitor (runtime safety — `11` §8, `30` §3, dari `32`)
Background loop 10s:
- **SL dual-mechanism:** conditional STOP (reduceOnly) primary + mark-price polling backup (untuk 1000x `-4120`).
- **Self-heal:** SL/TP hilang di exchange tapi posi open → re-place 1x/session.
- **Orphan detection:** posi tanpa order & age >30m → verify exchange (source of truth).
- **Time-based exit:** hold > max-hold (15m/10m/5m) → market close.

---

## 2c. Health Reporter (proactive — `28-C`, `30` §4, dari `32`)
Setiap 6 jam cek semua subsystem dan alert:
Telegram Bot / listener-conn, Exchange conn + balance, Portfolio (margin/posi),
Leverage ceiling, Symbol registry, DB reachability. Logger gagal = alarm + stop entry
## 3. Rate-of-Change Limit
- Bobot ≠ berubah > ±10% per siklus.
- Maks N perubahan per siklus (mis. 4) → isolasi sebab-akibat.
- `Σ weights == 1.0` selalu dinormalisasi ulang.

## 4. Rollback Otomatis
- Setiap versi config disimpan (snapshot).
- Kalau pasca-promosi (live) metrik memburuk dalam window validasi → rollback ke versi sebelumnya otomatis.
- Rollback juga bisa manual (tombol darurat / kill switch).

## 5. Kill Switch & Circuit Breaker
| Trigger | Aksi |
|---------|------|
| Drawdown harian > `daily_loss_limit_pct` | Tutup semua posi, mode PAPER, notif |
| Losing streak ≥ N (mis. 7) | Cooldown paksa, naikkan `cooldown_after_loss` |
| Exchange/connection error | Hentikan entry, pertahankan manajemen posi terbuka |
| 3x rollback berturut | Nonaktifkan auto-correct, mode supervised |
| **ADL rank tinggi / liquidation imminent** | Kurangi leverage / tutup sebagian, notif |
| **Funding rate ekstrem** | Jangan hold melawan, tutup sebelum funding |
| Exchange MAINTENANCE / DELIST | Pause bot, net position, notif |
| **Data feed FROZEN / stale** | Hentikan entry, alarm (blind spot kelompok A) |
| **Black-swan / vol anomali** | Kill switch event-driven + human alert wajib (kelompok G) |
| **Global live exposure melebihi cap** | `global_max_live_pairs` (default 5) → tolak promosi baru, notif |

> Filter safety (daily_loss_limit, kill switch, data-feed monitor) **TIDAK BOLEH dimatikan**
> oleh Sentinel — lihat `24-review-correction-bot.md` guardrail. Ini cegah Sentinel
> "mematikan rem" demi metrik bagus sementara.


## 6. Human-in-the-loop (opsional per mode)
- `mode=autonomous`: Sentinel apply tanpa approve (dengan semua guardrail di atas).
- `mode=supervised`: perubahan besar (≥2 param / bobot >5%) harus di-approve manusia.
- Selalu ada **notifikasi** (telegram/discord) tiap promosi & rollback.

## 7. Audit Trail
- Setiap perubahan config → siapa/apa/alasan/versi.
- Setiap trade → `config_version` tercatat di telemetry.
→ Bisa replay: "versi v1.4.3 penyebab drawdown 2% di regime breakout".
