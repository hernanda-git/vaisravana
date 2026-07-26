# doc 43 — Telegram Notifier Fix (v0.0.8)

The owner reported: after deploy, **no version / health-check / any message arrives**, and
the version text showed artifacts: `v0\.0\.4` and an em-dash `—`.

## Root cause

Two distinct bugs, both in `src/telegram_bot.py`:

1. **MarkdownV1 + escaped version -> silent fallback to plain text.**
   The startup card called `_md_escape(version)`, and `_md_escape` backslash-escapes `.`
   (dot is in the MarkdownV1 special set). So `0.0.4` became `0\.0\.4`. MarkdownV1 then
   failed to parse the message ("can't parse entities"), the notifier fell back to
   **plain text** (no parse_mode). The plain-text message *was* delivered, but the
   client rendered the literal backslashes -> `v0\.0\.4`. It looked "broken / not
   triggering" even though the HTTP call succeeded. The same path affected every card.

2. **No explicit health-check on deploy.** There was only a 30-minute status card that
   required trades to have happened. With the (correctly) sparse signal, a fresh deploy
   could sit silent for 30+ minutes, reinforcing the "not triggering" impression.

3. **Em-dash `—`** was used as a separator in the startup card (cosmetic, but the owner
   explicitly asked to remove it).

## Fix

- **Switched to MarkdownV2** (`parse_mode: "MarkdownV2"`), the current, reliable Telegram
  parser. Added a correct `mdv2_escape()` for all *free text* (reasons, changelog,
  titles).
- **Version + codes passed RAW** (not escaped). A version is a controlled `[digits.]digits`
  string with no special chars, so it now renders as `v0.0.8` — never `v0\.0\.8`.
- **Removed every em-dash**; clean `·` / `:` / `-` separators only.
- **NEW `notify_health_check()`** — an explicit heartbeat sent on every deploy (and usable
  periodically) so the owner can confirm liveness instantly: status, region, open positions,
  UTC timestamp. Wired into `bot_paper.run()` right after the startup + deploy cards.

## Result (verified by rendering)

```
🤖 Vessavaṇa · Bot PAPER aktif  v0.0.8

Pasangan  : BTCUSDT · ETHUSDT · SOLUSDT
Keputusan : 1m · eksekusi saat candle tutup
Konteks   : 5m · 15m · bias multi-timeframe
Siklus    : 60 dtk
Mode      : PAPER · tanpa order live
LLM       : off
Posisi    : 0 · dimuat ulang

💓 Health Check · v0.0.8
Status  : sehat ✅
Region  : sin
Posisi  : 0 terbuka
Waktu   : 2026-07-26 15:07 UTC
```

No backslashes, no em-dash, valid MarkdownV2 (renders bold/labels correctly).

## Tests
`tests/test_phase10b_deploy.py` updated:
- escape function renamed `_md_escape` -> `mdv2_escape`; assertions unchanged (same special
  set).
- fallback test asserts `MarkdownV2` then plain.
- NEW `test_startup_card_renders_version_cleanly`: asserts `v0.0.7` present, `v0\.0\.7`
  absent, no em-dash.
- NEW `test_health_check_sent_on_deploy`.
