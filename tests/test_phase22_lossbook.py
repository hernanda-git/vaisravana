"""Phase 22 (v0.1.4) — loss-book daily-loss accumulation in close handlers.

Verifies that _close() correctly accumulates realized losses into the loss_book
dict (used by the kill-switch for daily loss limits), and that loss_book=None safely
skips accumulation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest  # noqa: E402

from db import init_db  # noqa: E402
from lifecycle import TradeLifecycle  # noqa: E402
from telemetry import Telemetry  # noqa: E402
from safety import KillSwitch  # noqa: E402


class _DummyNotifier:
    """Minimal notifier stub — records notify_close calls."""
    def __init__(self):
        self.close_calls = []

    def notify_close(self, *a, **k):
        self.close_calls.append((a, k))
        return True

    def send_message(self, *a, **k):
        return True

    def notify_promotion(self, *a, **k):
        pass

    def exec_event(self, *a, **k):
        pass


def test_close_accumulates_loss_into_loss_book(tmp_path):
    """A losing close should debit loss_book['usd']."""
    db = init_db(tmp_path / "tx.db")
    lc = TradeLifecycle(db)
    tel = Telemetry(db)
    kill = KillSwitch(daily_loss_limit_pct=0.5)
    notifier = _DummyNotifier()

    loss_book = {"usd": 0.0, "day": "2026-07-26"}

    # Open a buy position
    t = lc.open("corr1", "BTCUSDT", "5m", "BUY",
                 entry_price=100.0, size=1.0, leverage=2.0,
                 sl_price=99.0, tp_price=102.0)

    open_trades = {("BTCUSDT", "5m", "BUY"): t}

    from bot_paper import _close

    # Close at a loss (SL hit)
    _close("BTCUSDT", "5m", "BUY", exit_price=99.0, reason="SL",
           conn=db, lc=lc, tel=tel, kill=kill, notifier=notifier,
           open_trades=open_trades, loss_book=loss_book)

    # loss_book should have increased by ~$1 (1.0 size, 100->99 = $1 loss)
    assert ("BTCUSDT", "5m", "BUY") not in open_trades, "trade should be removed"
    assert loss_book["usd"] > 0, f"expected positive loss, got {loss_book['usd']}"
    assert pytest.approx(loss_book["usd"], abs=0.5) == 1.0


def test_close_winning_trade_does_not_debit_loss_book(tmp_path):
    """A winning close should NOT change loss_book."""
    db = init_db(tmp_path / "tx2.db")
    lc = TradeLifecycle(db)
    tel = Telemetry(db)
    kill = KillSwitch(daily_loss_limit_pct=0.5)
    notifier = _DummyNotifier()

    loss_book = {"usd": 10.0, "day": "2026-07-26"}

    t = lc.open("corr2", "ETHUSDT", "15m", "BUY",
                 entry_price=100.0, size=1.0, leverage=2.0,
                 sl_price=99.0, tp_price=102.0)

    open_trades = {("ETHUSDT", "15m", "BUY"): t}

    from bot_paper import _close

    # Close at profit (TP hit)
    _close("ETHUSDT", "15m", "BUY", exit_price=102.0, reason="TP",
           conn=db, lc=lc, tel=tel, kill=kill, notifier=notifier,
           open_trades=open_trades, loss_book=loss_book)

    # loss_book should be unchanged (winning trade)
    assert loss_book["usd"] == 10.0


def test_close_loss_book_none_does_not_crash(tmp_path):
    """loss_book=None should not raise, just skip accumulation."""
    db = init_db(tmp_path / "tx3.db")
    lc = TradeLifecycle(db)
    tel = Telemetry(db)
    kill = KillSwitch(daily_loss_limit_pct=0.5)
    notifier = _DummyNotifier()

    t = lc.open("corr3", "SOLUSDT", "1m", "SELL",
                 entry_price=100.0, size=1.0, leverage=2.0,
                 sl_price=101.0, tp_price=98.0)

    open_trades = {("SOLUSDT", "1m", "SELL"): t}

    from bot_paper import _close

    # loss_book=None — must not throw
    _close("SOLUSDT", "1m", "SELL", exit_price=101.0, reason="SL",
           conn=db, lc=lc, tel=tel, kill=kill, notifier=notifier,
           open_trades=open_trades, loss_book=None)

    assert ("SOLUSDT", "1m", "SELL") not in open_trades
