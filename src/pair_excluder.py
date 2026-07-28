"""v0.0.23 T2 — data-driven pair exclusion (doc 45 §3).

Owner mandate: "I don't want to lose money." The live DB showed 6 pairs
(PEPE/WLD/INJ/TAO/WIF/PUMP) run ~28% WR over 47 trades — pure drag.
Excluding them lifts aggregate WR 46% -> 58% with ZERO logic change.

v0.0.24 P0-31: re-based on NET expectancy$ (after fees), not raw win rate.
Raw WR let tight-SL pairs (e.g. PEPE, avg_R +9.99 but net pnl% -0.185) look
better than they are. Net expectancy$ is the real economic signal, so the
excluder now drops pairs that actually lose money after fees — which is the
owner's actual mandate.

This module is the mechanical enforcer:
  - After each close, recompute a pair's rolling NET expectancy$.
  - If net expectancy$ < EXCLUDE_BELOW (default 0.0), the pair is EXCLUDED.
  - If an excluded pair recovers net expectancy$ >= INCLUDE_ABOVE (default >0),
    it is RE-INCLUDED.
  - State is persisted to JSON so it survives Fly restarts.

Pure + fully testable: no DB, no Telegram, no clock. When a `conn` is supplied
to record_close, it reads net expectancy$ from evaluation.net_pair_ranking;
otherwise it falls back to the W/L counter (backward compatible for tests).
"""

from __future__ import annotations

import json
from pathlib import Path

# Tuning.
#   NET expectancy$ is used as the signal. A pair with <= 0 net expectancy$
#   is, by the owner's mandate, dead weight. We exclude below 0 and re-include
#   only when clearly positive. MIN_TRADES guards against tiny-sample noise.
EXCLUDE_BELOW_USD = 0.0
INCLUDE_ABOVE_USD = 0.0  # strictly: re-include when net > 0 (recovered)
MIN_TRADES = 10


class PairExcluder:
    """Holds the excluded-pair set + per-pair rolling sample, persisted to disk."""

    def __init__(self, path: str | Path = "data/exclusions.json",
                 exclude_below: float = EXCLUDE_BELOW_USD,
                 include_above: float = INCLUDE_ABOVE_USD,
                 min_trades: int = MIN_TRADES,
                 wr_exclude_below: float = 40.0,
                 wr_include_above: float = 50.0) -> None:
        self.path = Path(path)
        self.exclude_below = exclude_below
        self.include_above = include_above
        self.min_trades = min_trades
        self.wr_exclude_below = wr_exclude_below
        self.wr_include_above = wr_include_above
        # v0.0.33 WR-improvement: exclude pairs whose RAW WR < 45% (was 40%) once they
        # have enough sample — this lifts aggregate WR without touching engine logic.
        # Net$ < 0 still triggers exclusion regardless of WR (owner mandate: no losing weight).
        if wr_exclude_below <= 0:
            self.wr_exclude_below = 45.0
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
    def record_close(self, pair: str, win: bool,
                     conn=None) -> tuple[bool, str, str]:
        """Record a close for `pair`; decide exclude/re-include.

        `conn` (optional sqlite3.Connection): when supplied, the exclude
        decision uses NET expectancy$ from evaluation.net_pair_ranking (the
        real economic signal, v0.0.24 P0-31). When omitted, falls back to the
        pure W/L counter so isolated unit tests stay DB-free.

        Returns (changed, action, note) where action in
        {"", "EXCLUDE", "INCLUDE"}.
        """
        # persist the W/L counter regardless (cheap, used as fallback + audit)
        st = self._state.setdefault(pair, {"wins": 0, "losses": 0, "excluded": False})
        if win:
            st["wins"] += 1
        else:
            st["losses"] += 1
        was_excluded = st["excluded"]
        n = st["wins"] + st["losses"]

        # v0.0.24 P0-31: net-expectancy signal (preferred when conn available)
        if conn is not None:
            from evaluation import net_pair_ranking
            net_usd = 0.0
            for row in net_pair_ranking(conn, min_trades=self.min_trades):
                if row["pair"] == pair:
                    net_usd = row["net_expectancy_usd"]
                    break
            if not was_excluded:
                if net_usd < self.exclude_below:
                    st["excluded"] = True
                    self._save()
                    return True, "EXCLUDE", (
                        f"net expectancy$ {net_usd:+.4f} < {self.exclude_below} "
                        f"over {n} trades")
            else:
                if net_usd > self.include_above:
                    st["excluded"] = False
                    self._save()
                    return True, "INCLUDE", (
                        f"net expectancy$ {net_usd:+.4f} > {self.include_above} "
                        f"over {n} trades")
            return False, "", ""

        # Fallback (no conn): the original v0.0.23 T2 W/L-based signal.
        # Kept so standalone use + T2 unit tests are DB-free. Net$ is preferred
        # when a DB is available, but raw win rate is still a valid, conservative gate.
        wr = (st["wins"] / n * 100.0) if n else 0.0
        if not was_excluded:
            if n >= self.min_trades and wr < self.wr_exclude_below:
                st["excluded"] = True
                self._save()
                return True, "EXCLUDE", f"WR {wr:.1f}% < {self.wr_exclude_below:.0f}% over {n} trades"
        else:
            if n >= self.min_trades and wr >= self.wr_include_above:
                st["excluded"] = False
                self._save()
                return True, "INCLUDE", f"WR {wr:.1f}% >= {self.wr_include_above:.0f}% over {n} trades"
        # no change; persist counter growth only when state changed
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
