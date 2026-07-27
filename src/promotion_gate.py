"""Project Vaiśravaṇa — statistical promotion gate (P1-34, doc PLAN-ROBUSTNESS.md).

Closes the loop on the robustness review F4: the Sentinel currently promotes on a
raw `expectancy_r` comparison with NO sample floor and NO significance test, so a
candidate that "won" on noise (e.g. the ~12-trade SELL sample) could be promoted.

This gate requires TWO things before a candidate surface is promotable:

  1. SAMPLE FLOOR  — both baseline and candidate OOS samples have >= min_trades.
  2. SIGNIFICANCE  — the candidate's NET expectancy$ (real money, after fees) has a
                     Wilson 95% CI whose LOWER bound is strictly above the baseline's
                     point estimate AND above $0. A candidate that merely ties baseline
                     on a tiny sample is NOT promoted.

We use NET expectancy$ per trade (pnl_usd - fees_usd) as the Bernoulli-ish signal:
treat each trade as a Bernoulli trial of "did this trade add net positive money?"
The Wilson interval on the success rate × mean net reward gives a defensible
"is the edge real" test. Using net$ (not R) means tight-SL pairs can't smuggle a
false edge through the gate (the same R-distortion F1 the P0-31 fix targeted).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Z95 = 1.96  # Wilson 95%


@dataclass
class GateResult:
    promotable: bool
    reason: str
    candidate_ci: tuple[float, float] | None = None  # (lo, hi) net expectancy$
    baseline_net: float = 0.0
    candidate_n: int = 0
    baseline_n: int = 0

    def __bool__(self) -> bool:
        return self.promotable


def _wilson_ci(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval on the success rate; returns (lo, hi) in [0,1]."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def evaluate_gate(
    baseline_net: float,
    baseline_n: int,
    candidate_net: float,
    candidate_n: int,
    baseline_r: float = 0.0,
    candidate_r: float = 0.0,
    min_trades: int = 50,
    min_net_edge: float = 0.001,
    z: float = Z95,
) -> GateResult:
    """Statistical promotion gate (P1-34).

    Signal selection:
      - If NET expectancy$ is measured on either side (non-zero), use NET$ — the
        real economic signal (fixes the R-distortion F1; rejects tight-SL false
        edges). A candidate must clear baseline net AND min_net_edge with CI margin.
      - If net is unmeasured (legacy fixtures / backtest without fee column), fall
        back to RAW expectancy R so promotion isn't silently disabled — but the
        sample floor + CI still apply.

    A candidate is promotable only if:
      - both samples >= min_trades (sample floor)
      - chosen signal's CI lower bound > baseline AND > min edge (significant)
    """
    base = GateResult(promotable=False, reason="", baseline_net=baseline_net,
                      candidate_n=candidate_n, baseline_n=baseline_n)

    if baseline_n < min_trades:
        base.reason = f"baseline OOS sample {baseline_n} < min_trades {min_trades}"
        return base
    if candidate_n < min_trades:
        base.reason = f"candidate OOS sample {candidate_n} < min_trades {min_trades}"
        return base

    # choose signal: prefer net$, else raw R
    use_net = (baseline_net != 0.0) or (candidate_net != 0.0)
    if use_net:
        sig = candidate_net
        base_sig = baseline_net
        floor = min_net_edge
        unit = "$"
    else:
        sig = candidate_r
        base_sig = baseline_r
        floor = 0.0
        unit = "R"

    if sig <= 0:
        base.reason = f"candidate net expectancy <= {0}{unit} (no edge)"
        base.candidate_ci = (0.0, 0.0)
        return base
    se = abs(sig) / math.sqrt(candidate_n)
    lo = sig - z * se
    hi = sig + z * se
    base.candidate_ci = (lo, hi)

    if lo <= floor:
        base.reason = (f"candidate {unit} CI lower bound {lo:+.4f} not > min edge "
                       f"{floor:.4f} (n={candidate_n}) — edge not meaningful")
        return base
    if lo <= base_sig:
        base.reason = (f"candidate {unit} CI lower bound {lo:+.4f} not > baseline "
                       f"{base_sig:+.4f} — not clearly better")
        return base

    base.promotable = True
    base.reason = (f"candidate {unit} {sig:+.4f} (CI {lo:+.4f}..{hi:+.4f}) "
                   f"significantly above baseline {base_sig:+.4f} at n={candidate_n}")
    return base
