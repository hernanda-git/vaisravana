"""Phase 16 - DB stats + overall win-rate awareness (README/monitoring ask).

Verifies db.db_stats() computes per-table counts, total rows, on-disk size, and a
portfolio-wide win rate; and that the Telegram cards render cleanly in HTML mode
(raw version, no em-dash, no MarkdownV2 backslashes).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from db import init_db, db_stats, _fmt_bytes  # noqa: E402
from telegram_bot import TelegramNotifier  # noqa: E402


def _seed_trade(conn, trade_id, pair, tf, side, win, pnl):
    conn.execute(
        "INSERT INTO trade_logs (trade_id, pair, tf, side, win, loss, pnl_usd, "
        "close_reason, ts_fully_closed) VALUES (?,?,?,?,?,?,?,?,?)",
        (trade_id, pair, tf, side, win, 0 if win else 1, pnl, "TP" if win else "SL",
         "2026-07-26T00:00:00"),
    )
    conn.commit()


def test_fmt_bytes_units():
    assert _fmt_bytes(0) == "0 B"
    assert _fmt_bytes(512) == "512 B"
    assert _fmt_bytes(1536).endswith("KB")
    assert _fmt_bytes(5 * 1024 * 1024).endswith("MB")


def test_db_stats_counts_and_winrate(tmp_path):
    db_file = tmp_path / "vaisravana.db"
    conn = init_db(str(db_file))
    # 3 wins, 1 loss -> 75% overall
    _seed_trade(conn, "t1", "BTCUSDT", "1m", "BUY", 1, 10.0)
    _seed_trade(conn, "t2", "BTCUSDT", "1m", "BUY", 1, 8.0)
    _seed_trade(conn, "t3", "ETHUSDT", "1m", "SELL", 1, 5.0)
    _seed_trade(conn, "t4", "SOLUSDT", "1m", "BUY", 0, -6.0)
    conn.execute("INSERT INTO decisions_log (id, pair, tf, decision) VALUES "
                 "('d1','BTCUSDT','1m','ENTRY')")
    conn.commit()

    stats = db_stats(conn, str(db_file))
    assert stats["counts"]["trade_logs"] == 4
    assert stats["counts"]["decisions_log"] == 1
    assert stats["total_rows"] == 5
    assert stats["overall"]["n_closed"] == 4
    assert stats["overall"]["n_wins"] == 3
    assert stats["overall"]["n_losses"] == 1
    assert stats["overall"]["win_rate_pct"] == 75.0
    # real file on disk -> size > 0 and human string parses
    assert stats["size_bytes"] > 0
    assert stats["size_human"].split()[-1] in ("B", "KB", "MB", "GB", "TB")


def test_db_stats_empty_db_no_div_zero(tmp_path):
    conn = init_db(str(tmp_path / "empty.db"))
    stats = db_stats(conn, str(tmp_path / "empty.db"))
    assert stats["total_rows"] == 0
    assert stats["overall"]["win_rate_pct"] == 0.0
    assert stats["overall"]["n_closed"] == 0


def test_db_stats_memory_uses_pragma():
    conn = init_db(":memory:")
    stats = db_stats(conn, ":memory:")
    # in-memory -> file paths skipped, PRAGMA fallback gives a page-based size
    assert stats["size_bytes"] >= 0
    assert "size_human" in stats


class _Client:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None):
        self.calls.append(json)

        class _R:
            status_code = 200
            text = "ok"
        return _R()


def test_notify_db_stats_card_html_clean():
    n = TelegramNotifier("T", "C")
    n._client = _Client()
    stats = {
        "counts": {"trade_logs": 12, "decisions_log": 340, "results_log": 3,
                   "exec_events": 24, "system_health": 100},
        "total_rows": 479, "size_bytes": 1_500_000, "size_human": "1.4 MB",
        "overall": {"n_closed": 12, "n_wins": 10, "n_losses": 2, "win_rate_pct": 83.3},
    }
    assert n.notify_db_stats("0.0.8", stats) is True
    body = n._client.calls[0]["text"]
    assert n._client.calls[0]["parse_mode"] == "HTML"
    assert "v0.0.8" in body and "\\" not in body and "—" not in body
    assert "83.3%" in body and "1.4 MB" in body
    assert "trade_logs" in body and "<code>340</code>" in body


def test_notify_status_30m_with_overall_and_dbline():
    n = TelegramNotifier("T", "C")
    n._client = _Client()
    ok = n.notify_status_30m(
        ["`BTCUSDT 1m BUY`: n=5 WR=80.0% Exp=+0.40R"],
        overall="<b>WR total</b>  : <code>80.0%</code>",
        dbline="<b>DB</b>        : <code>1.4 MB</code> · <code>479</code> row",
    )
    assert ok is True
    body = n._client.calls[0]["text"]
    assert "WR total" in body and "1.4 MB" in body and "479" in body
    assert "\\" not in body and "—" not in body
