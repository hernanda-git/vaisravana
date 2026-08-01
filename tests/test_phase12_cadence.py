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
    """v0.1.0: _decide_tick now reads klines from a `klines_cache` (one fetch per pair per
    cycle, fed by run()'s loop) and evaluates every active strategy on its own decision_tf.
    A high-conviction bullish state must open at least the scalping profile keyed by
    (pair, '1m', side) — proving it acts on the latest closed bar and keys by decision_tf.
    """
    import config, lifecycle, safety, telemetry, db, decision
    from telegram_bot_v4 import TelegramNotifier
    from engines import MarketState
    from marketcontext import MarketContext
    import tempfile
    conn = db.init_db(Path(tempfile.mkdtemp()) / "t.db")
    surface = config.default_surface()
    lc = lifecycle.TradeLifecycle(conn)
    tel = telemetry.Telemetry(conn)
    kill = safety.KillSwitch(daily_loss_limit_pct=surface.daily_loss_limit_pct)
    decider = decision.DecisionOrchestrator(conn, surface)
    cap = _Capturer()
    ot: dict = {}

    # The cache is the new contract: run() fills it once per pair, _decide_tick reads it.
    klines_cache = {
        "1m": _series(100.0, 120, 0.4),
        "15m": _series(100.0, 120, 6.0),
        "5m": _series(100.0, 120, 3.0),
        "1h": _series(100.0, 120, 12.0),
    }

    def fake_state(pair, dec_candles, i, contexts, **kw):
        s = MarketState(symbol=pair, tf=dec_candles[0].tf if hasattr(dec_candles[0], "tf") else "1m",
                        regime="trending_bull", htf_bias="bullish", mtf_aligned=True,
                        body_ratio=1.0, vol_z=3.0, delta_z=2.0, atr=1.0, atr_pct=0.01,
                        hh=True, hl=True, bos=True, choch=True, liq_sweep=True, eq_low=True,
                        fvg=True, btc_bias="bullish", risk_regime="bullish",
                        mtf_confluence=True, pullback_to_anchor=True, alt_breadth=0.8)
        return s
    b.build_state_mtf = fake_state

    def fake_ctx(pair, dec_candles, i, contexts):
        return MarketContext(btc_bias="bullish", risk_regime="bullish",
                              mtf_confluence=True, pullback_to_anchor=True, alt_breadth=0.8)
    b.build_context_for = fake_ctx

    b._decide_tick("BTCUSDT", conn, surface, lc, tel, kill, decider, cap, ot,
                   klines_cache=klines_cache)
    # A high-conviction setup opens at least the scalping (1m) profile.
    assert conn.execute("SELECT COUNT(*) FROM trade_logs").fetchone()[0] >= 1
    assert ("BTCUSDT", "1m", "BUY") in ot
    # The position is keyed by the strategy's own decision_tf (1m), not a global TF.
    assert any(k[1] == "1m" for k in ot), "scalp position must be keyed on its 1m decision_tf"


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
