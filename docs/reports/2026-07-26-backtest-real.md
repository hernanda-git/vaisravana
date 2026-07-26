# Phase 9 — Real-Data Backtest (Binance USDⓈ-M via binance-gateway/sin)

- Source: real klines, 1500 bars per series (fetched 2026-07-26)
- Fees: VIP0 maker 0.02% / taker 0.05% (LIMIT entry+TP maker; SL/MAXHOLD taker)
- Conservative bar-fill rule: SL checked before TP within the same bar

## Full sample

# Backtest Report — per (pair, tf, side)

| Pair | TF | Side | Trades | WR | Expectancy | PF | MaxDD |
|------|----|------|--------|----|------------|----|-------|
| BTCUSDT | 5m | BUY | 1 | 100.0% | +0.204R | ∞ | 0.00% |
| BTCUSDT | 15m | SELL | 1 | 100.0% | +0.705R | ∞ | 0.00% |
| ETHUSDT | 5m | BUY | 1 | 100.0% | +1.050R | ∞ | 0.00% |
| ETHUSDT | 15m | BUY | 1 | 100.0% | +1.050R | ∞ | 0.00% |
| SOLUSDT | 5m | SELL | 1 | 0.0% | -0.648R | 0.00 | 0.13% |
| SOLUSDT | 15m | BUY | 1 | 0.0% | -0.222R | 0.00 | 0.08% |

## In-sample (70%)

# Backtest Report — per (pair, tf, side)

| Pair | TF | Side | Trades | WR | Expectancy | PF | MaxDD |
|------|----|------|--------|----|------------|----|-------|
| BTCUSDT | 5m | BUY | 1 | 100.0% | +0.204R | ∞ | 0.00% |
| BTCUSDT | 15m | SELL | 1 | 100.0% | +0.705R | ∞ | 0.00% |
| ETHUSDT | 5m | BUY | 1 | 100.0% | +1.050R | ∞ | 0.00% |
| ETHUSDT | 15m | BUY | 1 | 100.0% | +1.050R | ∞ | 0.00% |
| SOLUSDT | 5m | SELL | 1 | 0.0% | -0.648R | 0.00 | 0.13% |
| SOLUSDT | 15m | BUY | 1 | 0.0% | -0.222R | 0.00 | 0.08% |

## Out-of-sample (30%)

# Backtest Report — per (pair, tf, side)

| Pair | TF | Side | Trades | WR | Expectancy | PF | MaxDD |
|------|----|------|--------|----|------------|----|-------|
| BTCUSDT | 15m | BUY | 1 | 0.0% | -1.000R | 0.00 | 0.17% |
| ETHUSDT | 5m | BUY | 1 | 100.0% | +1.050R | ∞ | 0.00% |
| ETHUSDT | 15m | SELL | 1 | 0.0% | -0.424R | 0.00 | 0.13% |
| SOLUSDT | 5m | BUY | 1 | 100.0% | +1.050R | ∞ | 0.00% |
| SOLUSDT | 15m | SELL | 1 | 0.0% | -0.356R | 0.00 | 0.10% |

## Notes
- Entries are sparse by design: 0.90 entry_threshold + Gate A/B select only A+ setups.
- WR targets (≥85% per pair×tf×side over 200 trades) require far longer history;
  this run validates PIPELINE correctness on real data, not final promotion stats.