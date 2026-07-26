"""Telegram notifier for Project Vaiśravaṇa (Phase 10 / Fly deploy).

Mirrors learnernoearner-listener's notifier exactly:
  - env TELEGRAM_BOT_TOKEN + NOTIFY_CHAT_ID (Fly secrets) → Bot API → your channel
  - _md_escape on every dynamic field so "can't parse entities" never eats an alert
  - Markdown attempt, then plain-text fallback so a notification is NEVER silently lost
  - 3950-char truncation guard (Telegram caps at 4096)

This bot is PAPER-only (no live orders). It reports decisions, fills, closes,
promotions, kill-switch trips, and periodic status — the same way the listener
reports trades, so everything lands in one Telegram channel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("vaisravana.notifier.telegram")

_MD_SPECIAL = r"_*[]()~`>#+-=|{}.!"


def _md_escape(text: str) -> str:
    """Escape Telegram Markdown (v1) special chars in dynamic content."""
    if not text:
        return text
    return "".join("\\" + c if c in _MD_SPECIAL else c for c in str(text))


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
            trunc = f"\n\n_... truncated ({len(text) - MAX_LEN} chars omitted)_"
            text = text[: MAX_LEN - len(trunc)] + trunc
        if not self.bot_token:
            log.info("[No bot token] %s", text[:100])
            return False
        client = self._get_client()
        resp = client.post(f"{self._base}/sendMessage", json={
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
        if resp.status_code == 200:
            return True
        # Permanent, non-retryable chat errors (bot not a member / kicked / forbidden):
        # stop hammering — surface once and go quiet until the next deploy.
        if any(k in resp.text for k in ("chat not found", "bot was kicked",
                                         "bot is not a member", "Forbidden", "PEER_ID")):
            self._chat_dead = True
            log.error("Telegram chat %s unreachable (%s) — notifications disabled "
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
            f"{icon} **{action}** `{pair} {tf}`\n"
            f"side: `{side or '-'}` · score: `{score:.3f}`\n"
            f"_{_md_escape(reason)}_"
        )
        return self.send_message(text)

    def notify_fill(self, pair: str, tf: str, side: str, entry: float,
                    sl: float, tp: float, lev: float) -> bool:
        text = (
            f"📈 **PAPER FILL** `{pair} {tf}` `{side}`\n"
            f"entry: `{entry:.2f}` · sl: `{sl:.2f}` · tp: `{tp:.2f}` · lev: `{lev}x`\n"
            f"🕐 _{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"
        )
        return self.send_message(text)

    def notify_close(self, pair: str, tf: str, side: str, exit_price: float,
                     reason: str, pnl_r: float, win: bool) -> bool:
        emoji = "✅" if win else "❌"
        text = (
            f"{emoji} **CLOSE** `{pair} {tf}` `{side}` ({_md_escape(reason)})\n"
            f"exit: `{exit_price:.2f}` · PnL: `{pnl_r:+.2f}R`"
        )
        return self.send_message(text)

    def notify_promotion(self, pair: str, tf: str, kind: str, review: str) -> bool:
        text = (
            f"🚀 **SENTINEL {kind}** `{pair} {tf}`\n"
            f"_{_md_escape(review)}_"
        )
        return self.send_message(text)

    def notify_kill_switch(self, reason: str) -> bool:
        text = (
            f"🛑 **KILL-SWITCH TRIPPED**\n"
            f"_{_md_escape(reason)}_\n"
            f"paper loop halted — no further entries until cooldown clears."
        )
        return self.send_message(text)

    def notify_deploy(self, version: str, changelog: str) -> bool:
        """Phase 13 — announce the deployed version + what changed on (re)start."""
        body = _md_escape(changelog).strip() if changelog else "_no changelog entry_"
        text = (
            f"🚀 **Vaiśravaṇa deployed** `v{_md_escape(version)}`\n"
            f"_{body}_"
        )
        return self.send_message(text)

    def notify_status(self, title: str, body_md: str) -> bool:
        return self.send_message(f"📊 **{_md_escape(title)}**\n\n{body_md}")
