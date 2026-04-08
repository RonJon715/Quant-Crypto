"""Portfolio state management with circuit-breaker risk controls.

Tracks positions, equity history, and enforces hard limits:
- 15 % max single-position exposure
- 80 % max total portfolio exposure
- 10 % max rolling 7-day drawdown
- 15 % max rolling 30-day drawdown
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86_400


@dataclass
class _PositionRecord:
    """Internal bookkeeping for a single position."""

    quantity: float = 0.0
    avg_entry_price: float = 0.0
    last_price: float = 0.0
    last_update_ts: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.last_price

    @property
    def notional_cost(self) -> float:
        return self.quantity * self.avg_entry_price

    @property
    def unrealised_pnl(self) -> float:
        return self.market_value - self.notional_cost


@dataclass
class _EquitySnapshot:
    """Timestamped equity observation."""

    timestamp: float  # unix seconds
    equity: float


class Portfolio:
    """Portfolio state manager with integrated risk controls."""

    def __init__(
        self,
        initial_capital: float,
        max_single_pct: float = 15.0,
        max_total_pct: float = 80.0,
        max_dd_7d_pct: float = 10.0,
        max_dd_30d_pct: float = 15.0,
    ) -> None:
        if initial_capital <= 0.0:
            raise ValueError("initial_capital must be positive")

        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.max_single_pct = max_single_pct
        self.max_total_pct = max_total_pct
        self.max_dd_7d_pct = max_dd_7d_pct
        self.max_dd_30d_pct = max_dd_30d_pct

        self._positions: dict[str, _PositionRecord] = {}
        self._equity_history: list[_EquitySnapshot] = [
            _EquitySnapshot(timestamp=time.time(), equity=initial_capital),
        ]
        self._peak_equity: float = initial_capital
        self._halted: bool = False
        self._halt_reason: str = ""

    # ------------------------------------------------------------------
    # Position tracking
    # ------------------------------------------------------------------

    def update_position(self, asset: str, quantity: float, price: float) -> None:
        """Set position to *target* quantity at the given trade price.

        If the position is being increased, the average entry price is updated
        using a weighted average.  If the position is being reduced, the entry
        price stays unchanged (PnL is realised at the current price).

        Setting ``quantity=0`` closes the position.

        Parameters
        ----------
        asset : str
            Asset identifier, e.g. "BTC-USD".
        quantity : float
            Desired final position quantity (signed: positive = long).
        price : float
            Execution / mark price.
        """
        if price <= 0.0:
            raise ValueError(f"Price must be positive, got {price}")

        now = time.time()

        if asset in self._positions:
            pos = self._positions[asset]
            old_qty = pos.quantity
            delta_qty = quantity - old_qty
            delta_cash = -delta_qty * price  # buying costs cash

            if quantity == 0.0:
                # Closing: realise PnL into cash
                self.cash += old_qty * price
                del self._positions[asset]
                return

            if abs(quantity) > abs(old_qty) and np.sign(quantity) == np.sign(old_qty):
                # Increasing -- blend average entry price
                total_cost = pos.avg_entry_price * abs(old_qty) + price * abs(delta_qty)
                pos.avg_entry_price = total_cost / abs(quantity)
            # else: reducing or flipping -- keep avg_entry as is (or reset on flip)
            if np.sign(quantity) != np.sign(old_qty):
                pos.avg_entry_price = price

            self.cash += delta_cash
            pos.quantity = quantity
            pos.last_price = price
            pos.last_update_ts = now
        else:
            if quantity == 0.0:
                return  # nothing to do
            cost = quantity * price
            self.cash -= cost
            self._positions[asset] = _PositionRecord(
                quantity=quantity,
                avg_entry_price=price,
                last_price=price,
                last_update_ts=now,
            )

    def get_position(self, asset: str) -> dict:
        """Return a snapshot dict for a single position.

        Returns an empty dict if the position does not exist.
        """
        pos = self._positions.get(asset)
        if pos is None:
            return {}
        return {
            "asset": asset,
            "quantity": pos.quantity,
            "avg_entry_price": pos.avg_entry_price,
            "last_price": pos.last_price,
            "market_value": pos.market_value,
            "unrealised_pnl": pos.unrealised_pnl,
            "last_update_ts": pos.last_update_ts,
        }

    def get_all_positions(self) -> dict[str, dict]:
        """Return snapshot dicts for every open position."""
        return {asset: self.get_position(asset) for asset in self._positions}

    # ------------------------------------------------------------------
    # Exposure calculations
    # ------------------------------------------------------------------

    @property
    def equity(self) -> float:
        """Total equity = cash + sum of position market values."""
        mv = sum(p.market_value for p in self._positions.values())
        return self.cash + mv

    def total_exposure_pct(self) -> float:
        """Sum of |market_value| / equity * 100."""
        eq = self.equity
        if eq <= 0.0:
            return 100.0  # degenerate -- treat as fully exposed
        gross = sum(abs(p.market_value) for p in self._positions.values())
        return (gross / eq) * 100.0

    def position_exposure_pct(self, asset: str) -> float:
        """Single-position |market_value| / equity * 100."""
        eq = self.equity
        if eq <= 0.0:
            return 100.0
        pos = self._positions.get(asset)
        if pos is None:
            return 0.0
        return (abs(pos.market_value) / eq) * 100.0

    def available_capital(self) -> float:
        """Cash available after reserving for the total-exposure cap."""
        remaining_pct = max(0.0, self.max_total_pct - self.total_exposure_pct())
        cap_room = (remaining_pct / 100.0) * self.equity
        return min(self.cash, cap_room)

    # ------------------------------------------------------------------
    # Drawdown tracking
    # ------------------------------------------------------------------

    def update_equity(self, prices: dict[str, float]) -> None:
        """Mark all positions to market and record an equity snapshot.

        Parameters
        ----------
        prices : dict[str, float]
            Mapping of asset -> latest price.
        """
        now = time.time()
        for asset, price in prices.items():
            pos = self._positions.get(asset)
            if pos is not None:
                pos.last_price = price
                pos.last_update_ts = now

        eq = self.equity
        self._equity_history.append(_EquitySnapshot(timestamp=now, equity=eq))
        if eq > self._peak_equity:
            self._peak_equity = eq

    def _rolling_drawdown_pct(self, window_days: int) -> float:
        """Compute peak-to-trough drawdown over the last *window_days*.

        Returns the drawdown as a positive percentage (e.g. 8.5 means -8.5%).
        """
        if len(self._equity_history) < 2:
            return 0.0

        now = self._equity_history[-1].timestamp
        cutoff = now - window_days * _SECONDS_PER_DAY

        recent = [s for s in self._equity_history if s.timestamp >= cutoff]
        if len(recent) < 2:
            return 0.0

        equities = np.array([s.equity for s in recent])
        running_peak = np.maximum.accumulate(equities)
        drawdowns = (running_peak - equities) / np.where(running_peak > 0, running_peak, 1.0)
        max_dd = float(np.max(drawdowns))
        return max_dd * 100.0

    def check_drawdown_breakers(self) -> tuple[bool, str]:
        """Check rolling drawdown circuit breakers.

        Returns
        -------
        tuple[bool, str]
            ``(should_halt, reason)``.  ``should_halt`` is True when any
            drawdown limit has been breached.
        """
        if self._halted:
            return True, self._halt_reason

        dd_7d = self._rolling_drawdown_pct(7)
        if dd_7d >= self.max_dd_7d_pct:
            self._halted = True
            self._halt_reason = (
                f"7-day rolling drawdown {dd_7d:.2f}% >= limit {self.max_dd_7d_pct}%"
            )
            logger.critical("CIRCUIT BREAKER: %s", self._halt_reason)
            return True, self._halt_reason

        dd_30d = self._rolling_drawdown_pct(30)
        if dd_30d >= self.max_dd_30d_pct:
            self._halted = True
            self._halt_reason = (
                f"30-day rolling drawdown {dd_30d:.2f}% >= limit {self.max_dd_30d_pct}%"
            )
            logger.critical("CIRCUIT BREAKER: %s", self._halt_reason)
            return True, self._halt_reason

        return False, ""

    # ------------------------------------------------------------------
    # Risk checks
    # ------------------------------------------------------------------

    def can_open_position(
        self, asset: str, dollar_amount: float
    ) -> tuple[bool, str]:
        """Pre-trade risk gate.

        Parameters
        ----------
        asset : str
            Asset identifier.
        dollar_amount : float
            Notional dollar value of the proposed trade.

        Returns
        -------
        tuple[bool, str]
            ``(allowed, reason)``.
        """
        if self._halted:
            return False, f"Trading halted: {self._halt_reason}"

        # Check drawdown breakers first
        halted, reason = self.check_drawdown_breakers()
        if halted:
            return False, f"Trading halted: {reason}"

        eq = self.equity
        if eq <= 0.0:
            return False, "Portfolio equity is non-positive"

        # Single-position exposure after trade
        existing_mv = 0.0
        pos = self._positions.get(asset)
        if pos is not None:
            existing_mv = abs(pos.market_value)
        new_exposure_pct = ((existing_mv + abs(dollar_amount)) / eq) * 100.0
        if new_exposure_pct > self.max_single_pct:
            return False, (
                f"Single-position exposure would be {new_exposure_pct:.1f}% "
                f"> limit {self.max_single_pct}%"
            )

        # Total exposure after trade
        current_gross = sum(abs(p.market_value) for p in self._positions.values())
        new_total_pct = ((current_gross + abs(dollar_amount)) / eq) * 100.0
        if new_total_pct > self.max_total_pct:
            return False, (
                f"Total exposure would be {new_total_pct:.1f}% "
                f"> limit {self.max_total_pct}%"
            )

        # Cash check
        if abs(dollar_amount) > self.cash:
            return False, (
                f"Insufficient cash: need ${abs(dollar_amount):.2f}, "
                f"have ${self.cash:.2f}"
            )

        return True, ""

    def compute_target_deltas(
        self,
        target_weights: dict[str, float],
        prices: dict[str, float],
    ) -> dict[str, float]:
        """Compute order deltas to move from current positions to target weights.

        Parameters
        ----------
        target_weights : dict[str, float]
            Asset -> target weight as a fraction of equity (e.g. 0.10 = 10%).
        prices : dict[str, float]
            Asset -> current market price.

        Returns
        -------
        dict[str, float]
            Asset -> delta quantity to trade (positive = buy, negative = sell).
        """
        eq = self.equity
        deltas: dict[str, float] = {}

        all_assets = set(target_weights.keys()) | set(self._positions.keys())
        for asset in all_assets:
            target_w = target_weights.get(asset, 0.0)
            price = prices.get(asset)
            if price is None or price <= 0.0:
                logger.warning("No valid price for %s; skipping delta calc", asset)
                continue

            target_qty = (target_w * eq) / price
            current_qty = 0.0
            pos = self._positions.get(asset)
            if pos is not None:
                current_qty = pos.quantity

            delta = target_qty - current_qty
            if abs(delta) > 1e-12:
                deltas[asset] = delta

        return deltas

    # ------------------------------------------------------------------
    # Utility / introspection
    # ------------------------------------------------------------------

    def reset_halt(self) -> None:
        """Manually reset the circuit-breaker halt (use with caution)."""
        self._halted = False
        self._halt_reason = ""
        logger.info("Circuit-breaker halt has been manually reset")

    def summary(self) -> dict:
        """Return a human-readable summary dict of portfolio state."""
        return {
            "equity": self.equity,
            "cash": self.cash,
            "total_exposure_pct": self.total_exposure_pct(),
            "n_positions": len(self._positions),
            "peak_equity": self._peak_equity,
            "dd_7d_pct": self._rolling_drawdown_pct(7),
            "dd_30d_pct": self._rolling_drawdown_pct(30),
            "halted": self._halted,
            "halt_reason": self._halt_reason,
        }
