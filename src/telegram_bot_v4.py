"""
Telegram Notifier v4 — Clean, Elegant, Professional

Design principles:
- Minimalist card structure with subtle borders
- Clear visual hierarchy: header → trade details → balance → footer
- Consistent alignment using monospace for numbers
- Color-coded results (green for win, red for loss)
- All critical data visible at a glance
- Fee-aware: tracks open + close fees separately
- Graceful handling of missing data (shows "—" instead of 0.0)
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
    if text is None:
        text = ""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text)


def _fmt_price(v: float | None) -> str:
    """Format price — shows '—' for None/0, otherwise smart precision."""
    if v is None or v == 0.0:
        return "<code>—</code>"
    if v >= 1000:
        return f"<code>{v:,.2f}</code>"
    if v >= 1:
        return f"<code>{v:.4f}</code>"
    if v >= 0.01:
        return f"<code>{v:.6f}</code>"
    return f"<code>{v:.8f}</code>"


def _fmt_usd(v: float | None) -> str:
    """Format USD value with sign."""
    if v is None:
        return "<code>—</code>"
    return f"<code>{v:+.4f}$</code>"


def _fmt_r(v: float | None) -> str:
    """Format R-multiple."""
    if v is None:
        return "<code>—</code>"
    return f"<code>{v:+.2f}R</code>"


def _fmt_pct(v: float | None) -> str:
    """Format percentage."""
    if v is None:
        return "<code>—</code>"
    return f"<code>{v:.1f}%</code>"


def _fmt_number(v: float | None, decimals: int = 4) -> str:
    """Format generic number."""
    if v is None:
        return "<code>—</code>"
    return f"<code>{v:,.{decimals}f}</code>"


class TelegramNotifier:
    """Clean, elegant Telegram notifier v4."""

    def __init__(self, bot_token: str, chat_id: str | int):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base = f"https://api.telegram.org/bot{bot_token}"
        self._client: httpx.Client | None = None
        self._chat_dead: bool = False

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=10)
        return self._client

    def register_commands(self) -> bool:
        """Register slash commands with Telegram so / shows a hint list.

        Commands are designed for the owner to monitor and control the bot:
        - /status     — Bot status, WR, trades, wins/losses, open positions, balance
        - /performance — Detailed performance: WR, avg R, net PnL, fees, median R
        - /positions  — Open positions with live PnL, SL, TP, R
        - /trades     — Recent trades history with results
        - /version    — Current version, changelog, uptime
        - /stop       — Graceful shutdown
        - /resume     — Resume trading (if stopped)
        - /help       — List all commands
        """
        commands = [
            {"command": "vaisravana_status", "description": "Bot status, WR, trades, positions, balance"},
            {"command": "vaisravana_performance", "description": "Detailed performance: WR, avg R, net PnL, fees"},
            {"command": "vaisravana_positions", "description": "Open positions with live PnL, SL, TP, R"},
            {"command": "vaisravana_trades", "description": "Recent trades history with results"},
            {"command": "vaisravana_version", "description": "Current version, changelog, uptime"},
            {"command": "vaisravana_stop", "description": "Graceful shutdown after current cycle"},
            {"command": "vaisravana_resume", "description": "Resume trading (if stopped)"},
            {"command": "vaisravana_help", "description": "List all available commands"},
        ]
        try:
            r = httpx.post(
                f"{self._base}/setMyCommands",
                json={"commands": commands},
                timeout=10,
            )
            ok = r.status_code == 200 and r.json().get("ok")
            if ok:
                self.send_message(
                    "ℹ️ Commands registered: /vaisravana_status /vaisravana_performance "
                    "/vaisravana_positions /vaisravana_trades /vaisravana_version "
                    "/vaisravana_stop /vaisravana_resume /vaisravana_help"
                )
            return ok
        except Exception:
            return False

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
        if any(k in resp.text for k in ("chat not found", "bot was kicked",
                                         "bot is not a member", "Forbidden", "PEER_ID")):
            self._chat_dead = True
            log.error("Telegram chat %s unreachable", self.chat_id)
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

    # ── Helper: build a card ──────────────────────────────────────────

    def _card(
        self,
        header_emoji: str,
        header_text: str,
        body_lines: list[str],
        footer_lines: list[str] | None = None,
    ) -> str:
        """Build a unified card structure with clean borders."""
        lines = [
            f"{'╔' + '═' * 38 + '╗'}",
            f"║  {header_emoji}  <b>{header_text}</b>",
            f"{'╠' + '═' * 38 + '╣'}",
        ]
        for line in body_lines:
            lines.append(f"║  {line}")
        if footer_lines:
            lines.append(f"{'╠' + '═' * 38 + '╣'}")
            for line in footer_lines:
                lines.append(f"║  {line}")
        lines.append(f"{'╚' + '═' * 38 + '╝'}")
        return "\n".join(lines)

    # ── Trade Open ────────────────────────────────────────────────────

    def notify_trade_open(
        self,
        bot_name: str,
        pair: str,
        side: str,
        entry: float,
        sl: float,
        tp: float,
        size: float,
        notional: float,
        leverage: float,
        confidence: float,
        open_fee: float,
        wallet_balance: float,
        used_margin: float,
        unrealized: float,
        realized: float,
    ) -> bool:
        side_icon = "🟢" if side == "BUY" else "🔴"
        direction = "LONG" if side == "BUY" else "SHORT"
        pair_display = html_escape(pair)

        # Header
        header = f"{bot_name} — <b>{side_icon} {direction}</b>"

        # Body: trade details
        body = [
            f"<code>{pair_display}</code>",
            "",
            f"Entry   {_fmt_price(entry)}",
            f"SL      {_fmt_price(sl)}",
            f"TP      {_fmt_price(tp)}",
            "",
            f"Size      <code>{_fmt_number(size, 2)}</code>",
            f"Notional  <code>{_fmt_number(notional, 2)}$</code>",
            f"Leverage  <code>{_fmt_number(leverage, 1)}x</code>",
            f"Confidence <code>{_fmt_pct(confidence * 100)}</code>",
            "",
            f"Open Fee  <code>-{open_fee:.4f}$</code>",
        ]

        # Footer: balance & status
        free_margin = wallet_balance - used_margin if wallet_balance and used_margin is not None else None
        footer = [
            f"Balance   <code>{_fmt_number(wallet_balance, 4)}$</code>",
            f"Used      <code>{_fmt_number(used_margin, 4)}$</code>",
            f"Free      <code>{_fmt_number(free_margin, 4)}$</code>",
            f"Unreal.   {_fmt_usd(unrealized)}",
            f"Realized  {_fmt_usd(realized)}",
            "",
            f"⏳ Awaiting TP/SL...",
        ]

        return self.send_message(self._card("🌊", header, body, footer))

    # ── Trade Close ───────────────────────────────────────────────────

    def notify_trade_close(
        self,
        bot_name: str,
        pair: str,
        side: str,
        entry: float,
        exit_price: float,
        exit_reason: str,
        pnl_r: float,
        gross_pnl: float,
        open_fee: float,
        close_fee: float,
        net_pnl: float,
        wallet_balance: float,
        used_margin: float,
        unrealized: float,
        realized: float,
        total_trades: int,
        wins: int,
        losses: int,
        total_fees_paid: float,
    ) -> bool:
        is_win = net_pnl >= 0
        result_icon = "🟢" if is_win else "🔴"
        result_text = "WIN" if is_win else "LOSS"
        pnl_icon = "📈" if is_win else "📉"

        reason_map = {
            "tp_hit": "🎯 TP Hit",
            "sl_hit": "🛑 SL Hit",
            "max_age": "⏱ Max Age",
            "bias_flip": "🔄 Bias Flip",
            "conf_collapse": "💥 Conf Collapse",
            "bank_08r": "🏦 Bank 0.8R",
        }
        reason_text = reason_map.get(exit_reason, f"❓ {exit_reason}")

        total_fee = open_fee + close_fee
        pair_display = html_escape(pair)
        side_icon = "🟢" if side == "BUY" else "🔴"
        direction = "LONG" if side == "BUY" else "SHORT"

        # Header
        header = f"{bot_name} — <b>{result_icon} {result_text}</b>"

        # Body: trade details
        body = [
            f"{direction} {pair_display} {side_icon}",
            "",
            f"Entry     {_fmt_price(entry)}",
            f"Exit      {_fmt_price(exit_price)}",
            f"R         {_fmt_r(pnl_r)}",
            f"Gross PnL {_fmt_usd(gross_pnl)}",
            "",
            f"Open Fee  <code>-{open_fee:.4f}$</code>",
            f"Close Fee <code>-{close_fee:.4f}$</code>",
            f"Total Fee <code>-{total_fee:.4f}$</code>",
            "",
            f"{pnl_icon} Net PnL  <code>{net_pnl:+.4f}$</code>",
        ]

        # Footer: balance & stats
        free_margin = wallet_balance - used_margin if wallet_balance and used_margin is not None else None
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        footer = [
            f"Balance   <code>{_fmt_number(wallet_balance, 4)}$</code>",
            f"Used      <code>{_fmt_number(used_margin, 4)}$</code>",
            f"Free      <code>{_fmt_number(free_margin, 4)}$</code>",
            f"Unreal.   {_fmt_usd(unrealized)}",
            f"Realized  {_fmt_usd(realized)}",
            "",
            f"📊 WR: <code>{wins}/{total_trades} ({win_rate:.1f}%)</code>",
            f"📊 Fees:  <code>-{total_fees_paid:.4f}$</code>",
            "",
            f"Exit: {reason_text}",
        ]

        return self.send_message(self._card("🌊", header, body, footer))

    # ── Evaluation Report ─────────────────────────────────────────────

    def notify_evaluation(
        self,
        bot_name: str,
        window_id: str,
        trades_count: int,
        wins: int,
        losses: int,
        win_rate: float,
        avg_r: float,
        net_pnl: float,
        total_fees: float,
        aggregate_score: float,
        verdict: str,
        decision: str,
        confidence: float,
        balance: float,
        drawdown: float,
    ) -> bool:
        verdict_color = "🟢" if verdict == "green" else "🟡" if verdict == "yellow" else "🔴"
        decision_icon = {
            "persist_changes": "✅ Persist",
            "iterate": "🔄 Iterate",
            "rollback": "⏪ Rollback",
            "rollback_immediate": "⛔ Rollback Now",
            "pause_trading": "⏸ Pause",
            "stop_trading": "🛑 Stop",
            "research_more": "🔍 Research",
            "investigate_evaluators": "⚠️ Investigate",
        }.get(decision, "📋 Pending")

        body = [
            f"📊 <b>Window</b> — <code>{window_id}</code>",
            "",
            f"📈 Trades     <code>{trades_count}</code>",
            f"📈 WR         <code>{wins}W / {losses}L ({win_rate * 100:.1f}%)</code>",
            f"📈 Avg R      {_fmt_r(avg_r)}",
            f"📈 Net PnL    {_fmt_usd(net_pnl)}",
            f"💸 Fees       <code>-{total_fees:.4f}$</code>",
            "",
            f"{verdict_color} Score     <code>{aggregate_score:.2f}</code>",
        ]

        footer = [
            f"📋 Decision  {decision_icon}",
            f"📋 Confidence <code>{confidence:.0%}</code>",
            f"📋 Drawdown  <code>{drawdown * 100:.1f}%</code>",
            f"📋 Balance   <code>{balance:.4f}$</code>",
        ]

        return self.send_message(self._card("📊", f"{bot_name} — Evaluation", body, footer))

    # ── Startup ───────────────────────────────────────────────────────

    def notify_startup(self, version: str, pairs: list[str], decide_tf: str,
                       ctx_tfs: list[str], cycle_s: int, llm_mode: str,
                       open_n: int) -> bool:
        pair_s = " · ".join(pairs)
        ctx_s = " · ".join(ctx_tfs)

        body = [
            f"🚀 <b>Bot Started</b>",
            "",
            f"🤖 Bot       <code>vaisravana</code>",
            f"📦 Version   <code>v{html_escape(version)}</code>",
            f"💰 Mode      <code>PAPER</code>",
            f"💰 Balance   <code>10.0000$</code>",
            "",
            f"📍 Pairs     <code>{html_escape(pair_s)}</code>",
            f"📍 Decide TF <code>{html_escape(decide_tf)}</code>",
            f"📍 Context   <code>{html_escape(ctx_s)}</code>",
            f"📍 Cycle     <code>{cycle_s}s</code>",
            f"📍 LLM       <code>{html_escape(llm_mode)}</code>",
            f"📍 Open      <code>{open_n}</code> positions",
        ]

        return self.send_message(self._card("🚀", "Bot Startup", body))
    
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

    # ── Status 30m ────────────────────────────────────────────────────

    def notify_status_30m(self, lines: list[str], overall: str = "",
                          dbline: str = "") -> bool:
        body = lines if lines else ["<i>Belum ada trade dieksekusi.</i>"]
        head = []
        if overall:
            head.append(overall)
        if dbline:
            head.append(dbline)
        if head:
            head.append("")

        return self.send_message(self._card("📊", "Status (30m)", head + body))

    # ── Health Check ──────────────────────────────────────────────────

    def notify_health_check(self, version: str, region: str, open_n: int,
                            feed_ok: bool = True, notes: str = "") -> bool:
        status = "🟢 SEHAT" if feed_ok else "🔴 FEED BERMASALAH"

        body = [
            f"📡 Status    {status}",
            f"🌍 Region    <code>{html_escape(region)}</code>",
            f"📂 Positions <code>{open_n}</code> open",
            f"⏰ Uptime    <i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>",
        ]

        if notes:
            body.append(f"")
            body.append(f"<i>{html_escape(notes)}</i>")

        return self.send_message(self._card("💚", "Health Check", body))

    # ── Kill Switch ───────────────────────────────────────────────────

    def notify_kill_switch(self, reason: str) -> bool:
        body = [
            f"🛑 <b>Kill-Switch Tripped</b>",
            "",
            f"<i>{html_escape(reason)}</i>",
            "",
            f"Paper loop halted — no further entries.",
        ]
        return self.send_message(self._card("🛑", "Kill-Switch", body))

    # ── DB Stats ──────────────────────────────────────────────────────

    def notify_db_stats(self, version: str, stats: dict) -> bool:
        o = stats.get("overall", {})
        c = stats.get("counts", {})
        wr = o.get("win_rate_pct", 0.0)

        body = [
            f"v{html_escape(version)}",
            "",
            f"🗄️ <b>Database</b>",
            "",
            f"📈 WR       <code>{wr:.1f}%</code> "
            f"({o.get('n_wins', 0)}W / {o.get('n_losses', 0)}L · {o.get('n_closed', 0)} closed)",
            f"💾 Size     <code>{html_escape(stats.get('size_human', '0 B'))}</code>",
            f"📊 Rows     <code>{stats.get('total_rows', 0)}</code>",
            "",
            f"📋 trade_logs     <code>{c.get('trade_logs', 0)}</code>",
            f"📋 decisions_log  <code>{c.get('decisions_log', 0)}</code>",
            f"📋 results_log    <code>{c.get('results_log', 0)}</code>",
            f"📋 exec_events    <code>{c.get('exec_events', 0)}</code>",
            f"📋 system_health  <code>{c.get('system_health', 0)}</code>",
        ]

        return self.send_message(self._card("🗄️", "Database Stats", body))

    # ── Backward-compat methods (v3/v2 API) ─────────────────────────

    def notify_decision(
        self,
        pair: str,
        tf: str,
        signal: str,
        confidence: float,
        side: str,
        reason: str,
    ) -> bool:
        """Legacy: notify a decision/signal. Maps to a simple card."""
        side_icon = "🟢" if side == "BUY" else "🔴"
        direction = "LONG" if side == "BUY" else "SHORT"
        pair_display = html_escape(pair)
        reason_escaped = html_escape(reason)

        body = [
            f"<code>{pair_display}</code> {tf}",
            "",
            f"Signal    <code>{html_escape(signal)}</code>",
            f"Direction {side_icon} <code>{side}</code>",
            f"Confidence <code>{confidence:.0%}</code>",
            "",
            f"Reason    <code>{reason_escaped}</code>",
        ]
        return self.send_message(self._card("📡", "Decision", body))

    def notify_fill(
        self,
        pair: str,
        tf: str,
        side: str,
        entry: float,
        sl: float,
        tp: float,
        leverage: float,
        *,
        conf: float = 0.0,
        fee_usd: float = 0.0,
        size: float = 0.0,
        stats: dict | None = None,
    ) -> bool:
        """v5: Trade open notification — clean, professional, shows SL/TP/fee/balance."""
        side_icon = "🟢" if side == "BUY" else "🔴"
        direction = "LONG" if side == "BUY" else "SHORT"
        pair_display = html_escape(pair)

        # Extract stats
        balance = stats.get("balance", 0.0) if stats else 0.0
        # accept canonical paper_stats keys and legacy notifier aliases
        used = (stats.get("used_margin", stats.get("margin", stats.get("used", 0.0))) if stats else 0.0)
        unrealized = stats.get("unrealized", 0.0) if stats else 0.0
        realized = (stats.get("realized_pnl", stats.get("realized", 0.0)) if stats else 0.0)
        free = balance - used

        body = [
            f"{direction} {pair_display} {side_icon}",
            "",
            f"entry:    {_fmt_price(entry)}",
            f"sl:       {_fmt_price(sl)}",
            f"tp:       {_fmt_price(tp)}",
            "",
            f"Size      <code>{_fmt_number(size, 2)}</code>",
            f"Leverage  <code>{_fmt_number(leverage, 1)}x</code>",
            f"Conf      <code>{_fmt_pct(conf * 100)}</code>",
            "",
            f"Fee       <code>-{fee_usd:.4f}$</code>",
        ]

        footer = [
            f"Balance   <code>{_fmt_number(balance, 4)}$</code>",
            f"Used      <code>{_fmt_number(used, 4)}$</code>",
            f"Free      <code>{_fmt_number(free, 4)}$</code>",
            f"Unreal.   {_fmt_usd(unrealized)}",
            f"Realized  {_fmt_usd(realized)}",
            f"WR        <code>{stats.get('wins', 0) if stats else 0}/{stats.get('total_trades', 0) if stats else 0} ({stats.get('win_rate_pct', 0.0) if stats else 0.0:.1f}%)</code>",
            f"Fees      <code>-{stats.get('total_fees', 0.0) if stats else 0.0:.4f}$</code>",
            "",
            f"⏳ Engine monitoring SL/TP...",
        ]

        return self.send_message(self._card("🌊", f"OPEN {pair_display}", body, footer))

    def notify_close(
        self,
        pair: str,
        tf: str,
        side: str,
        exit_price: float,
        reason: str,
        pnl_r: float,
        is_win: bool,
        *,
        fee_usd: float = 0.0,
        net_usd: float = 0.0,
        stats: dict | None = None,
    ) -> bool:
        """v5: Trade close notification — clean, professional, shows fee/PnL/balance."""
        result_text = "WIN" if is_win else "LOSS"
        result_icon = "🟢" if is_win else "🔴"
        pnl_icon = "📈" if is_win else "📉"
        side_icon = "🟢" if side == "BUY" else "🔴"
        direction = "LONG" if side == "BUY" else "SHORT"
        pair_display = html_escape(pair)

        # Extract stats
        balance = stats.get("balance", 0.0) if stats else 0.0
        # accept canonical paper_stats keys and legacy notifier aliases
        used = (stats.get("used_margin", stats.get("margin", stats.get("used", 0.0))) if stats else 0.0)
        unrealized = stats.get("unrealized", 0.0) if stats else 0.0
        realized = (stats.get("realized_pnl", stats.get("realized", 0.0)) if stats else 0.0)
        free = balance - used

        # Win rate from DB if available
        win_rate = stats.get("win_rate_pct", 0.0) if stats else 0.0
        total_trades = stats.get("total_trades", 0) if stats else 0
        wins = stats.get("wins", 0) if stats else 0
        losses = stats.get("losses", 0) if stats else 0
        total_fees = stats.get("total_fees", 0.0) if stats else 0.0

        # Reason mapping
        reason_map = {
            "tp_hit": "🎯 TP Hit",
            "sl_hit": "🛑 SL Hit",
            "max_age": "⏱ Max Age",
            "bias_flip": "🔄 Bias Flip",
            "conf_collapse": "💥 Conf Collapse",
            "bank_08r": "🏦 Bank 0.8R",
            "SL": "🛑 SL Hit",
            "TP": "🎯 TP Hit",
            "MAXHOLD": "⏱ Max Age",
            "STRUCTURE": "📐 Structure",
        }
        reason_text = reason_map.get(reason, f"❓ {reason}")

        body = [
            f"{direction} {pair_display} {side_icon}",
            "",
            f"Exit      {_fmt_price(exit_price)}",
            f"R         {_fmt_r(pnl_r)}",
            f"pnl:      {_fmt_usd(net_usd)}",
            f"net:      {_fmt_usd(net_usd)}",
            "",
            f"Fee       <code>-{fee_usd:.4f}$</code>",
        ]

        footer = [
            f"Balance   <code>{_fmt_number(balance, 4)}$</code>",
            f"Used      <code>{_fmt_number(used, 4)}$</code>",
            f"Free      <code>{_fmt_number(free, 4)}$</code>",
            f"Unreal.   {_fmt_usd(unrealized)}",
            f"Realized  {_fmt_usd(realized)}",
            "",
            f"📊 WR: <code>{wins}/{total_trades} ({win_rate:.1f}%)</code>",
            f"📊 Fees:  <code>-{total_fees:.4f}$</code>",
            "",
            f"Exit: {reason_text}",
        ]

        return self.send_message(self._card("🌊", f"{result_text} {pair_display}", body, footer))

    def notify_partial(
        self, pair: str, tf: str, side: str, price: float, size: float,
        pnl_r: float, fee_usd: float, net_usd: float, remaining_size: float,
        remaining_sl: float | None, stats: dict | None = None,
    ) -> bool:
        """Notify a real partial close; never confuse it with a full close."""
        s = stats or {}
        balance = s.get("balance", 0.0)
        used = s.get("used_margin", s.get("margin", s.get("used", 0.0)))
        unrealized = s.get("unrealized", 0.0)
        realized = s.get("realized_pnl", s.get("realized", 0.0))
        free = balance - used
        direction = "LONG" if side == "BUY" else "SHORT"
        body = [
            f"<code>{html_escape(pair)}</code> {'🟢' if side == 'BUY' else '🔴'} {direction}",
            "", f"Partial exit  {_fmt_price(price)}",
            f"Size closed <code>{_fmt_number(size, 4)}</code>",
            f"Remaining   <code>{_fmt_number(remaining_size, 4)}</code>",
            f"R           {_fmt_r(pnl_r)}",
            f"Net PnL     {_fmt_usd(net_usd)}",
            f"Fee         <code>-{fee_usd:.4f}$</code>",
            f"Remaining SL {_fmt_price(remaining_sl)}",
        ]
        footer = [
            f"Balance   <code>{_fmt_number(balance, 4)}$</code>",
            f"Used      <code>{_fmt_number(used, 4)}$</code>",
            f"Free      <code>{_fmt_number(free, 4)}$</code>",
            f"Unreal.   {_fmt_usd(unrealized)}",
            f"Realized  {_fmt_usd(realized)}",
            "", "⏳ Remaining position is still monitored.",
        ]
        return self.send_message(self._card("🌊", f"PARTIAL {html_escape(pair)}", body, footer))

    def notify_status(self, pair: str, text: str) -> bool:
        """Legacy: notify a status update. Plain text fallback on parse error."""
        pair_display = html_escape(pair)
        text_escaped = html_escape(text)

        body = [
            f"<code>{pair_display}</code>",
            "",
            f"<i>{text_escaped}</i>",
        ]
        return self.send_message(self._card("📊", "Status", body))

    def notify_health_check(
        self,
        version: str,
        region: str,
        open_n: int,
        feed_ok: bool = True,
        notes: str = "",
    ) -> bool:
        """Health check with version header and SEHAT status."""
        status = "🟢 SEHAT" if feed_ok else "🔴 FEED BERMASALAH"

        body = [
            f"v{html_escape(version)}",
            "",
            f"📡 Status    {status}",
            f"🌍 Region    <code>{html_escape(region)}</code>",
            f"📂 Positions <code>{open_n}</code> open",
            f"⏰ Uptime    <i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</i>",
        ]

        if notes:
            body.append("")
            body.append(f"<i>{html_escape(notes)}</i>")

        return self.send_message(self._card("💚", "Health Check", body))


class TelegramCommandListener:
    """Polls Telegram getUpdates in a daemon thread and dispatches slash commands."""

    def __init__(self, notifier: "TelegramNotifier",
                 on_command: "callable[[str, str], None]",
                 poll_s: int = 2, allowed_chat_id: "str | int | None" = None,
                 bot_username: "str | None" = None) -> None:
        self._n = notifier
        self._on = on_command
        self._poll_s = poll_s
        self._allowed = str(allowed_chat_id) if allowed_chat_id not in (None, "", "0") else None
        self._bot_username = bot_username.lstrip("@").lower() if bot_username else None
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
            except Exception as e:
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
                continue
            text = (msg.get("text") or "").strip()
            if not text.startswith("/"):
                continue
            head = text.split()[0].lower()
            target = head.split("@", 1)[1] if "@" in head else None
            if target is not None and self._bot_username is not None and target != self._bot_username:
                continue
            try:
                self._on(text, text)
            except Exception as e:
                log.exception("tg command handler error: %s", e)