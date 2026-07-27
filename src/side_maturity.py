"""v0.0.24 P0-32 — side maturity gate (doc: robustness plan P0-32).

Fixes F3: SELL only went live 2026-07-27 ~04:42 UTC and had ~12 trades (<3h).
Concluding "SELL broken" or "SELL works" on that noise is unsafe, and the
SideBalancer / PairExcluder could over-react.

A SIDE is "mature" only when:
  - it has >= min_trades closed samples, AND
  - its Wilson 95% lower-bound CI on win rate is wide enough to matter
    (we require CI half-width < ci_max_width, i.e. it has been sampled enough
    that the win rate estimate is stable).

Immature sides may still trade (entries happen), but MUST be excluded from:
  - pair-exclusion / promotion math (don't de-bleed on noise)
  - "SELL works / SELL broken" conclusions (dashboard label)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class SideSample:
    wins: int = 0
    losses: int = 0

    @property
    def n(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n else 0.0

    def wilson_ci(self, z: float = 1.96) -> tuple[float, float]:
        """95% Wilson score interval (low, high) on win rate in [0,1]."""
        n = self.n
        if n == 0:
            return (0.0, 1.0)
        p = self.win_rate
        denom = 1.0 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
        return (max(0.0, center - half), min(1.0, center + half))


@dataclass
class SideMaturity:
    min_trades: int = 50
    ci_max_width: float = 0.20  # half-width bound; <0.20 => estimate stable
    samples: dict[str, SideSample] = field(default_factory=dict)

    def record(self, side: str, win: bool) -> None:
        s = self.samples.setdefault(side, SideSample())
        if win:
            s.wins += 1
        else:
            s.losses += 1

    def is_mature(self, side: str) -> bool:
        s = self.samples.get(side)
        if s is None or s.n < self.min_trades:
            return False
        lo, hi = s.wilson_ci()
        # ci_max_width guards on the CI HALF-width (hi-lo)/2, not full width.
        return (hi - lo) / 2.0 <= self.ci_max_width

    def maturity_label(self, side: str) -> str:
        s = self.samples.get(side)
        if s is None or s.n == 0:
            return "UNSAMPLED"
        if s.n < self.min_trades:
            return f"IMMATURE(n={s.n})"
        lo, hi = s.wilson_ci()
        half = (hi - lo) / 2.0
        if half > self.ci_max_width:
            return f"IMMATURE(ci={half:.2f})"
        return "MATURE"
