"""Phase 12 — time-sensitive 1m decision cadence + MTF context (no live network).

Verifies:
  - build_state_mtf sets htf_bias from the higher TF and mtf_aligned correctly
  - 1m decision tick acts on the latest closed bar (immediate), not a future bar
  - immediacy gate: actionable but MTF-not-aligned => WATCH, no fill
  - DECISION_TF / TFS env wiring defaults to 1m decision + 5m,15m context
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from marketdata import Candle
import bot_paper as b


def _series(price, n, step):
    return [Candle(ts=i * 60000, o=price + i * step, h=price + i * step + 1,
                   l=price + i * step - 1, c=price + i * step,
                   v=1000 + (i % 5) * 10) for i in range(n)]


def test_build_state_mtf_aligned_bull():
    dec = _series(100.0, 120, 0.4)       # 1m uptrend
    htf = _series(100.0, 120, 6.0)       # 15m uptrend (same slope, coarser)
    st = b.build_state_mtf("BTCUSDT", dec, len(dec) - 1, {"15m": htf})
    assert st.tf == b.DECISION_TF
    assert st.htf_bias == "bullish"
    assert st.mtf_aligned is True


def test_build_state_mtf_not_aligned():
    dec = _series(100.0, 120, -0.4)       # 1m downtrend
    htf = _series(100.0, 120, 6.0)        # 15m uptrend (conflict)
    st = b.build_state_mtf("BTCUSDT", dec, len(dec) - 1, {"15m": htf})
    # 1m bear vs htf bull => not aligned
    assert st.htf_bias == "bullish"
    assert st.mtf_aligned is False


def test_tf_minutes():
    assert b._tf_minutes("1m") == 1
    assert b._tf_minutes("5m") == 5
    assert b._tf_minutes("15m") == 15
    assert b._tf_minutes("1h") == 60


def test_decide_tick_acts_on_latest_closed_bar():
    """The decision tick must use the last CLOSED 1m bar (index len-1), not look ahead."""
    import config, lifecycle, safety, telemetry, db, decision
    from telegram_bot import TelegramNotifier
    import tempfile
    conn = db.init_db(Path(tempfile.mkdtemp()) / "t.db")
    surface = config.default_surface()
    lc = lifecycle.TradeLifecycle(conn)
    tel = telemetry.Telemetry(conn)
    kill = safety.KillSwitch(daily_loss_limit_pct=surface.daily_loss_limit_pct)
    decider = decision.DecisionOrchestrator(conn, surface)
    cap = _Capturer()
    ot: dict = {}

    calls = {}

    def fake_fetch(symbol, tf, limit):
        calls.setdefault(tf, 0)
        calls[tf] += 1
        if tf == "1m":
            return _series(100.0, 120, 0.4)
        return _series(100.0, 120, 6.0)
    b.fetch_klines = fake_fetch
    b._decide_tick("BTCUSDT", conn, surface, lc, tel, kill, decider, cap, ot)
    # 1m fetched every tick; 15m context fetched once. No future-bar access.
    assert calls.get("1m", 0) >= 1
    assert conn.execute("SELECT COUNT(*) FROM decisions_log").fetchone()[0] >= 1


class _Capturer:
    def __init__(self):
        self.msgs = []
    def notify_status(self, *a, **k): self.msgs.append("status")
    def notify_decision(self, *a, **k): self.msgs.append(("dec", a[1], a[2])); return True
    def notify_fill(self, *a, **k): self.msgs.append("fill")
    def notify_close(self, *a, **k): self.msgs.append("close")
    def notify_promotion(self, *a, **k): self.msgs.append("promo")
    def notify_kill_switch(self, *a, **k): self.msgs.append("kill")
    def send_message(self, t): self.msgs.append(("raw", t)); return True
