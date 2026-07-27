"""Project Vaiśravaṇa — trade lifecycle + rolling win/loss metrics (doc 30 §4).

Every trade (win AND loss) writes a complete `trade_logs` row:
  - lifecycle timestamps: ts_opened, ts_filled, ts_tp_hit, ts_partial_close,
    ts_fully_closed, ts_closed
  - win/loss booleans (1/0)
  - rolling win_pct / loss_pct per (pair, tf, side) — doc 30 §4:
    "di-update (rolling per (pair×tf×side)) tiap trade close"

Uses the Telemetry fail-loud rule: DB errors raise TelemetryError via sqlite3.Error.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from telemetry import TelemetryError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OpenTrade:
    trade_id: str
    correlation_id: str
    pair: str
    tf: str
    side: str
    entry_price: float
    size: float
    leverage: float
    sl_price: float
    tp_price: float


class TradeLifecycle:
    def __init__(self, conn: sqlite3.Connection, config_ver: str = "surface-v1") -> None:
        self.conn = conn
        self.config_ver = config_ver

    def _exec(self, sql: str, params: tuple) -> None:
        try:
            self.conn.execute(sql, params)
            self.conn.commit()
        except sqlite3.Error as e:
            raise TelemetryError(f"trade_logs write failed: {e}") from e

    # --- open ---

    def open(
        self,
        correlation_id: str,
        pair: str,
        tf: str,
        side: str,
        entry_price: float,
        size: float,
        leverage: float,
        sl_price: float,
        tp_price: float,
        decision_id: str = "",
        spread_bps: float | None = None,
        regime: str = "",
        scores: dict | None = None,
        ts_filled: str | None = None,
    ) -> OpenTrade:
        trade_id = str(uuid.uuid4())
        now = _now_iso()
        self._exec(
            """INSERT INTO trade_logs
               (trade_id, correlation_id, pair, tf, side, ts_opened, ts_filled,
                entry_price, size, leverage, sl_price, tp_price, decision_id,
                spread_bps, regime, scores_json, config_ver)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (trade_id, correlation_id, pair, tf, side, now, ts_filled or now,
             entry_price, size, leverage, sl_price, tp_price, decision_id,
             spread_bps, regime, json.dumps(scores or {}), self.config_ver),
        )
        return OpenTrade(trade_id, correlation_id, pair, tf, side,
                         entry_price, size, leverage, sl_price, tp_price)

    # --- partial / tp events ---

    def mark_tp_hit(self, trade_id: str) -> None:
        self._exec("UPDATE trade_logs SET ts_tp_hit=? WHERE trade_id=?",
                   (_now_iso(), trade_id))

    def mark_partial_close(self, trade_id: str) -> None:
        self._exec("UPDATE trade_logs SET ts_partial_close=? WHERE trade_id=?",
                   (_now_iso(), trade_id))

    # --- close ---

    def close(
        self,
        trade: OpenTrade,
        exit_price: float,
        close_reason: str,          # TP/SL/TRAILING/STRUCTURE/MAXHOLD/PARTIAL
        fill_type: str = "MAKER",
        mfe_r: float | None = None,
        mae_r: float | None = None,
        fees_usd: float = 0.0,
        notes: str = "",
    ) -> dict:
        """Close the trade, compute PnL/R/win-loss, update rolling win_pct/loss_pct."""
        direction = 1.0 if trade.side == "BUY" else -1.0
        pnl_usd = (exit_price - trade.entry_price) * direction * trade.size
        denom = trade.entry_price * trade.size
        pnl_pct = (pnl_usd / denom * 100.0) if denom else 0.0
        risk = abs(trade.entry_price - trade.sl_price) * trade.size
        r_multiple = (pnl_usd / risk) if risk > 0 else 0.0
        win = 1 if pnl_usd > 0 else 0
        loss = 1 - win

        now = _now_iso()
        # hold_min from ts_opened
        row = self.conn.execute(
            "SELECT ts_opened FROM trade_logs WHERE trade_id=?", (trade.trade_id,)
        ).fetchone()
        hold_min = None
        if row and row["ts_opened"]:
            t0 = datetime.fromisoformat(row["ts_opened"])
            hold_min = (datetime.now(timezone.utc) - t0).total_seconds() / 60.0

        self._exec(
            """UPDATE trade_logs SET
                 ts_fully_closed=?, ts_closed=?, exit_price=?, pnl_usd=?, pnl_pct=?,
                 r_multiple=?, win=?, loss=?, close_reason=?, fill_type=?,
                 hold_min=?, mfe_r=?, mae_r=?, fees_usd=?, notes=?
               WHERE trade_id=?""",
            (now, now, exit_price, round(pnl_usd, 8), round(pnl_pct, 6),
             round(r_multiple, 4), win, loss, close_reason, fill_type,
             hold_min, mfe_r, mae_r, round(fees_usd, 8), notes, trade.trade_id),
        )

        win_pct, loss_pct = self._update_rolling(trade)
        return {
            "trade_id": trade.trade_id, "pnl_usd": pnl_usd, "r_multiple": r_multiple,
            "win": win, "loss": loss, "win_pct": win_pct, "loss_pct": loss_pct,
            "close_reason": close_reason,
        }

    def get_open_positions(self) -> dict:
        """Reload open (pair,tf,side) → OpenTrade from the DB.

        Restart-safe: after a deploy/machine restart the in-memory map is empty,
        but the persisted rows (ts_closed IS NULL) are still there. The bot calls
        this at boot so positions are never orphaned.
        """
        out: dict[tuple, OpenTrade] = {}
        for r in self.conn.execute(
            """SELECT trade_id, correlation_id, pair, tf, side, entry_price, size,
                      leverage, sl_price, tp_price
               FROM trade_logs WHERE ts_closed IS NULL"""
        ):
            out[(r["pair"], r["tf"], r["side"])] = OpenTrade(
                trade_id=r["trade_id"], correlation_id=r["correlation_id"],
                pair=r["pair"], tf=r["tf"], side=r["side"],
                entry_price=r["entry_price"], size=r["size"], leverage=r["leverage"],
                sl_price=r["sl_price"], tp_price=r["tp_price"],
            )
        return out

    def _update_rolling(self, trade: OpenTrade) -> tuple[float, float]:
        """Rolling win_pct/loss_pct per (pair, tf, side) over ALL closed trades so far
        (rolling-200 windowing is the Evaluation Engine's job, doc 30 §5)."""
        row = self.conn.execute(
            """SELECT COUNT(*) AS n, COALESCE(SUM(win),0) AS wins
               FROM trade_logs
               WHERE pair=? AND tf=? AND side=? AND ts_closed IS NOT NULL""",
            (trade.pair, trade.tf, trade.side),
        ).fetchone()
        n, wins = row["n"], row["wins"]
        win_pct = round(100.0 * wins / n, 4) if n else 0.0
        loss_pct = round(100.0 - win_pct, 4) if n else 0.0
        self._exec(
            "UPDATE trade_logs SET win_pct=?, loss_pct=? WHERE trade_id=?",
            (win_pct, loss_pct, trade.trade_id),
        )
        return win_pct, loss_pct

    def side_expectancy(self, side: str, n: int = 30) -> tuple[int, float]:
        """Rolling expectancy (Σ r_multiple) over the LAST `n` closed trades for `side`.

        Used by the entry gate to suppress a side that is systematically bleeding
        (e.g. BUY at -14R while SELL is positive). Returns (count, expectancy_r).
        A side with < 2 samples is reported as (0, 0.0) so the gate never blindly
        blocks an unproven side.
        """
        try:
            rows = self.conn.execute(
                """SELECT r_multiple FROM trade_logs
                   WHERE side=? AND ts_closed IS NOT NULL
                   ORDER BY ts_closed DESC LIMIT ?""",
                (side, n),
            ).fetchall()
        except sqlite3.Error:
            return 0, 0.0
        vals = [r["r_multiple"] for r in rows if r["r_multiple"] is not None]
        if len(vals) < 2:
            return len(vals), 0.0
        return len(vals), round(sum(vals), 3)
