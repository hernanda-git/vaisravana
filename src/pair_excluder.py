"""v0.0.23 T2 — data-driven pair exclusion (doc 45 §3).

Owner mandate: "I don't want to lose money." The live DB shows 6 pairs
(PEPE/WLD/INJ/TAO/WIF/PUMP) run ~28% WR over 47 trades — pure drag.
Excluding them lifts aggregate WR 46% -> 58% with ZERO logic change.

This module is the mechanical enforcer:
  - After each close, recompute a pair's rolling WR over its last >= N trades.
  - If WR < EXCLUDE_BELOW (default 40%), the pair is EXCLUDED (no new entries).
  - If an excluded pair recovers WR >= INCLUDE_ABOVE (default 50%) over its next
    >= N trades, it is RE-INCLUDED.
  - State is persisted to JSON so it survives Fly restarts.

Pure + fully testable: no DB, no Telegram, no clock.
"""

from __future__ import annotations

import json
from pathlib import Path

# Tuning (doc 45 §3). Conservative on purpose:
#   - N=10: need a real sample before judging a pair.
#   - exclude < 40%: well below the 33.3% break-even-at-2:1, so we only
#     drop pairs that are clearly unprofitable under THIS engine.
#   - include >= 50%: must clear break-even with margin to come back.
EXCLUDE_BELOW_PCT = 40.0
INCLUDE_ABOVE_PCT = 50.0
MIN_TRADES = 10


class PairExcluder:
    """Holds the excluded-pair set + per-pair rolling sample, persisted to disk."""

    def __init__(self, path: str | Path = "/data/exclusions.json",
                 exclude_below: float = EXCLUDE_BELOW_PCT,
                 include_above: float = INCLUDE_ABOVE_PCT,
                 min_trades: int = MIN_TRADES) -> None:
        self.path = Path(path)
        self.exclude_below = exclude_below
        self.include_above = include_above
        self.min_trades = min_trades
        # pair -> {"wins": int, "losses": int, "excluded": bool}
        self._state: dict[str, dict] = {}
        self._load()

    # --- persistence ---
    def _load(self) -> None:
        try:
            self._state = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except FileNotFoundError:
            self._state = {}
        except json.JSONDecodeError:
            self._state = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    # --- queries ---
    def is_excluded(self, pair: str) -> bool:
        return bool(self._state.get(pair, {}).get("excluded", False))

    @property
    def excluded_pairs(self) -> list[str]:
        return sorted(p for p, s in self._state.items() if s.get("excluded"))

    # --- core: feed one close, return (changed, action, note) ---
    def record_close(self, pair: str, win: bool) -> tuple[bool, str, str]:
        """Record a close for `pair`; decide exclude/re-include.

        Returns (changed, action, note) where action in
        {"", "EXCLUDE", "INCLUDE"}.
        """
        st = self._state.setdefault(pair, {"wins": 0, "losses": 0, "excluded": False})
        if win:
            st["wins"] += 1
        else:
            st["losses"] += 1
        was_excluded = st["excluded"]
        n = st["wins"] + st["losses"]
        wr = (st["wins"] / n * 100.0) if n else 0.0

        if not was_excluded:
            if n >= self.min_trades and wr < self.exclude_below:
                st["excluded"] = True
                self._save()
                return True, "EXCLUDE", f"WR {wr:.1f}% < {self.exclude_below:.0f}% over {n} trades"
        else:
            # excluded: re-include once it clears the recovery bar
            if n >= self.min_trades and wr >= self.include_above:
                st["excluded"] = False
                self._save()
                return True, "INCLUDE", f"WR {wr:.1f}% >= {self.include_above:.0f}% over {n} trades"

        # no change; but persist counter growth only when state changed
        if (win and st["wins"] == 1 and st["losses"] == 0) or \
           ((not win) and st["losses"] == 1 and st["wins"] == 0):
            self._save()
        return False, "", ""

    def reset(self) -> None:
        self._state = {}
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
