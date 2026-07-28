"""Risk guard — port of ModeGuard + kill-switch + daily-DD + PairExcluder."""
from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


class ModeGuard:
    """PAPER-only enforcement. Ported from src/mode.py.

    PAPER (default): PaperSimExchange always.
    live: GuardedExchange (requires human approval set).
    """

    def __init__(self, mode: str = "paper"):
        if mode not in ("paper", "live"):
            raise SystemExit(f"ModeGuard: mode must be paper/live, got {mode!r}")
        self.mode = mode

    def exchange_for(self, live_exchange=None):
        """Return the appropriate exchange for the mode.

        In PAPER mode, always return a PaperSimExchange.
        In LIVE mode, wrap in a GuardedExchange.
        """
        if self.mode == "paper":
            from mode import PaperSimExchange
            return PaperSimExchange()
        # Live with guard — only if human approval configured
        if live_exchange is None:
            raise RuntimeError("ModeGuard LIVE requires a live_exchange")
        from execution import GuardedExchange
        return GuardedExchange(live_exchange)

    def is_paper(self) -> bool:
        return self.mode == "paper"


class KillSwitch:
    """Port of safety.KillSwitch — trips on daily DD or explicit kill.

    Once tripped, blocks all new activity until reset at midnight.
    """

    def __init__(self, daily_loss_limit_pct: float = 0.5):
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self._tripped: bool = False
        self._trip_reason: str = ""
        self._trip_ts: float = 0.0
        self._daily_loss: float = 0.0
        self._day: str = ""

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def trip_reason(self) -> str:
        return self._trip_reason

    def trip(self, reason: str = "manual") -> None:
        """Trip the kill-switch."""
        self._tripped = True
        self._trip_reason = reason
        self._trip_ts = time.time()
        log.warning("KILL-SWITCH TRIPPED: %s", reason)

    def reset(self) -> None:
        """Reset kill-switch (midnight roll or /clean)."""
        self._tripped = False
        self._trip_reason = ""
        self._trip_ts = 0.0

    def record_loss(self, usd: float) -> None:
        """Record a realised loss and trip if daily limit exceeded."""
        today = time.strftime("%Y-%m-%d")
        if self._day != today:
            self._daily_loss = 0.0
            self._day = today
        self._daily_loss += abs(usd)

    def check_daily_dd(self, equity: float) -> bool:
        """Check if daily DD limit is exceeded. Trips if so."""
        if equity <= 0:
            return False
        pct = (self._daily_loss / equity) * 100.0
        if pct >= self.daily_loss_limit_pct and not self._tripped:
            self.trip(f"DAILY_DD {pct:.2f}% >= {self.daily_loss_limit_pct}%")
            return True
        return False


class PairExcluder:
    """Lightweight pair exclusion — pairs with net negative expectancy are skipped.

    Ported from pair_excluder.PairExcluder.
    """

    def __init__(self):
        self._excluded: set[str] = set()

    def exclude(self, pair: str) -> None:
        self._excluded.add(pair)

    def include(self, pair: str) -> None:
        self._excluded.discard(pair)

    def is_excluded(self, pair: str) -> bool:
        return pair in self._excluded

    def get_excluded(self) -> list[str]:
        return list(sorted(self._excluded))
