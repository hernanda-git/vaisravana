"""Telegram notifier for Project Vaiśravaṇa (Phase 10 / Fly deploy).

Mirrors learnernoearner-listener's notifier exactly:
  - env TELEGRAM_BOT_TOKEN + NOTIFY_CHAT_ID (Fly secrets) -> Bot API -> your channel
  - HTML parse mode (robust: only & < > need escaping; version/dots/dashes/parens are
    safe, so "v0.0.8" always renders raw and never shows literal backslashes)
  - HTML attempt, then plain-text fallback (tags stripped) so a notification is NEVER
    silently lost
  - 3950-char truncation guard (Telegram caps at 4096)

This bot is PAPER-only (no live orders). It reports the startup card, health checks,
decisions, fills, closes, promotions, kill-switch trips, and periodic status in one
Telegram channel.

Rendering policy (fixes the old backslash / em-dash artifacts, doc 43):
  - Versions and codes go inside <code> -> render raw as v0.0.8 (never v0\\.0\\.8).
  - Em-dashes (—) are never used; clean separators (·, :, -) only.
  - All free-text (reasons, changelog, titles) goes through html_escape.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("vaisravana.notifier.telegram")

_TAG_RE = re.compile(r"<[^>]+>")


def html_escape(text: str) -> str:
    """Escape the three HTML-significant chars in dynamic content."""
    if text is None:
        text = ""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text)


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

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if self._chat_dead:
            return False
        MAX_LEN = 3950
        if len(text) > MAX_LEN:
            text = text[:MAX_LEN - 40] + "\n\n… (truncated)"
        if not self.bot_token:
            log.info("[No bot token] %s", _strip_tags(text)[:100])
            return False
        client = self._get_client()
        resp = client.post(f"{self._base}/sendMessage", json={
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
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
        if parse_mode != "plain" and "parse entities" in resp.text:
            plain = _strip_tags(text)
            resp2 = client.post(f"{self._base}/sendMessage", json={
                "chat_id": self.chat_id,
                "text": plain,
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
            f"{icon} <b>{html_escape(action)}</b> <code>{html_escape(pair)} {html_escape(tf)}</code>\n"
            f"side: <code>{html_escape(side or '-')}</code> · score: <code>{score:.3f}</code>\n"
            f"<i>{html_escape(reason)}</i>"
        )
        return self.send_message(text)

    def notify_fill(self, pair: str, tf: str, side: str, entry: float,
                    sl: float, tp: float, lev: float, strategy: str = "") -> bool:
        strat = f" · <b>{html_escape(strategy)}</b>" if strategy else ""
        text = (
            f"📈 <b>PAPER FILL</b> <code>{html_escape(pair)} {html_escape(tf)}</code> "
            f"<code>{html_escape(side)}</code>{strat}\n"
            f"entry: <code>{entry:.2f}</code> · sl: <code>{sl:.2f}</code> · "
            f"tp: <code>{tp:.2f}</code> · lev: <code>{lev}x</code>\n"
            f"🕐 <i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>"
        )
        return self.send_message(text)

    def notify_close(self, pair: str, tf: str, side: str, exit_price: float,
                     reason: str, pnl_r: float, win: bool) -> bool:
        emoji = "✅" if win else "❌"
        text = (
            f"{emoji} <b>CLOSE</b> <code>{html_escape(pair)} {html_escape(tf)}</code> "
            f"<code>{html_escape(side)}</code> ({html_escape(reason)})\n"
            f"exit: <code>{exit_price:.2f}</code> · PnL: <code>{pnl_r:+.2f}R</code>"
        )
        return self.send_message(text)

    def notify_promotion(self, pair: str, tf: str, kind: str, review: str) -> bool:
        text = (
            f"🚀 <b>SENTINEL {html_escape(kind)}</b> <code>{html_escape(pair)} {html_escape(tf)}</code>\n"
            f"<i>{html_escape(review)}</i>"
        )
        return self.send_message(text)

    def notify_kill_switch(self, reason: str) -> bool:
        text = (
            f"🛑 <b>KILL-SWITCH TRIPPED</b>\n"
            f"<i>{html_escape(reason)}</i>\n"
            f"paper loop halted - no further entries until cooldown clears."
        )
        return self.send_message(text)

    def notify_startup(self, version: str, pairs: list[str], decide_tf: str,
                       ctx_tfs: list[str], cycle_s: int, llm_mode: str,
                       open_n: int) -> bool:
        """Clean, modern startup card (Bahasa Indonesia, brand Vessavaṇa).

        Version is rendered inside <code> -> shows as v0.0.8 (raw, no backslashes).
        No em-dashes are used; clean · / : separators only.
        """
        pair_s = " · ".join(pairs)
        ctx_s = " · ".join(ctx_tfs)
        text = (
            f"🤖 <b>Vessavaṇa</b> · <b>Bot PAPER aktif</b> <code>v{html_escape(version)}</code>\n"
            f"\n"
            f"<b>Pasangan</b>  : <code>{html_escape(pair_s)}</code>\n"
            f"<b>Keputusan</b> : <code>{html_escape(decide_tf)}</code> · eksekusi saat candle tutup\n"
            f"<b>Konteks</b>   : <code>{html_escape(ctx_s)}</code> · bias multi-timeframe\n"
            f"<b>Siklus</b>    : <code>{cycle_s} dtk</code>\n"
            f"<b>Mode</b>      : <code>PAPER</code> · tanpa order live\n"
            f"<b>LLM</b>       : <code>{html_escape(llm_mode)}</code>\n"
            f"<b>Posisi</b>    : <code>{open_n}</code> · dimuat ulang\n"
        )
        return self.send_message(text)

    def notify_health_check(self, version: str, region: str, open_n: int,
                            feed_ok: bool = True, notes: str = "") -> bool:
        """Explicit on-deploy + periodic heartbeat (doc 43). Lets the owner confirm the
        bot is alive and healthy without waiting for a trade to happen."""
        status = "sehat ✅" if feed_ok else "feed bermasalah ⚠️"
        text = (
            f"💓 <b>Health Check</b> · <code>v{html_escape(version)}</code>\n"
            f"\n"
            f"<b>Status</b>  : {status}\n"
            f"<b>Region</b>  : <code>{html_escape(region)}</code>\n"
            f"<b>Posisi</b>  : <code>{open_n}</code> terbuka\n"
            f"<b>Waktu</b>   : <i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>\n"
        )
        if notes:
            text += f"\n<i>{html_escape(notes)}</i>"
        return self.send_message(text)

    def notify_deploy(self, version: str, changelog: str) -> bool:
        """Announce the deployed version + what changed (Bahasa Indonesia)."""
        body = (changelog or "").strip()
        lines = []
        for ln in body.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            lines.append("• " + ln.lstrip("- ").lstrip("• "))
        body = html_escape("\n".join(lines[:12])) or "<i>Belum ada catatan rilis.</i>"
        text = (
            f"🚀 <b>Vessavaṇa <code>v{html_escape(version)}</code> ter-deploy</b>\n"
            f"\n"
            f"<b>Perubahan:</b>\n"
            f"{body}"
        )
        return self.send_message(text)

    def notify_status(self, title: str, body_md: str) -> bool:
        return self.send_message(f"📊 <b>{html_escape(title)}</b>\n\n{body_md}")

    def notify_status_30m(self, lines: list[str], overall: str = "",
                          dbline: str = "") -> bool:
        """Periodic 30m status card (Bahasa Indonesia).

        `overall` = portfolio-wide win-rate line, `dbline` = DB size/row summary,
        both rendered above the per-series breakdown so the owner can watch the
        aggregate win rate and DB growth at a glance.
        """
        body = "\n".join(lines) if lines else "<i>Belum ada trade dieksekusi.</i>"
        head = ""
        if overall:
            head += f"{overall}\n"
        if dbline:
            head += f"{dbline}\n"
        if head:
            head += "\n"
        return self.send_message(f"📊 <b>Vessavaṇa - Status (30m)</b>\n\n{head}{body}")

    def notify_db_stats(self, version: str, stats: dict) -> bool:
        """Standalone DB-awareness card: overall win rate + per-table row counts +
        on-disk size, so the owner can monitor database growth over time (doc 43)."""
        o = stats.get("overall", {})
        c = stats.get("counts", {})
        wr = o.get("win_rate_pct", 0.0)
        text = (
            f"🗄️ <b>Database - Vessavaṇa</b> · <code>v{html_escape(version)}</code>\n"
            f"\n"
            f"<b>Win rate</b>  : <code>{wr:.1f}%</code> "
            f"({o.get('n_wins', 0)}W / {o.get('n_losses', 0)}L · {o.get('n_closed', 0)} closed)\n"
            f"<b>Ukuran DB</b> : <code>{html_escape(stats.get('size_human', '0 B'))}</code>\n"
            f"<b>Total row</b> : <code>{stats.get('total_rows', 0)}</code>\n"
            f"\n"
            f"<b>trade_logs</b>     : <code>{c.get('trade_logs', 0)}</code>\n"
            f"<b>decisions_log</b>  : <code>{c.get('decisions_log', 0)}</code>\n"
            f"<b>results_log</b>    : <code>{c.get('results_log', 0)}</code>\n"
            f"<b>exec_events</b>    : <code>{c.get('exec_events', 0)}</code>\n"
            f"<b>system_health</b>  : <code>{c.get('system_health', 0)}</code>\n"
        )
        return self.send_message(text)


    def notify_health(self, version: str, summary: dict, db_stats: dict | None = None,
                      control_state: str = "RUNNING") -> bool:
        """Full `/health` card: win rates (overall/side/tf/pair), all trades, summary.

        `summary` comes from db.trade_summary(); `db_stats` from db.db_stats()."""
        o = summary.get("overall", {})
        lines = [f"🩺 <b>Vessavaṇa Health — v{html_escape(version)}</b> · <code>{control_state}</code>", ""]
        # overall
        lines.append(f"<b>Overall</b>: WR <code>{o.get('win_rate_pct',0):.1f}%</code> "
                     f"({o.get('wins',0)}W/{o.get('losses',0)}L · {o.get('n',0)} closed) · "
                     f"Exp <code>{o.get('expectancy_r',0):+.3f}R</code> · PnL <code>${o.get('pnl_usd',0):.2f}</code>")
        # by side
        by_side = summary.get("by_side", {})
        if by_side:
            s = " · ".join(
                f"{k}: <code>{v['win_rate_pct']:.1f}%</code> (Exp {v['expectancy_r']:+.3f}R)"
                for k, v in by_side.items())
            lines.append(f"<b>By side</b>: {s}")
        # by tf
        by_tf = summary.get("by_tf", {})
        if by_tf:
            t = " · ".join(
                f"{k}: <code>{v['win_rate_pct']:.1f}%</code> (Exp {v['expectancy_r']:+.3f}R)"
                for k, v in sorted(by_tf.items()))
            lines.append(f"<b>By tf</b>: {t}")
        # worst/best pairs
        by_pair = summary.get("by_pair", {})
        if by_pair:
            ranked = sorted(by_pair.items(), key=lambda kv: kv[1]["expectancy_r"])
            worst = " · ".join(f"{p} {b['expectancy_r']:+.2f}R" for p, b in ranked[:3])
            best = " · ".join(f"{p} {b['expectancy_r']:+.2f}R" for p, b in ranked[-3:][::-1])
            lines.append(f"<b>Worst</b>: {worst}")
            lines.append(f"<b>Best</b>: {best}")
        # counts
        lines.append(f"<b>Open</b>: <code>{summary.get('open_count',0)}</code> · "
                     f"<b>Closed</b>: <code>{summary.get('closed_count',0)}</code>")
        # DB
        if db_stats:
            lines.append(f"<b>DB</b>: <code>{html_escape(db_stats.get('size_human','0 B'))}</code> · "
                         f"<code>{db_stats.get('total_rows',0)}</code> rows")
        # recent
        recent = summary.get("recent", [])
        if recent:
            lines.append("")
            lines.append("<b>Recent trades:</b>")
            for r in recent[:8]:
                sign = "🟢" if r["win"] else "🔴"
                lines.append(f"{sign} {r['pair']} {r['side']} {r['tf']} "
                             f"R<code>{r['r_multiple']:+.2f}</code> · {r['close_reason']}")
        return self.send_message("\n".join(lines))



class TelegramCommandListener:
    """Polls Telegram `getUpdates` in a daemon thread and dispatches slash commands.

    Owner-only control surface for the running bot (e.g. `/clean`). The bot is otherwise
    send-only; this adds inbound command handling without a webhook. Uses the same httpx
    client as the notifier. Offsets are tracked so each update is handled once.
    """

    def __init__(self, notifier: "TelegramNotifier",
                 on_command: "callable[[str, str], None]",
                 poll_s: int = 2, allowed_chat_id: "str | int | None" = None) -> None:
        self._n = notifier
        self._on = on_command
        self._poll_s = poll_s
        self._allowed = str(allowed_chat_id) if allowed_chat_id is not None else None
        self._offset = 0
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as e:  # never let polling kill the bot
                log.debug("tg command poll error: %s", e)
            self._stop.wait(self._poll_s)

    def _poll_once(self) -> None:
        client = self._n._get_client()
        try:
            resp = client.get(f"{self._n._base}/getUpdates",
                              params={"offset": self._offset, "timeout": 1})
        except Exception as e:
            log.debug("tg getUpdates failed: %s", e)
            return
        if resp.status_code != 200:
            return
        try:
            data = resp.json()
        except Exception:
            return
        for upd in data.get("result", []):
            self._offset = upd.get("update_id", self._offset) + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            chat_id = msg.get("chat", {}).get("id")
            if self._allowed is not None and str(chat_id) != self._allowed:
                continue  # ignore commands from other chats
            text = (msg.get("text") or "").strip()
            if text.startswith("/"):
                try:
                    self._on(text, text)
                except Exception as e:
                    log.exception("tg command handler error: %s", e)
