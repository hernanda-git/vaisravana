"""Project Vaiśravaṇa — safety: kill-switches + promotion gate (doc 30 §6-§7, doc 25).

Kill-switch triggers (doc 30 §7):
  - daily drawdown ≥ 0.5%  → force PAPER + alarm
  - ADL rank ≥ 4           → halt entries (auto-deleverage danger)
  - frozen feed            → halt (data can't be trusted)
  - maintenance / delist   → auto-pause pair
  - losing streak = 5      → 30-minute cooldown (that pair×tf×side)

Promotion gate (doc 30 §6) — per (pair, tf, SIDE), all required:
  ≥200 PAPER trades (that side) · WR ≥85% (that side) · expectancy > +0.2R ·
  Max DD < 3% · PF > 1.3 · clean system_health · HUMAN approval.
LONG and SHORT are promoted independently. Post-live: WR < 85% in the validation
window → revert to shadow / disable.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field

from evaluation import EvalReport

LOSING_STREAK_LIMIT = 5            # doc 30 §7
STREAK_COOLDOWN_S = 30 * 60        # doc 30 §7: 30 menit
PROMOTION_MIN_TRADES = 200         # doc 30 §6
PROMOTION_WR_PCT = 85.0
PROMOTION_EXPECTANCY_R = 0.2
PROMOTION_MAX_DD_PCT = 3.0
PROMOTION_PF = 1.3                 # NOTE: §6 uses 1.3 (stricter than §5's 1.20)


# --- kill switch ---

@dataclass
class KillSwitch:
    daily_loss_limit_pct: float = 0.5
    adl_rank_limit: int = 4
    clock: callable = time.time
    tripped: bool = False
    reason: str = ""
    _cooldowns: dict[tuple, float] = field(default_factory=dict)
    _streaks: dict[tuple, int] = field(default_factory=dict)

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

    def _trip(self, reason: str) -> None:
        self.tripped = True
        self.reason = reason

    def reset(self) -> None:
        """Manual/next-day reset (human or day-roll)."""
        self.tripped = False
        self.reason = ""

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


# --- promotion gate (doc 30 §6) ---

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
) -> PromotionDecision:
    """Evaluate ALL doc 30 §6 criteria for ONE (pair, tf, side). Human gate last."""
    reasons: list[str] = []
    if report.n_trades < PROMOTION_MIN_TRADES:
        reasons.append(f"TRADES: {report.n_trades} < {PROMOTION_MIN_TRADES}")
    if report.win_rate_pct < PROMOTION_WR_PCT:
        reasons.append(f"WR: {report.win_rate_pct:.2f}% < {PROMOTION_WR_PCT}%")
    if report.expectancy_r <= PROMOTION_EXPECTANCY_R:
        reasons.append(f"EXPECTANCY: {report.expectancy_r:+.3f}R <= +{PROMOTION_EXPECTANCY_R}R")
    if report.max_dd_pct >= PROMOTION_MAX_DD_PCT:
        reasons.append(f"MAX_DD: {report.max_dd_pct:.2f}% >= {PROMOTION_MAX_DD_PCT}%")
    if report.profit_factor <= PROMOTION_PF:
        reasons.append(f"PF: {report.profit_factor:.2f} <= {PROMOTION_PF}")
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


def should_demote(report: EvalReport) -> bool:
    """Post-live: WR < 85% in validation window → revert/disable (doc 30 §6)."""
    return report.win_rate_pct < PROMOTION_WR_PCT
