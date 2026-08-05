"""Project Vaiśravaṇa — parameter surface (doc 21) + bounds + strategy profiles.

Single source of truth for *what the Sentinel may change*. Mirrors
`docs/21-active-bot.md`. Engine logic, execution code, and telemetry schema are OUT OF
SCOPE here (see doc 21 "Apa yang TIDAK BOLEH diubah").

v0.1.0 (Active Multi-Strategy overhaul):
  - entry_threshold floor lowered 0.85 -> 0.55: the old 0.86-0.90 "A+ only" bar produced
    ~0 trades. Break-even WR after taker fees at R:R 1.5 is only ~48%, so a 56% WR floor is
    genuinely +EV. The bot is now expectancy-first, not vanity-WR-first.
  - StrategyProfile: Scalping / Day / Swing run concurrently, each with its own TF, SL/TP
    ATR multipliers, entry threshold, max-hold and cooldown.
  - winrate_floor_pct (default 56) + min_expectancy_r replace the 85% gate's role.

The only hard invariant: Σ weights == 1.0 (doc 21 §"Syarat konsistensi").
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


# Bounds copied verbatim from docs/21-active-bot.md.
_WEIGHT_BOUNDS: dict[str, tuple[float, float]] = {
    "trend": (0.20, 0.40),
    "momentum": (0.10, 0.30),
    "volume": (0.05, 0.25),
    "structure": (0.05, 0.25),
    "liquidity": (0.00, 0.20),
    "atr": (0.00, 0.15),
    "funding_oi": (0.00, 0.15),
}


class Weights(BaseModel):
    """9-engine factor weights. Sum must be 1.0 (doc 21)."""

    trend: float = Field(default=0.30, ge=0.20, le=0.40)
    momentum: float = Field(default=0.20, ge=0.10, le=0.30)
    volume: float = Field(default=0.15, ge=0.05, le=0.25)
    structure: float = Field(default=0.15, ge=0.05, le=0.25)
    liquidity: float = Field(default=0.10, ge=0.00, le=0.20)
    atr: float = Field(default=0.05, ge=0.00, le=0.15)
    funding_oi: float = Field(default=0.05, ge=0.00, le=0.15)

    @model_validator(mode="after")
    def _check_sum(self) -> "Weights":
        total = sum(self.model_dump().values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"Σ weights must be 1.0, got {total:.6f}")
        return self

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class StrategyProfile(BaseModel):
    """One tradable timescale. Scalping / Day / Swing run concurrently (v0.1.0).

    Each profile sets its own entry bar and SL/TP ATR multipliers so a scalp (tight, R:R 1.5)
    and a swing (wide, R:R 2.0) can be active on the same pair without one starving the other.
    `context_tfs` are the higher timeframes used for htf_bias / MTF confluence.
    """

    name: str
    decision_tf: str                       # the bar we decide + act on
    context_tfs: list[str] = Field(default_factory=list)
    entry_threshold: float = Field(ge=0.40, le=0.92)
    watch_threshold: float = Field(ge=0.35, le=0.85)
    sl_atr_mult: float = Field(ge=0.8, le=3.0)
    tp_atr_mult: float = Field(ge=1.0, le=6.0)
    max_hold_min: int = Field(ge=1, le=10080)
    cooldown_min: int = Field(default=5, ge=0, le=240)
    winrate_floor_pct: float = Field(default=45.0, ge=40.0, le=85.0)

    @property
    def rr(self) -> float:
        """Reward:risk ratio (tp/sl)."""
        return self.tp_atr_mult / self.sl_atr_mult if self.sl_atr_mult else 0.0

    @model_validator(mode="after")
    def _watch_below_entry(self) -> "StrategyProfile":
        if self.watch_threshold >= self.entry_threshold:
            raise ValueError(
                f"[{self.name}] watch_threshold ({self.watch_threshold}) must be < "
                f"entry_threshold ({self.entry_threshold})"
            )
        return self


def default_profiles() -> dict[str, StrategyProfile]:
    """The three concurrent strategies (v0.1.0).

    Thresholds/mults chosen from the break-even-WR analysis (docs/44-active-strategy.md):
      Scalp  R:R 1.5 -> BE WR 48% -> 56% floor = +0.20R
      Day    R:R 1.67 -> BE WR 41% -> 54% floor = +0.30R
      Swing  R:R 2.0 -> BE WR 35% -> 52% floor = +0.40R
    """
    return {
        "scalping": StrategyProfile(
            name="scalping", decision_tf="1m", context_tfs=["5m", "15m"],
            entry_threshold=0.55, watch_threshold=0.45,
            sl_atr_mult=1.5, tp_atr_mult=3.0, max_hold_min=5, cooldown_min=1,
            winrate_floor_pct=45.0,
        ),
        "day": StrategyProfile(
            name="day", decision_tf="15m", context_tfs=["1h", "4h"],
            entry_threshold=0.55, watch_threshold=0.45,
            sl_atr_mult=1.5, tp_atr_mult=3.5, max_hold_min=60, cooldown_min=15,
            winrate_floor_pct=45.0,
        ),
        "swing": StrategyProfile(
            name="swing", decision_tf="1h", context_tfs=["4h", "1d"],
            entry_threshold=0.55, watch_threshold=0.45,
            sl_atr_mult=2.0, tp_atr_mult=4.5, max_hold_min=120, cooldown_min=60,
            winrate_floor_pct=45.0,
        ),
    }


class ParameterSurface(BaseModel):
    """The full mutable parameter surface (doc 21).

    v0.1.0: entry/watch floors lowered so the bot is active; the 85% WR gate is demoted to an
    advisory field (`winrate_gate_pct`) and replaced operationally by `winrate_floor_pct` +
    `min_expectancy_r` (expectancy-first promotion; see safety.promotion_gate).
    """

    weights: Weights = Field(default_factory=Weights)

    entry_threshold: float = Field(default=0.45, ge=0.40, le=0.92)
    watch_threshold: float = Field(default=0.40, ge=0.35, le=0.85)

    sl_atr_mult: float = Field(default=1.0, ge=0.8, le=3.0)
    tp_atr_mult: float = Field(default=2.0, ge=1.0, le=6.0)  # v0.0.23 T1: R:R 2:1 (was 1.5)

    max_leverage: int = Field(default=5, ge=1, le=5)
    cooldown_after_loss: int = Field(default=2, ge=0, le=60)

    daily_loss_limit_pct: float = Field(default=2.0, ge=0.3, le=2.0)
    risk_per_trade_pct: float = Field(default=0.25, ge=0.10, le=0.50)
    max_position_notional_pct: float = Field(default=50.0, ge=10.0, le=60.0)

    # Expectancy-first promotion (v0.1.0). winrate_gate_pct kept for backward-compat/advisory.
    winrate_floor_pct: float = Field(default=45.0, ge=40.0, le=85.0)
    min_expectancy_r: float = Field(default=0.02, ge=0.0, le=1.0)
    winrate_gate_pct: float = Field(default=85.0, ge=50.0, le=95.0)
    min_trades_for_promote: int = Field(default=100, ge=30, le=500)
    global_max_live_pairs: int = Field(default=10, ge=1, le=20)

    @property
    def rr(self) -> float:
        """Reward:risk ratio (tp/sl) for the active PAPER surface.

        v0.0.23: used by the R:R >= 2:1 owner-floor validator.
        """
        return self.tp_atr_mult / self.sl_atr_mult if self.sl_atr_mult else 0.0

    @model_validator(mode="after")
    def _watch_below_entry(self) -> "ParameterSurface":
        if self.watch_threshold >= self.entry_threshold:
            raise ValueError(
                f"watch_threshold ({self.watch_threshold}) must be < "
                f"entry_threshold ({self.entry_threshold})"
            )
        return self

    @model_validator(mode="after")
    def _rr_floor(self) -> "ParameterSurface":
        """v0.0.23 T1: HARD owner floor R:R >= 2:1.

        Owner mandate: "1 win recovers 2 losses is OK, but I don't want
        to lose money." Translated: tp_atr_mult / sl_atr_mult >= 2.0,
        i.e. break-even WR = 1/(1+2) = 33.3%. Below this the bot
        can lose money structurally, so any surface below 2:1 is rejected
        at construction time — the floor is enforced in code, not by hope.
        """
        rr = self.rr
        if rr < 2.0 - 1e-9:
            raise ValueError(
                f"R:R {rr:.3f} is below the owner floor of 2:1 "
                f"(tp_atr_mult={self.tp_atr_mult} / sl_atr_mult="
                f"{self.sl_atr_mult}). 1 win must recover >=2 losses."
            )
        return self

    def as_dict(self) -> dict:
        return self.model_dump()


def default_surface() -> ParameterSurface:
    """Return a fresh default ParameterSurface (doc 21 / v0.1.0 active defaults)."""
    return ParameterSurface()
