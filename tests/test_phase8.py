"""Tests for Phase 8: kill-switch, promotion gate, paper orchestrator integration.

Includes the plan's integration test: 200 simulated PAPER trades at WR≥85% on one
pair×TF×side → promotion eligible; WR<85% → never promoted.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

from db import init_db  # noqa: E402
from engines import MarketState  # noqa: E402
from evaluation import evaluate  # noqa: E402
from lifecycle import TradeLifecycle  # noqa: E402
from orchestrator import PaperOrchestrator  # noqa: E402
from safety import (  # noqa: E402
    KillSwitch,
    health_clean,
    promotion_gate,
    should_demote,
)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _bull() -> MarketState:
    return MarketState(
        symbol="BTCUSDT", tf="5m", regime="trending_bull", htf_bias="bullish",
        body_ratio=0.95, vol_z=3.0, delta_z=3.0, bos=True, hh=True, hl=True,
        choch=True, liq_sweep=True, eq_low=True, fvg=True, atr_pct=0.01,
        spread_bps=1.0, funding_ok=True, adl_rank=1,
    )


# --- kill switch (doc 30 §7) ---

def test_kill_switch_daily_dd():
    ks = KillSwitch()
    tripped, reason = ks.check_global(daily_loss_pct=2.5)
    assert tripped and "DAILY_DD" in reason


def test_kill_switch_adl_and_feed():
    assert KillSwitch().check_global(0.0, adl_rank=4)[0]
    assert KillSwitch().check_global(0.0, feed_frozen=True)[0]
    assert not KillSwitch().check_global(0.1)[0]


def test_losing_streak_5_starts_30m_cooldown():
    now = [0.0]
    ks = KillSwitch(clock=lambda: now[0])
    for _ in range(5):
        ks.record_close("BTCUSDT", "5m", "BUY", win=False)
    assert ks.in_cooldown("BTCUSDT", "5m", "BUY")
    # other side unaffected (per pair×tf×side)
    assert not ks.in_cooldown("BTCUSDT", "5m", "SELL")
    now[0] = 30 * 60 + 1
    assert not ks.in_cooldown("BTCUSDT", "5m", "BUY")


def test_win_resets_streak():
    ks = KillSwitch()
    for _ in range(4):
        ks.record_close("BTCUSDT", "5m", "BUY", win=False)
    ks.record_close("BTCUSDT", "5m", "BUY", win=True)
    for _ in range(4):
        ks.record_close("BTCUSDT", "5m", "BUY", win=False)
    assert not ks.in_cooldown("BTCUSDT", "5m", "BUY")


# --- health_clean (doc 30 §6) ---

def test_health_clean_empty_table(conn):
    """Empty system_health is healthy."""
    assert health_clean(conn) is True


def test_health_clean_all_pass(conn):
    """Only PASS rows → healthy."""
    conn.execute('INSERT INTO system_health (ts, "check", status) VALUES (?,?,?)',
                 ("2026-01-01T00:00:00Z", "heartbeat", "PASS"))
    conn.execute('INSERT INTO system_health (ts, "check", status) VALUES (?,?,?)',
                 ("2026-01-01T00:01:00Z", "heartbeat", "PASS"))
    conn.commit()
    assert health_clean(conn) is True


def test_health_clean_any_fail_in_window(conn):
    """FAIL rows within the window → unhealthy."""
    conn.execute('INSERT INTO system_health (ts, "check", status) VALUES (?,?,?)',
                 ("2026-01-01T00:00:00Z", "kill_switch", "FAIL"))
    conn.commit()
    assert health_clean(conn, window_rows=100) is False


def test_health_clean_fail_outside_window(conn):
    """FAIL rows older than the window are ignored."""
    conn.execute('INSERT INTO system_health (ts, "check", status) VALUES (?,?,?)',
                 ("2026-01-01T00:00:00Z", "kill_switch", "FAIL"))
    conn.execute('INSERT INTO system_health (ts, "check", status) VALUES (?,?,?)',
                 ("2026-01-01T00:01:00Z", "heartbeat", "PASS"))
    conn.execute('INSERT INTO system_health (ts, "check", status) VALUES (?,?,?)',
                 ("2026-01-01T00:02:00Z", "heartbeat", "PASS"))
    conn.commit()
    # window of 2 means only the 2 PASS rows are checked → healthy
    assert health_clean(conn, window_rows=2) is True


def test_health_clean_mixed_with_fail(conn):
    """FAIL rows within the window → unhealthy even with PASS rows."""
    conn.execute('INSERT INTO system_health (ts, "check", status) VALUES (?,?,?)',
                 ("2026-01-01T00:00:00Z", "heartbeat", "PASS"))
    conn.execute('INSERT INTO system_health (ts, "check", status) VALUES (?,?,?)',
                 ("2026-01-01T00:01:00Z", "kill_switch", "FAIL"))
    conn.commit()
    assert health_clean(conn, window_rows=100) is False


# --- promotion gate integration (plan Phase 8 item 5) ---

def _simulate(conn, n_win, n_loss, side="BUY", tp_price=None, sl_price=None):
    lc = TradeLifecycle(conn)
    # default R:R 1.25 (win r=+1.25, loss r=-1.0). Callers can pass custom tp/sl to
    # craft a high-WR-but-negative-expectancy (fee-bleed) series.
    win_px = tp_price if tp_price is not None else (101.25 if side == "BUY" else 98.75)
    loss_px = sl_price if sl_price is not None else (99.0 if side == "BUY" else 101.0)
    # interleave losses evenly to avoid a terminal DD block
    seq = []
    ratio = max(1, n_win // max(1, n_loss))
    wi = li = 0
    while wi < n_win or li < n_loss:
        for _ in range(ratio):
            if wi < n_win:
                seq.append("W"); wi += 1
        if li < n_loss:
            seq.append("L"); li += 1
    for i, o in enumerate(seq):
        t = lc.open(f"c{side}{i}", "BTCUSDT", "5m", side, entry_price=100.0,
                    size=1.0, leverage=2.0,
                    sl_price=99.0 if side == "BUY" else 101.0,
                    tp_price=101.25 if side == "BUY" else 98.75)

        if o == "W":
            lc.close(t, exit_price=win_px, close_reason="TP")
        else:
            lc.close(t, exit_price=loss_px, close_reason="SL")


def test_200_trades_at_90pct_wr_is_promotion_eligible(conn):
    _simulate(conn, 180, 20)   # 90% WR over 200
    rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    assert rep.n_trades == 200 and rep.win_rate_pct == pytest.approx(90.0)
    dec = promotion_gate(rep, conn, human_approved=False)
    assert dec.eligible and not dec.live          # human gate still required
    assert any("HUMAN" in r for r in dec.reasons)
    dec2 = promotion_gate(rep, conn, human_approved=True)
    assert dec2.live


def test_moderate_wr_positive_expectancy_promotes(conn):
    """v0.1.0 expectancy-first: 60% WR at R:R 1.25 (+0.35R, PF 1.9) is genuinely +EV
    and MUST promote — the old 85% gate wrongly rejected exactly this profitable case."""
    _simulate(conn, 120, 80)   # 60% WR over 200
    rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    assert rep.win_rate_pct == pytest.approx(60.0)
    assert rep.expectancy_r > 0.10
    dec = promotion_gate(rep, conn, human_approved=True)
    assert dec.live, dec.reasons


def test_high_wr_negative_expectancy_never_promoted(conn):
    """Fee-bleed trap: 90% WR but tiny wins (+0.1R) vs big losses (-2R) => -0.11R, PF<1.
    Expectancy-first gate must REJECT this even though WR looks stellar."""
    _simulate(conn, 180, 20, tp_price=100.1, sl_price=98.0)  # win r=+0.1, loss r=-2.0
    rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    assert rep.win_rate_pct == pytest.approx(90.0)
    assert rep.expectancy_r <= 0.10
    dec = promotion_gate(rep, conn, human_approved=True)
    assert not dec.eligible and not dec.live
    assert any("EXPECTANCY" in r or "PF" in r for r in dec.reasons)


def test_wr_below_floor_blocks_promotion(conn):
    """WR below the 56% sanity floor blocks promotion even if other metrics pass."""
    _simulate(conn, 100, 100)   # 50% WR < 56% floor
    rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    dec = promotion_gate(rep, conn, human_approved=True)
    assert not dec.live and any("WR" in r for r in dec.reasons)


def test_dirty_health_blocks_promotion(conn):
    _simulate(conn, 180, 20)
    conn.execute('INSERT INTO system_health (ts, "check", status) VALUES (?,?,?)',
                 ("2026-07-26T00:00:00", "feed", "FAIL"))
    conn.commit()
    rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    dec = promotion_gate(rep, conn, human_approved=True)
    assert not dec.live and any("HEALTH" in r for r in dec.reasons)


def test_global_live_cap_blocks(conn):
    _simulate(conn, 180, 20)
    rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    dec = promotion_gate(rep, conn, human_approved=True, live_pairs_count=5)
    assert not dec.live and any("GLOBAL_CAP" in r for r in dec.reasons)


def test_post_live_demotion_on_wr_drop(conn):
    # v0.1.0: demotion is expectancy-first. A negative-expectancy series (90% WR but
    # +0.1R wins vs -2R losses => -0.11R) must demote despite the high WR.
    _simulate(conn, 180, 20, tp_price=100.1, sl_price=98.0)
    rep = evaluate(conn, "BTCUSDT", "5m", "BUY")
    assert should_demote(rep)
    # a healthy +EV side (60% WR, +0.35R) must NOT demote
    conn.execute("DELETE FROM trade_logs")
    conn.commit()
    _simulate(conn, 120, 80)
    rep_ok = evaluate(conn, "BTCUSDT", "5m", "BUY")
    assert not should_demote(rep_ok)


# --- paper orchestrator end-to-end (doc 30 §9 flow) ---

def test_orchestrator_full_cycle_decision_to_eval(conn):
    orch = PaperOrchestrator(conn)
    out = orch.on_candle_close(_bull(), entry_price=100.0, atr=1.0)
    assert out.record.actionable and out.opened is not None
    # SL/TP derived from ATR multipliers (v0.0.23 default: sl 1.0×ATR, tp 2.0×ATR, R:R 2:1)
    assert out.opened.sl_price == pytest.approx(99.0)
    assert out.opened.tp_price == pytest.approx(102.0)
    rep = orch.close_trade("BTCUSDT", "5m", "BUY", exit_price=102.0, reason="TP")
    assert rep.n_trades == 1 and rep.win_rate_pct == 100.0
    # full audit trail exists
    assert conn.execute("SELECT COUNT(*) c FROM decisions_log").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM trade_logs").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM exec_events").fetchone()["c"] == 2  # FILL+CLOSE


def test_orchestrator_halts_on_kill_switch(conn):
    orch = PaperOrchestrator(conn)
    out = orch.on_candle_close(_bull(), entry_price=100.0, atr=1.0, daily_loss_pct=0.6)
    assert out.halted and "DAILY_DD" in out.halt_reason
    assert conn.execute("SELECT COUNT(*) c FROM decisions_log").fetchone()["c"] == 0
    h = conn.execute('SELECT * FROM system_health').fetchone()
    assert h["check"] == "kill_switch" and h["status"] == "FAIL"


def test_orchestrator_no_stacking_same_key(conn):
    orch = PaperOrchestrator(conn)
    out1 = orch.on_candle_close(_bull(), entry_price=100.0, atr=1.0)
    assert out1.opened is not None
    out2 = orch.on_candle_close(_bull(), entry_price=100.5, atr=1.0)
    assert out2.opened is None   # max 1 per (pair×tf×side), doc 30 §7
