"""Project Vaiśravaṇa — parameter surface (doc 21) + bounds.

Single source of truth for *what the Sentinel may change*. Mirrors
`docs/21-active-bot.md` exactly. Engine logic, execution code, and telemetry
schema are OUT OF SCOPE here (see doc 21 "Apa yang TIDAK BOLEH diubah").

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


class ParameterSurface(BaseModel):
    """The full mutable parameter surface (doc 21).

    Defaults mirror the *concrete spec* (doc 30 / doc 21): entry 0.90,
    tp 1.05, sl 1.0, lev 2, daily_loss 0.5%, risk 0.25%, WR gate 85%,
    min_trades 200, global_max_live 5.
    """

    weights: Weights = Field(default_factory=Weights)

    entry_threshold: float = Field(default=0.86, ge=0.85, le=0.92)
    watch_threshold: float = Field(default=0.78, ge=0.78, le=0.85)

    sl_atr_mult: float = Field(default=1.0, ge=0.8, le=2.0)
    tp_atr_mult: float = Field(default=1.25, ge=1.0, le=2.0)

    max_leverage: int = Field(default=3, ge=1, le=3)
    cooldown_after_loss: int = Field(default=5, ge=0, le=60)

    daily_loss_limit_pct: float = Field(default=0.5, ge=0.3, le=2.0)
    risk_per_trade_pct: float = Field(default=0.25, ge=0.10, le=0.50)
    max_position_notional_pct: float = Field(default=50.0, ge=10.0, le=60.0)

    winrate_gate_pct: float = Field(default=85.0, ge=80.0, le=95.0)
    min_trades_for_promote: int = Field(default=200, ge=100, le=500)
    global_max_live_pairs: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def _watch_below_entry(self) -> "ParameterSurface":
        if self.watch_threshold >= self.entry_threshold:
            raise ValueError(
                f"watch_threshold ({self.watch_threshold}) must be < "
                f"entry_threshold ({self.entry_threshold})"
            )
        return self

    def as_dict(self) -> dict:
        return self.model_dump()


def default_surface() -> ParameterSurface:
    """Return a fresh default ParameterSurface (doc 21 / doc 30 defaults)."""
    return ParameterSurface()
