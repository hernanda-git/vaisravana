"""v0.0.23 T3 — un-suppress SELL (doc 45 §2).

Live finding: 110 BUY vs 11 SELL (10:1). The engine's "pick higher of
BUY/SELL score" structurally favors BUY in the 1m/MTF regime, so the
bot only trades half the market (and skips the profitable short side in
downtrends).

Design (bounded + testable, no model magic):
  - A `SideBalancer` tracks the trailing entry share of BUY vs SELL.
  - When SELL share < MIN_SELL_SHARE (25%), it nudges the SELL entry
    threshold DOWN by up to SELL_NUDGE (0.03) — never below the
    profile's watch_threshold (so we never take a sub-A+ SELL).
  - When SELL share is healthy, the threshold is untouched (symmetry with
    the existing BUY non-bull penalty at bot_paper.py:1191).
  - The bot still requires the SELL score to clear the (nudged) bar AND
    pass the directional gate, so quality is preserved — we only remove the
    *structural* suppression, not the bar itself.

Pure + fully testable: in-memory ring of recent entries, no DB/Telegram.
"""

from __future__ import annotations

from collections import deque

MIN_SELL_SHARE = 0.25       # floor: SELL should be >= 25% of entries
SELL_NUDGE = 0.03           # max threshold reduction for SELL when suppressed
WINDOW = 40                   # trailing window to judge the share


class SideBalancer:
    """Tracks trailing BUY/SELL entry share; returns a SELL threshold nudge."""

    def __init__(self, min_sell_share: float = MIN_SELL_SHARE,
                 sell_nudge: float = SELL_NUDGE, window: int = WINDOW) -> None:
        self.min_sell_share = min_sell_share
        self.sell_nudge = sell_nudge
        self.window = window
        self._recent: deque[str] = deque(maxlen=window)

    def record(self, side: str) -> None:
        if side in ("BUY", "SELL"):
            self._recent.append(side)

    @property
    def sell_share(self) -> float:
        n = len(self._recent)
        if n == 0:
            return 0.0
        s = sum(1 for s in self._recent if s == "SELL")
        return s / n

    @property
    def suppressed(self) -> bool:
        """True when SELL share is below the floor (and we have enough data)."""
        if len(self._recent) < self.window:
            return False
        return self.sell_share < self.min_sell_share

    def sell_threshold(self, base_entry: float, watch_threshold: float) -> float:
        """Return the (possibly nudged-down) SELL entry threshold.

        Never goes below `watch_threshold` — we refuse sub-A+ SELLs.
        """
        if not self.suppressed:
            return base_entry
        # nudge down, but clamp at the watch band (no junk entries)
        return max(watch_threshold, base_entry - self.sell_nudge)

    def reset(self) -> None:
        self._recent.clear()
