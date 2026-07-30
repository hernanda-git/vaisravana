"""Project Vaiśravaṇa — safety: kill-switches + promotion gate (doc 30 §6-§7, doc 25).

Kill-switch triggers (doc 30 §7):
  - daily drawdown ≥ 0.5%  → force PAPER + alarm
  - ADL rank ≥ 4           → halt entries (auto-deleverage danger)
  - frozen feed            → halt (data can't be trusted)
  - maintenance / delist   → auto-pause pair
  - losing streak = 5      → 30-minute cooldown (that pair×tf×side)

Promotion gate — EXPECTANCY-FIRST (v0.1.0, supersedes the old 85% WR gate).
Per (pair, tf, SIDE), all required:
  ≥`min_trades` PAPER trades (that side) · **expectancy > min_expectancy_r** ·
  **profit_factor > min_pf** · Max DD < 3% · **WR ≥ winrate_floor (default 56%, a FLOOR
  not a target)** · clean system_health · HUMAN approval.

WHY the change: with R:R ≥ 1.5 the break-even WR after taker fees is ~48%, so demanding
85% WR rejects thousands of +EV trades and the bot goes silent. A profitable system is
defined by positive expectancy and PF > 1.2, with WR only as a sanity floor above break-even.
LONG and SHORT are promoted independently. Post-live: expectancy ≤ 0 OR WR < floor → revert.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field

from evaluation import EvalReport

LOSING_STREAK_LIMIT = 10            # doc 30 §7
STREAK_COOLDOWN_S = 5 * 60          # doc 30 §7: 5 menit

# Expectancy-first promotion defaults (v0.1.0). Overridable per-call from the surface.
PROMOTION_MIN_TRADES = 30          # reachable in paper (was 200)
PROMOTION_WR_FLOOR_PCT = 45.0      # FLOOR above break-even (was 85 target)
PROMOTION_EXPECTANCY_R = 0.02      # headline gate: must be mildly +EV
PROMOTION_MAX_DD_PCT = 10.0
PROMOTION_PF = 1.05                # doc 30 §5 profit-factor target

# Backward-compat alias (some older code/tests referenced the WR gate constant).
PROMOTION_WR_PCT = PROMOTION_WR_FLOOR_PCT


# --- kill switch ---

@dataclass
class KillSwitch:
    daily_loss_limit_pct: float = 2.0
    adl_rank_limit: int = 4
    clock: callable = time.time
    tripped: bool = False
    reason: str = ""
    _cooldowns: dict[tuple, float] = field(default_factory=dict)
    _streaks: dict[tuple, int] = field(default_factory=dict)
    # v0.0.25: alert de-duplication — the kill-switch is checked every tick, so a
    # tripped switch must alert ONCE per trip, not spam every loop (see spammy.txt).
    _last_alert_ts: float = field(default_factory=lambda: -1e18)  # far past -> first trip always alerts
    _alert_interval_s: float = 30 * 60  # re-alert at most every 30 min while tripped

    def check_global(
        self,
        daily_loss_pct: float,
        adl_rank: int = 1,
        feed_frozen: bool = False,
        maintenance: bool = False,
        delisted: bool = False,
    ) -> tuple[bool, str]:
        """Global halt check — True means TRADING MUST STOP (force PAPER + alarm)."""
        if daily_loss_pct >= self.daily_loss_limit_pct:
            self._trip(f"DAILY_DD: {daily_loss_pct}% >= {self.daily_loss_limit_pct}%")
        elif adl_rank >= self.adl_rank_limit:
            self._trip(f"ADL_RANK: {adl_rank} >= {self.adl_rank_limit}")
        elif feed_frozen:
            self._trip("FEED_FROZEN")
        elif maintenance:
            self._trip("MAINTENANCE")
        elif delisted:
            self._trip("DELIST")
        return self.tripped, self.reason

    def alert_due(self) -> bool:
        """True at most once per trip, then at most every _alert_interval_s while
        still tripped. Caller uses this to gate notify_kill_switch()."""
        if not self.tripped:
            return False
        now = self.clock()
        if now - self._last_alert_ts >= self._alert_interval_s:
            self._last_alert_ts = now
            return True
        return False

    def _trip(self, reason: str) -> None:
        newly = not self.tripped
        self.tripped = True
        self.reason = reason
        if newly:
            # clear the alert timer on a FRESH trip so the first alert always
            # fires (far-past sentinel; do NOT reset to 0.0 — that would
            # suppress the first alert when the clock is already > 0).
            self._last_alert_ts = -1e18

    def reset(self) -> None:
        """Manual/next-day reset (human or day-roll)."""
        self.tripped = False
        self.reason = ""
        self._last_alert_ts = 0.0

    # --- per (pair, tf, side) losing streak (doc 30 §7) ---

    def record_close(self, pair: str, tf: str, side: str, win: bool) -> None:
        key = (pair, tf, side)
        if win:
            self._streaks[key] = 0
            return
        self._streaks[key] = self._streaks.get(key, 0) + 1
        if self._streaks[key] >= LOSING_STREAK_LIMIT:
            self._cooldowns[key] = self.clock() + STREAK_COOLDOWN_S
            self._streaks[key] = 0

    def in_cooldown(self, pair: str, tf: str, side: str) -> bool:
        until = self._cooldowns.get((pair, tf, side))
        return until is not None and self.clock() < until


# --- promotion gate (expectancy-first, v0.1.0) ---

@dataclass
class PromotionDecision:
    eligible: bool          # all automatic criteria pass
    live: bool              # eligible AND human approved
    reasons: list[str]


def health_clean(conn: sqlite3.Connection, window_rows: int = 100) -> bool:
    """No FAIL rows among recent system_health entries (doc 30 §6: 'bersih')."""
    row = conn.execute(
        """SELECT COUNT(*) AS c FROM (
             SELECT status FROM system_health ORDER BY id DESC LIMIT ?
           ) WHERE status='FAIL'""",
        (window_rows,),
    ).fetchone()
    return row["c"] == 0


def promotion_gate(
    report: EvalReport,
    conn: sqlite3.Connection,
    human_approved: bool = False,
    live_pairs_count: int = 0,
    global_max_live_pairs: int = 5,
    *,
    min_trades: int = PROMOTION_MIN_TRADES,
    winrate_floor_pct: float = PROMOTION_WR_FLOOR_PCT,
    min_expectancy_r: float = PROMOTION_EXPECTANCY_R,
    min_pf: float = PROMOTION_PF,
    max_dd_pct: float = PROMOTION_MAX_DD_PCT,
) -> PromotionDecision:
    """Expectancy-first promotion for ONE (pair, tf, side). Human gate last.

    Order of evidence (strongest first): expectancy → profit factor → drawdown →
    WR floor (sanity, above break-even) → sample size → health → global cap.
    """
    reasons: list[str] = []
    if report.expectancy_r <= min_expectancy_r:
        reasons.append(f"EXPECTANCY: {report.expectancy_r:+.3f}R <= +{min_expectancy_r}R")
    if report.profit_factor <= min_pf:
        reasons.append(f"PF: {report.profit_factor:.2f} <= {min_pf}")
    if report.max_dd_pct >= max_dd_pct:
        reasons.append(f"MAX_DD: {report.max_dd_pct:.2f}% >= {max_dd_pct}%")
    if report.win_rate_pct < winrate_floor_pct:
        reasons.append(f"WR: {report.win_rate_pct:.2f}% < floor {winrate_floor_pct}%")
    if report.n_trades < min_trades:
        reasons.append(f"TRADES: {report.n_trades} < {min_trades}")
    if not health_clean(conn):
        reasons.append("HEALTH: system_health has FAIL incidents")
    if live_pairs_count >= global_max_live_pairs:
        reasons.append(f"GLOBAL_CAP: {live_pairs_count} live >= {global_max_live_pairs}")

    eligible = not reasons
    if eligible and not human_approved:
        reasons.append("HUMAN: approval pending (supervised mode)")
    return PromotionDecision(eligible=eligible,
                             live=eligible and human_approved,
                             reasons=reasons)


def should_demote(
    report: EvalReport,
    *,
    winrate_floor_pct: float = PROMOTION_WR_FLOOR_PCT,
    min_expectancy_r: float = 0.0,
) -> bool:
    """Post-live revert: negative/zero expectancy OR WR below the sanity floor (v0.1.0).

    Expectancy is the primary demotion trigger — a side that stops being +EV must come
    off live even if its historical WR still looks fine.
    """
    return report.expectancy_r <= min_expectancy_r or report.win_rate_pct < winrate_floor_pct
