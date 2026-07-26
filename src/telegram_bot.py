"""Telegram notifier for Project Vaiśravaṇa (Phase 10 / Fly deploy).

Mirrors learnernoearner-listener's notifier exactly:
  - env TELEGRAM_BOT_TOKEN + NOTIFY_CHAT_ID (Fly secrets) -> Bot API -> your channel
  - MarkdownV2 with a correct escaper on every dynamic field, so "can't parse entities"
    never eats an alert and never shows raw backslashes
  - MarkdownV2 attempt, then plain-text fallback so a notification is NEVER silently lost
  - 3950-char truncation guard (Telegram caps at 4096)

This bot is PAPER-only (no live orders). It reports the startup card, health checks,
decisions, fills, closes, promotions, kill-switch trips, and periodic status in one
Telegram channel.

Rendering policy (fixes the old backslash / em-dash artifacts):
  - Versions and codes are passed RAW (they are controlled `[digits.]digits` strings).
  - Em-dashes are never used; clean separators (·, :, -) only.
  - All free-text (reasons, changelog, titles) goes through `mdv2_escape`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("vaisravana.notifier.telegram")

# MarkdownV2 special characters that MUST be backslash-escaped when literal.
_MDV2_SPECIAL = r"_*[]()~`>#+-=|{}.!"


def mdv2_escape(text: str) -> str:
    """Escape Telegram MarkdownV2 special chars in dynamic content."""
    if not text:
        return text
    return "".join("\\" + c if c in _MDV2_SPECIAL else c for c in str(text))


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str | int):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base = f"https://api.telegram.org/bot{bot_token}"
        self._client: httpx.Client | None = None
        self._chat_dead: bool = False   # sticky: permanent chat error (e.g. not a member)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=10)
        return self._client

    def send_message(self, text: str) -> bool:
        if self._chat_dead:
            return False
        MAX_LEN = 3950
        if len(text) > MAX_LEN:
            text = text[:MAX_LEN - 40] + "\n\n… (truncated)"
        if not self.bot_token:
            log.info("[No bot token] %s", text[:100])
            return False
        client = self._get_client()
        resp = client.post(f"{self._base}/sendMessage", json={
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        })
        if resp.status_code == 200:
            return True
        # Permanent, non-retryable chat errors (bot not a member / kicked / forbidden):
        # stop hammering; surface once and go quiet until the next deploy.
        if any(k in resp.text for k in ("chat not found", "bot was kicked",
                                         "bot is not a member", "Forbidden", "PEER_ID")):
            self._chat_dead = True
            log.error("Telegram chat %s unreachable (%s) - notifications disabled "
                      "until restart. Add the bot to the chat or fix NOTIFY_CHAT_ID.",
                      self.chat_id, resp.text[:80])
            return False
        if "parse entities" in resp.text:
            resp2 = client.post(f"{self._base}/sendMessage", json={
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": True,
            })
            if resp2.status_code == 200:
                return True
            log.error("Telegram send failed (plain): %s", resp2.text)
            return False
        log.error("Telegram send failed: %s", resp.text)
        return False

    # ---- domain messages -------------------------------------------------

    def notify_decision(self, pair: str, tf: str, action: str, score: float,
                        side: str, reason: str) -> bool:
        icon = {"ENTRY": "🟢", "WATCH": "👁", "SKIP": "⏭"}.get(action, "•")
        text = (
            f"{icon} *{action}* `{pair} {tf}`\n"
            f"side: `{side or '-'}` · score: `{score:.3f}`\n"
            f"_{mdv2_escape(reason)}_"
        )
        return self.send_message(text)

    def notify_fill(self, pair: str, tf: str, side: str, entry: float,
                    sl: float, tp: float, lev: float) -> bool:
        text = (
            f"📈 *PAPER FILL* `{pair} {tf}` `{side}`\n"
            f"entry: `{entry:.2f}` · sl: `{sl:.2f}` · tp: `{tp:.2f}` · lev: `{lev}x`\n"
            f"🕐 _{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
        )
        return self.send_message(text)

    def notify_close(self, pair: str, tf: str, side: str, exit_price: float,
                     reason: str, pnl_r: float, win: bool) -> bool:
        emoji = "✅" if win else "❌"
        text = (
            f"{emoji} *CLOSE* `{pair} {tf}` `{side}` ({mdv2_escape(reason)})\n"
            f"exit: `{exit_price:.2f}` · PnL: `{pnl_r:+.2f}R`"
        )
        return self.send_message(text)

    def notify_promotion(self, pair: str, tf: str, kind: str, review: str) -> bool:
        text = (
            f"🚀 *SENTINEL {kind}* `{pair} {tf}`\n"
            f"_{mdv2_escape(review)}_"
        )
        return self.send_message(text)

    def notify_kill_switch(self, reason: str) -> bool:
        text = (
            f"🛑 *KILL-SWITCH TRIPPED*\n"
            f"_{mdv2_escape(reason)}_\n"
            f"paper loop halted - no further entries until cooldown clears."
        )
        return self.send_message(text)

    def notify_startup(self, version: str, pairs: list[str], decide_tf: str,
                       ctx_tfs: list[str], cycle_s: int, llm_mode: str,
                       open_n: int) -> bool:
        """Clean, modern startup card (Bahasa Indonesia, brand Vessavaṇa).

        Version is passed RAW (no escaping) so it renders as `v0.0.7`, never `v0\\.0\\.7`.
        No em-dashes are used; clean `·` / `:` separators only.
        """
        pair_s = " · ".join(pairs)
        ctx_s = " · ".join(ctx_tfs)
        text = (
            f"🤖 *Vessavaṇa* · *Bot PAPER aktif* `v{version}`\n"
            f"\n"
            f"*Pasangan*  : `{pair_s}`\n"
            f"*Keputusan* : `{decide_tf}` · eksekusi saat candle tutup\n"
            f"*Konteks*   : `{ctx_s}` · bias multi-timeframe\n"
            f"*Siklus*    : `{cycle_s} dtk`\n"
            f"*Mode*      : `PAPER` · tanpa order live\n"
            f"*LLM*       : `{llm_mode}`\n"
            f"*Posisi*    : `{open_n}` · dimuat ulang\n"
        )
        return self.send_message(text)

    def notify_health_check(self, version: str, region: str, open_n: int,
                            feed_ok: bool = True, notes: str = "") -> bool:
        """Explicit on-deploy + periodic heartbeat (doc 43). Lets the owner confirm the
        bot is alive and healthy without waiting for a trade to happen."""
        status = "sehat ✅" if feed_ok else "feed bermasalah ⚠️"
        text = (
            f"💓 *Health Check* · `v{version}`\n"
            f"\n"
            f"*Status*  : {status}\n"
            f"*Region*  : `{region}`\n"
            f"*Posisi*  : `{open_n}` terbuka\n"
            f"*Waktu*   : _{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n"
        )
        if notes:
            text += f"\n_{mdv2_escape(notes)}_"
        return self.send_message(text)

    def notify_deploy(self, version: str, changelog: str) -> bool:
        """Announce the deployed version + what changed (Bahasa Indonesia)."""
        body = mdv2_escape(changelog).strip() if changelog else "_Belum ada catatan rilis._"
        # keep each changelog line readable: replace leading '- ' bullets with '• '
        lines = []
        for ln in body.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            lines.append("• " + ln.lstrip("- ").lstrip("• "))
        body = "\n".join(lines[:12]) or "_Belum ada catatan rilis._"
        text = (
            f"🚀 *Vessavaṇa `v{version}` ter-deploy*\n"
            f"\n"
            f"*Perubahan:*\n"
            f"{body}"
        )
        return self.send_message(text)

    def notify_status(self, title: str, body_md: str) -> bool:
        return self.send_message(f"📊 *{mdv2_escape(title)}*\n\n{body_md}")

    def notify_status_30m(self, lines: list[str]) -> bool:
        """Periodic 30m status card (Bahasa Indonesia)."""
        body = "\n".join(lines) if lines else "_Belum ada trade dieksekusi._"
        return self.send_message(f"📊 *Vessavaṇa - Status (30m)*\n\n{body}")
