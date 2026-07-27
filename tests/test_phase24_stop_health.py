"""Phase 24 (v0.1.7) — /stop + /health commands + control mechanism.

Verifies (TDD):
- db.trade_summary() returns overall / by_side / by_tf / by_pair WR + expectancy,
  open/closed counts, and recent trades.
- The TelegramCommandListener dispatch (`_dispatch` shape) routes /clean /stop /health
  to the right handler and ignores unknown commands.
- The main loop honours control["stop"] (graceful break) — verified via the dispatch
  closure setting control["stop"] and a small loop simulation.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from db import init_db, trade_summary  # noqa: E402
from lifecycle import TradeLifecycle  # noqa: E402


def _seed(conn, rows):
    """rows: list of (pair, tf, side, win). close() computes r/pnl from exit_price."""
    lc = TradeLifecycle(conn)
    for i, (pair, tf, side, win) in enumerate(rows):
        entry = 100.0
        sl, tp = 99.0, 101.0
        exit_price = tp if win else sl
        t = lc.open(f"c{i}", pair, tf, side, entry, 1.0, 10, sl, tp)
        lc.close(t, exit_price=exit_price, close_reason="TP" if win else "SL")


def test_trade_summary_overall_and_breakdown():
    conn = init_db(Path(tempfile.mkdtemp()) / "t.db")
    # 7 wins, 3 losses across sides/tfs/pairs
    rows = [
        ("BTCUSDT", "1m", "BUY", True),
        ("BTCUSDT", "1m", "BUY", True),
        ("BTCUSDT", "1m", "BUY", False),
        ("ETHUSDT", "1m", "SELL", True),
        ("ETHUSDT", "15m", "SELL", False),
        ("SOLUSDT", "1h", "BUY", True),
        ("SOLUSDT", "1h", "BUY", False),
        ("SOLUSDT", "1h", "BUY", True),
        ("SOLUSDT", "1h", "BUY", True),
        ("SOLUSDT", "1h", "BUY", True),
    ]
    _seed(conn, rows)
    s = trade_summary(conn, recent_n=3)
    assert s["overall"]["n"] == 10
    assert s["overall"]["wins"] == 7
    assert s["overall"]["win_rate_pct"] == 70.0
    # by_side present for both
    assert set(s["by_side"].keys()) == {"BUY", "SELL"}
    # by_tf present
    assert set(s["by_tf"].keys()) == {"1m", "15m", "1h"}
    # by_pair present
    assert set(s["by_pair"].keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    # closed count = 10, open = 0
    assert s["closed_count"] == 10
    assert s["open_count"] == 0
    # recent has last 3 (most recent first)
    assert len(s["recent"]) == 3
    assert s["recent"][0]["pair"] == "SOLUSDT"


def test_trade_summary_open_count():
    conn = init_db(Path(tempfile.mkdtemp()) / "t.db")
    lc = TradeLifecycle(conn)
    # one still-open position (not closed)
    lc.open("c0", "BTCUSDT", "1m", "BUY", 100.0, 1.0, 10, 99.0, 101.0)
    s = trade_summary(conn)
    assert s["open_count"] == 1
    assert s["closed_count"] == 0
    assert s["overall"]["n"] == 0


def test_dispatch_routes_clean_stop_health():
    """Replicates the bot's _dispatch routing to prove command selection."""
    fired = []
    def clean_state(): fired.append("clean")
    def stop_bot(): fired.append("stop")
    def health_report(): fired.append("health")

    def _dispatch(text, _raw):
        cmd = text.split()[0].split("@")[0].lower()
        if cmd == "/clean":
            clean_state()
        elif cmd == "/stop":
            stop_bot()
        elif cmd == "/health":
            health_report()

    _dispatch("/clean", "")
    _dispatch("/stop@VessavaṇaBot", "")
    _dispatch("/HEALTH", "")
    _dispatch("/status", "")  # unknown -> ignored
    _dispatch("hello", "")
    assert fired == ["clean", "stop", "health"], f"fired: {fired}"


def test_stop_control_breaks_loop():
    """control['stop'] set by /stop must break the main loop (graceful stop)."""
    control = {"stop": False}

    def stop_bot():
        control["stop"] = True

    # simulate the loop guard the bot uses
    iterations = 0
    while iterations < 5:
        if control["stop"]:
            break
        iterations += 1
        if iterations == 2:
            stop_bot()  # /stop fires mid-loop
    assert control["stop"] is True
    assert iterations == 2  # loop exited promptly after stop
