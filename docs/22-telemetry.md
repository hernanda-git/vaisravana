# Telemetry — Trade Journal (Mata Sentinel)

Tanpa log yang kaya, bot koreksi **buta**. Ini skema minimal yang HARUS dicatat tiap event.
Sentinel membaca ini untuk auto-evaluate & auto-review.

## 1. Event: DECISION (tiap kali scoring dijalankan — TIDAK ADA sinyal eksternal)
Bot memutuskan sendiri dari engine → rekam sebagai `decisions_log` (bukan SIGNAL).
```json
{
  "ts": "2026-07-26T12:00:00Z",
  "correlation_id": "C-10231",
  "pair": "BTCUSDT",
  "tf": "5m",
  "symbol": "BTCUSDT",
  "regime": "trending_bull",
  "scores": {
    "trend": 28, "momentum": 17, "volume": 10,
    "structure": 13, "liquidity": 8, "atr": 5, "funding_oi": 5,
    "long_score": 86, "short_score": 41
  },
  "decision": "ENTRY" | "WATCH" | "SKIP",
  "side": "BUY" | "SELL",
  "confidence_pct": 86,
  "gate_a_pass": 1, "gate_b_pass": 1,
  "filters_passed": ["support", "volume_up", "htf_bull"],
  "filters_failed": ["momentum_exhausted"],
  "market_ctx": { "atr": 120, "avg_body": 45, "vol_z": 1.8, "liq_sweep": false }
}
```

> **Bidirectional:** `long_score` dan `short_score` dihitung terpisah (`doc 10`).
> `side` = arah terpilih (BUY/SELL). `confidence_pct` = skor terpilih × 100.

## 2. Event: FILL (order terisi)
```json
{
  "ts": "...", "trade_id": "T-10231",
  "side": "BUY", "entry": 64210.5, "size": 0.05,
  "leverage": 2, "sl": 63800, "tp": 65100,
  "config_version": "v1.4.2",
  "decision_snapshot": { /* copy scores + ctx dari DECISION */ }
}
```

## 3. Event: EXIT (ditutup)
```json
{
  "ts": "...", "trade_id": "T-10231",
  "exit_price": 65100, "exit_reason": "TP" | "SL" | "STRUCTURE_BREAK" | "TRAILING" | "MANUAL",
  "pnl_usd": 44.5, "pnl_pct": 0.69, "r_multiple": 2.1,
  "hold_min": 37,
  "max_favorable_excursion": 2.4,
  "max_adverse_excursion": -0.8
}
```

## 4. Event: REGIME / METRIC ROLLUP (tiap window)
```json
{
  "window": "2026-07-26", "trades": 24,
  "per_regime": { "trending_bull": {...}, "range": {...}, "breakout": {...} },
  "per_factor_winrate": { "trend": 0.71, "volume": 0.55, ... }
}
```

## 5. Event: EXECUTION HEALTH (krusial — blind spot eksekusi/data)
Lihat `28-unexpected-factors.md` kelompok B/C. Tanpa ini, Sentinel buta pada kerugian
bukan-sinyal (slippage, partial fill, reject, latency).

```json
{
  "ts": "...", "trade_id": "T-10231",
  "fill_type": "MAKER" | "TAKER",
  "expected_slippage_bps": 2, "realized_slippage_bps": 11,
  "filled_qty": 0.05, "order_qty": 0.05, "partial": false,
  "reject_reason": null,           // "INSUFFICIENT_MARGIN" | "PRICE_MOVED" | null
  "order_latency_ms": 84,
  "ack_status": "FILLED" | "REJECTED" | "STUCK",
  "spread_bps_at_exec": 3
}
```

## 6. Event: DATA / INFRA HEALTH (blind spot kelompok A/C)
```json
{
  "ts": "...",
  "feed_age_ms": 1200,              // > threshold → stale
  "clock_offset_ms": -350,         // vs exchange
  "candle_gap": true,              // missing candle terdeteksi
  "ws_status": "CONNECTED" | "FROZEN" | "RECONNECTING",
  "api_429_count": 0,
  "process_uptime_s": 86400
}
```

## 7. Event: EXCHANGE RISK (blind spot kelompok D)
```json
{
  "ts": "...", "symbol": "BTCUSDT",
  "funding_rate": 0.0001,
  "adl_rank": 3,                   // 1-5, tinggi = bahaya
  "mark_vs_last_gap_bps": 5,
  "liquidation_imminent": false,
  "exchange_status": "NORMAL" | "MAINTENANCE" | "DELIST_WARN"
}
```

> **Aturan:** Event 5/6/7 wajib masuk ke evaluator sebagai metrik kesehatan pipeline,
> bukan cuma metrik PnL. Sentinel yang hanya lihat WinRate akan lewatkan slippage
> merusak expectancy.

## 8. Skema Wajib (konkret — pakai ini)
Telemetry diimplementasikan sebagai tabel DB. Skema SQL pasti (tabel `trade_logs`,
`decisions_log`, `exec_events`, `system_health`, `results_log`) ada di **`30-concrete-spec.md` §4**.
Gunakan skema itu sebagai sumber tunggal — jangan buat skema berbeda.

> **Aturan emas logging:** `trade_logs` mencatat **SETIAP trade unreal (menang & kalah)**.
> Ini memenuhi syarat "record all win and loss on the unreal trade" — basis auto-evaluate
> dan promosi ke live.
- **Setiap keputusan** (bahkan SKIP) dicatat → Sentinel tahu false-negative & false-positive.
- `config_version` wajib ada di tiap FILL → Sentinel bisa korelasi hasil ↔ versi param.
- **`correlation_id`** wajib di SETIAP tabel (`decisions_log`, `exec_events`, `trade_logs`,
  `results_log`, `system_health`) → satu trade bisa di-trace penuh (decision→order→fill→tp→close),
  krusial untuk auto-review Sentinel & postmortem (`32` Lesson 5).
- Simpan di DB时间序列 (SQLite/Postgres) agar bisa query per symbol/regime/versi.
- Jangan log secret (API key). Hanya metadata strategi.

## Mengapa ini krusial
Sentinel melakukan **atribusi**: "faktor volume punya win rate 55% vs tren 71% → bobot volume boleh turun sedikit". Tanpa `scores` per event, atribusi mustahil.
