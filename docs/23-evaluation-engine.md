# Evaluation Engine — auto-evaluate

Bagian Sentinel yang menghitung metrik dari telemetry. Berjalan otomatis (tiap trade tutup + tiap window rollup).

## Metrik Inti
| Metrik | Rumus | Arti |
|--------|-------|------|
| Win Rate | wins / total | Proporsi menang |
| Expectancy | Σ pnl / total | Rata-rata PnL per trade |
| Profit Factor | gross_profit / gross_loss | >1 = menguntungkan |
| R-Multiple avg | Σ R / total | Kualitas ukuran vs risiko |
| Max Drawdown | peak→trough equity | Risiko terburuk |
| Sharpe (sederhana) | mean(R)/std(R) | Konsistensi |
| Trade Efficiency | MFE vs actual exit | Apakah TP/SL pas? |

## 5. Per-Pair × Per-TF Evaluation (HEADLINE: +85% WR)
Sistem mengevaluasi **setiap kombinasi pair×TF secara independen** (`30` §5, §8).

| Metrik | Target |
|--------|--------|
| **Win Rate (per pair×TF)** | **≥ 85%** (gate promosi ke live) |
| Expectancy (R) | > +0.2R |
| Profit Factor | > 1.20 |
| Max Drawdown | < 3% |
| Sharpe (R) | > 0.5 |
| Fill rate | > 95% |
| Avg slippage | < 5 bps |

Rolling window **200 trade per pair×TF**. Pair×TF di bawah 85% WR → Sentinel revert ke
shadow / disable (`30` §6). Atribusi per-faktor & per-regime tetap dihitung untuk koreksi.
Untuk tiap faktor skor, hitung:
- Win rate saat faktor tersebut **tinggi** vs **rendah**.
- Korelasi skor-faktor vs PnL.

```
Contoh hasil:
  trend      winrate 0.72  (bagus → pertahankan bobot)
  volume     winrate 0.54  (lemah → kandidat turun bobot)
  liquidity  winrate 0.61
  atr        winrate 0.49  (di bawah 50% → cek filter)
```

## Atribusi per-Regime
```
  trending_bull   expectancy +0.8R   ✓
  range           expectancy -0.3R   ✗ → bot rugi di range
  breakout        expectancy +0.4R
  high_vol        expectancy -0.9R   ✗ → kurangi leverage di high_vol
```
→ Sentinel tahu **regime mana yang harus di-disable / di-tweak**.

## Atribusi False Decision (TIDAK ADA sinyal — pakai "decision")
- **False Positive**: decision=ENTRY tapi berakhir SL.
- **False Negative**: decision=SKIP tapi harness/shadow menunjukkan seharusnya profit.
→ Deteksi filter yang terlalu longgar/ketat. Data dari `decisions_log` + `trade_logs`.

## Trigger Evaluasi
- Setiap trade EXIT (unreal maupun live) → update metrik rolling.
- Setiap window (harian / **200 trade rolling** per `30-concrete-spec.md` §5) → rollup + panggil Review Bot.
- Setiap event khusus: drawdown > batas, losing streak ≥ N, regime shift terdeteksi.

## Metrik Eksekusi (BARU — blind spot mikrostruktur)
Selain PnL, Sentinel wajib ukur **kesehatan eksekusi** (kelompok B/C `28-unexpected-factors.md`):

| Metrik | Rumus | Arti |
|--------|-------|------|
| Realized Slippage (bps) | (fill − ref)/ref × 1e4 | Biaya riil vs ekspektasi |
| Slippage vs Expected | realized − assumed | Negatif besar = model salah |
| Fill Rate | filled / orders | Reject/partial tinggi = masalah |
| Maker Ratio | maker_fills / total | Strategi "maker" nyata taker? |
| Exec Latency p95 | ms | Lambat = sinyal kadaluarsa |
| Reject Rate | rejected / orders | Margin/limit/price issue |
| Data Staleness | age(last_update) | Feed frozen? |
| 429 Rate | reject API / total | Rate-limit kena |

Jika metrik eksekusi buruk → **bukan salah sinyal**. Sentinel arahkan ke perbaikan
infrastruktur/eksekusi, bukan ubah bobot skor.

## Metrik Exchange Risk (BARU — kelompok D)
- Avg funding rate per hold → biaya carry.
- ADL rank max → risiko deleverage.
- Mark-vs-last gap ekstrem → SL engine exchange beda dari asumsi.
- Insiden maintenance/delist → otomatis pause.

## Metrik Riset / Validitas (BARU — kelompok E)
| Metrik | Tujuannya |
|--------|-----------|
| Backtest-vs-Live gap | Deteksi overfitting / look-ahead |
| OOS decay slope | Model decay (kapan retrain) |
| Parameter churn | Berapa sering Sentinel ubah config (osilasi?) |
| Shadow-vs-Live diff | Apakah shadow sungguh out-of-sample |

## Composite Health Score (BARU — cegah reward hacking)
JANGAN evaluasi cuma 1 metrik (Sentinel bakal game WinRate lalu hancurkan PF).
Gunakan skor komposit, mis.:
```
Health = 0.35·ProfitFactor + 0.25·(1−MaxDD) + 0.20·Expectancy + 0.20·FillRate
```
Hanya promosi kalau **Health** naik, bukan sekadar WinRate.

