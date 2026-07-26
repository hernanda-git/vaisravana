"""Project Vaiśravaṇa — monitoring dashboard + alerting (Phase 10, doc 25/26, doc 30 §7).

Read-only over the runtime DB: trade_logs, results_log, system_health, exec_events.
Two surfaces:
  - `snapshot(conn)`   → DashboardSnapshot (programmatic / tests)
  - `render(snap)`     → terminal/markdown status block
  - `alerts(conn, since_id)` → human-alert stream: every promotion, rollback,
    kill-switch trip, and health incident MUST reach a human (doc 30 §7).

LIVE cutover itself stays HUMAN-GATED: nothing in this module (or the codebase)
flips a (pair, tf, side) to live without safety.promotion_gate(human_approved=True).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from evaluation import evaluate

ALERT_KINDS = ("IMPROVEMENT", "CORRECTION")           # promotion / refused diff
ALERT_HEALTH = ("FAIL",)                              # incidents + kill-switch


@dataclass
class KeyStatus:
    pair: str
    tf: str
    side: str
    n_trades: int
    win_rate_pct: float
    expectancy_r: float
    max_dd_pct: float
    open_position: bool


@dataclass
class DashboardSnapshot:
    keys: list[KeyStatus] = field(default_factory=list)
    incidents_24: int = 0
    last_config_ver: str = ""
    total_closed: int = 0
    total_open: int = 0


def _distinct_keys(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    return [
        (r["pair"], r["tf"], r["side"])
        for r in conn.execute(
            "SELECT DISTINCT pair, tf, side FROM trade_logs ORDER BY pair, tf, side"
        )
    ]


def snapshot(conn: sqlite3.Connection) -> DashboardSnapshot:
    snap = DashboardSnapshot()
    open_keys = {
        (r["pair"], r["tf"], r["side"])
        for r in conn.execute(
            "SELECT DISTINCT pair, tf, side FROM trade_logs WHERE ts_closed IS NULL"
        )
    }
    for pair, tf, side in _distinct_keys(conn):
        rep = evaluate(conn, pair, tf, side)
        snap.keys.append(KeyStatus(pair, tf, side, rep.n_trades, rep.win_rate_pct,
                                   rep.expectancy_r, rep.max_dd_pct,
                                   (pair, tf, side) in open_keys))
    snap.total_open = len(open_keys)
    snap.total_closed = conn.execute(
        "SELECT COUNT(*) c FROM trade_logs WHERE ts_closed IS NOT NULL"
    ).fetchone()["c"]
    snap.incidents_24 = conn.execute(
        "SELECT COUNT(*) c FROM system_health WHERE status='FAIL'"
    ).fetchone()["c"]
    row = conn.execute(
        "SELECT config_ver_to FROM results_log WHERE kind='IMPROVEMENT' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    snap.last_config_ver = row["config_ver_to"] if row else "1"
    return snap


def render(snap: DashboardSnapshot) -> str:
    lines = ["# Vaiśravaṇa — Status", "",
             f"- closed trades: {snap.total_closed} · open: {snap.total_open} "
             f"· health FAILs: {snap.incidents_24} · config v{snap.last_config_ver}",
             "",
             "| Pair | TF | Side | Trades | WR | Exp | MaxDD | Open |",
             "|------|----|------|--------|----|-----|-------|------|"]
    for k in snap.keys:
        lines.append(
            f"| {k.pair} | {k.tf} | {k.side} | {k.n_trades} | {k.win_rate_pct:.1f}% "
            f"| {k.expectancy_r:+.2f}R | {k.max_dd_pct:.2f}% | {'●' if k.open_position else '—'} |"
        )
    return "\n".join(lines)


@dataclass
class Alert:
    source: str      # 'results_log' | 'system_health'
    row_id: int
    kind: str        # IMPROVEMENT / CORRECTION / FAIL
    text: str


def alerts(
    conn: sqlite3.Connection,
    since_results_id: int = 0,
    since_health_id: int = 0,
) -> list[Alert]:
    """Everything a human must see (doc 30 §7): promotions, rollbacks/refusals,
    kill-switch trips and health incidents. Poll with last-seen ids."""
    out: list[Alert] = []
    for r in conn.execute(
        "SELECT id, kind, pair, tf, review FROM results_log WHERE id>? AND kind IN (?,?)"
        " ORDER BY id", (since_results_id, *ALERT_KINDS),
    ):
        out.append(Alert("results_log", r["id"], r["kind"],
                         f"[{r['kind']}] {r['pair']} {r['tf']}: {r['review']}"))
    for r in conn.execute(
        'SELECT id, "check", status, detail FROM system_health WHERE id>? AND status=?'
        " ORDER BY id", (since_health_id, ALERT_HEALTH[0]),
    ):
        out.append(Alert("system_health", r["id"], "FAIL",
                         f"[HEALTH FAIL] {r['check']}: {r['detail'] or ''}"))
    return out
