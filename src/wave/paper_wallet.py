"""Paper wallet — fake balance + per-trade fees + survival sizing.

This is the owner's redesign (2026-07-28): the wave bot runs on a
$10 paper balance. Every OPEN and CLOSE pays a taker fee
(fee_rate * notional). The bot survives on a "survival instinct":
it sizes as a small % of the live balance, so a $10 account does
not blow up on the first wave, and as the balance grows (winning
streaks) the position size grows with it — up to a 10x target.

The wallet is a tiny in-memory + on-disk singleton so a restart does
not reset the balance to $10 (the owner's equity is "real" across
sessions). If the balance hits <= 0 the engine must stop trading.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("wave.wallet")

# ── Config (env-overridable) ──────────────────────────────────────────
START_BALANCE_USD = float(os.getenv("VAISRAVANA_PAPER_BALANCE", "10.0"))
# Binance USDT-M futures taker fee is 0.04% (0.0004). Maker lower; we
# model every fill as taker for a conservative, worst-case fee.
FEE_RATE = float(os.getenv("VAISRAVANA_PAPER_FEE", "0.0004"))
# Survival sizing: risk this fraction of live balance as notional per wave.
# 20% of $10 = $2 notional. Tiny on purpose — survives drawdowns.
RISK_PCT = float(os.getenv("VAISRAVANA_PAPER_RISK_PCT", "0.20"))
# Hard ceiling so a hot streak cannot over-leverage the paper account.
MAX_BALANCE_TARGET = float(os.getenv("VAISRAVANA_PAPER_MAX", "100.0"))  # 10x of $10
# Stop the engine once balance falls to/below this.
STOP_AT_USD = float(os.getenv("VAISRAVANA_PAPER_STOP", "0.0"))

WALLET_PATH = os.getenv(
    "VAISRAVANA_PAPER_WALLET",
    os.path.join(os.getenv("VAISRAVANA_DATA", "/data"), "paper_wallet.json"),
)


@dataclass
class PaperWallet:
    """Thread-safe fake balance with fees + survival sizing."""

    balance: float = START_BALANCE_USD
    fee_rate: float = FEE_RATE
    risk_pct: float = RISK_PCT
    max_target: float = MAX_BALANCE_TARGET
    stop_at: float = STOP_AT_USD
    trades: int = 0
    fees_paid: float = 0.0
    realized_pnl: float = 0.0   # iter-11: cumulative realized PnL (net of fees) for /wave footer
    peak_balance: float = START_BALANCE_USD
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ── persistence ──────────────────────────────────────────────────────
    def load(self) -> "PaperWallet":
        try:
            with open(WALLET_PATH, "r") as f:
                d = json.load(f)
            self.balance = float(d.get("balance", self.balance))
            self.trades = int(d.get("trades", 0))
            self.fees_paid = float(d.get("fees_paid", 0.0))
            self.realized_pnl = float(d.get("realized_pnl", 0.0))
            self.peak_balance = float(d.get("peak_balance", self.balance))
            log.info(
                "paper wallet loaded: balance=%.4f trades=%d fees=%.4f",
                self.balance, self.trades, self.fees_paid,
            )
        except FileNotFoundError:
            log.info("paper wallet fresh start: balance=%.2f", self.balance)
            self._save()
        except Exception as e:
            log.warning("paper wallet load failed (%s) — using defaults", e)
        return self

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(WALLET_PATH), exist_ok=True)
            with open(WALLET_PATH, "w") as f:
                json.dump({
                    "balance": self.balance,
                    "trades": self.trades,
                    "fees_paid": self.fees_paid,
                    "realized_pnl": self.realized_pnl,
                    "peak_balance": self.peak_balance,
                }, f)
        except Exception as e:
            log.debug("paper wallet save failed: %s", e)

    # ── queries ─────────────────────────────────────────────────────────
    @property
    def is_broke(self) -> bool:
        return self.balance <= self.stop_at

    def notional_for(self, price: float) -> float:
        """Survival sizing: risk_pct of live balance as notional.

        Returns the USD notional to open for a wave at `price`.
        Grows with balance (winning streak) and is clamped so a hot
        run cannot exceed max_target.
        """
        with self._lock:
            b = self.balance
        effective = min(b, self.max_target)
        notion = effective * self.risk_pct
        # never open more notional than the balance itself (no leverage blow-up)
        return max(0.0, min(notion, b))

    # ── mutations ───────────────────────────────────────────────────────
    def charge_open_fee(self, notional: float) -> float:
        """Deduct the taker fee for opening a position. Returns fee paid."""
        fee = notional * self.fee_rate
        with self._lock:
            self.balance -= fee
            self.fees_paid += fee
            self.trades += 1
            self.peak_balance = max(self.peak_balance, self.balance)
            self._save()
        log.info("PAPER fee(open) -%.4f balance=%.4f", fee, self.balance)
        return fee

    def charge_close_fee(self, notional: float) -> float:
        """Deduct the taker fee for closing a position. Returns fee paid."""
        fee = notional * self.fee_rate
        with self._lock:
            self.balance -= fee
            self.fees_paid += fee
            self.peak_balance = max(self.peak_balance, self.balance)
            self._save()
        log.info("PAPER fee(close) -%.4f balance=%.4f", fee, self.balance)
        return fee

    def credit_pnl(self, pnl_usd: float) -> None:
        """Apply realized PnL (already fee-adjusted by caller) to balance."""
        with self._lock:
            self.balance += pnl_usd
            self.realized_pnl += pnl_usd
            self.peak_balance = max(self.peak_balance, self.balance)
            self._save()
        log.info("PAPER pnl %+.4f balance=%.4f", pnl_usd, self.balance)

    def snapshot(self, open_waves: list = None) -> dict:
        """Full card metrics.

        open_waves: list of live Wave objects (need .margin, .notional,
        .live_r, .entry_price, .anchor) so we can report used margin
        + unrealized PnL.
        """
        used = 0.0
        unreal = 0.0
        if open_waves:
            for w in open_waves:
                m = getattr(w, "margin", 0.0) or 0.0
                used += m
                notn = getattr(w, "notional", 0.0) or 0.0
                ent = getattr(w, "entry_price", 0.0) or 0.0
                anc = getattr(w, "anchor", 0.0) or 0.0
                r = getattr(w, "live_r", 0.0) or 0.0
                if ent:
                    risk_per_r = notn * (abs(ent - anc) / ent)
                    unreal += r * risk_per_r
        with self._lock:
            bal = self.balance
            peak = self.peak_balance
            fees = self.fees_paid
            real = self.realized_pnl
            tr = self.trades
        return {
            "balance": round(bal, 4),
            "used": round(used, 4),
            "unrealized": round(unreal, 4),
            "free": round(bal - used, 4),
            "fees_paid": round(fees, 4),
            "realized": round(real, 4),
            "trades": tr,
            "peak": round(peak, 4),
            "max_target": self.max_target,
            "broke": self.is_broke,
        }


# Module-level singleton (one wallet per engine process).
_wallet: Optional[PaperWallet] = None


def get_wallet() -> PaperWallet:
    global _wallet
    if _wallet is None:
        _wallet = PaperWallet().load()
    return _wallet


def reset_wallet() -> PaperWallet:
    """Wipe disk state back to the configured start balance."""
    global _wallet
    try:
        os.remove(WALLET_PATH)
    except FileNotFoundError:
        pass
    _wallet = PaperWallet().load()
    return _wallet
