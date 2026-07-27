"""v0.0.24 P0-30 — boot-time R:R floor scan (doc: robustness plan P0-30).

Makes a sub-2:1 live OPEN position structurally unshippable.

The construction-time validator (config.py _rr_floor) rejects surfaces below
2:1, but an open trade's realized R:R = |tp - entry| / |entry - sl| depends on
the actual SL/TP written per trade. A transient mis-write (e.g. the BTCUSDT 1m
1.50:1 entry observed 2026-07-27) proved a sub-floor open trade is possible.

This module scans ALL open trades and flags any with R:R < floor. The boot
wiring treats a violation as a hard alert (and refuses new entries on the
offending pair until repaired) — it does NOT auto-mutate live positions.
"""

from __future__ import annotations

import sqlite3

FLOOR = 2.0  # owner mandate: 1 win must recover >= 2 losses


def trade_rr(side: str, entry_price: float, sl_price: float, tp_price: float) -> float:
    """Realized reward:risk of a trade from stored prices.

    BUY:  RR = (tp - entry) / (entry - sl)   (both positive when valid)
    SELL: RR = (entry - tp) / (sl - entry)
    Returns 0.0 if risk (denominator) is non-positive (invalid/missing SL).
    """
    if side == "BUY":
        reward = (tp_price - entry_price) if tp_price is not None else 0.0
        risk = (entry_price - sl_price) if sl_price is not None else 0.0
    else:  # SELL
        reward = (entry_price - tp_price) if tp_price is not None else 0.0
        risk = (sl_price - entry_price) if sl_price is not None else 0.0
    if risk <= 0:
        return 0.0
    return reward / risk


def scan_open_rr(conn: sqlite3.Connection, floor: float = FLOOR) -> list[dict]:
    """Return open trades whose realized R:R is below `floor`.

    Each dict: pair, tf, side, entry_price, sl_price, tp_price, rr.
    Empty list => floor is respected across the whole open book.
    """
    rows = conn.execute(
        """SELECT pair, tf, side, entry_price, sl_price, tp_price
           FROM trade_logs
           WHERE ts_closed IS NULL AND entry_price IS NOT NULL
             AND sl_price IS NOT NULL AND tp_price IS NOT NULL"""
    ).fetchall()
    bad: list[dict] = []
    for r in rows:
        rr = trade_rr(r["side"], r["entry_price"], r["sl_price"], r["tp_price"])
        if rr < floor - 1e-9:
            bad.append({
                "pair": r["pair"], "tf": r["tf"], "side": r["side"],
                "entry_price": r["entry_price"], "sl_price": r["sl_price"],
                "tp_price": r["tp_price"], "rr": round(rr, 4),
            })
    return bad


def assert_rr_floor(conn: sqlite3.Connection, floor: float = FLOOR) -> None:
    """Raise AssertionError listing any open trade below the floor.

    Used in a boot self-check. Caller decides how to react (alert / block pair).
    """
    bad = scan_open_rr(conn, floor)
    if bad:
        lines = ", ".join(f"{b['pair']} {b['tf']} {b['side']} R:R={b['rr']}" for b in bad)
        raise AssertionError(f"open trades below R:R {floor}:1 floor: {lines}")
