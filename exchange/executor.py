"""VWAP execution engine – splits large orders into price-tiered slices."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from exchange.rest_client import CoinbaseRestClient

logger = logging.getLogger(__name__)


class VWAPExecutor:
    """Volume-Weighted Average Price execution engine.

    Splits a target order quantity into *num_slices* limit orders spaced
    *spread_bps* basis points apart from *mid_price*.  Orders are monitored
    periodically and unfilled slices are re-placed.  All remaining open
    orders are cancelled after *max_duration_seconds*.

    Parameters
    ----------
    rest_client : CoinbaseRestClient
        Authenticated REST client used to place/cancel/query orders.
    num_slices : int
        Number of child limit orders to create.
    spread_bps : int
        Spacing between slices in basis points (1 bp = 0.01%).
    max_duration_seconds : int
        Maximum wall-clock time (seconds) to keep attempting fills.
    """

    _MONITOR_INTERVAL = 60  # seconds between fill checks

    def __init__(
        self,
        rest_client: CoinbaseRestClient,
        num_slices: int = 5,
        spread_bps: int = 10,
        max_duration_seconds: int = 300,
    ) -> None:
        self._client = rest_client
        self._num_slices = num_slices
        self._spread_bps = spread_bps
        self._max_duration = max_duration_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        product_id: str,
        side: str,
        target_qty: float,
        mid_price: float,
    ) -> dict[str, Any]:
        """Run the VWAP execution algorithm.

        Parameters
        ----------
        product_id : str
            Trading pair, e.g. ``"BTC-USD"``.
        side : str
            ``"BUY"`` or ``"SELL"``.
        target_qty : float
            Total base-asset quantity to execute.
        mid_price : float
            Reference price around which slices are spaced.

        Returns
        -------
        dict
            Execution summary with keys:
            - ``filled_qty``  – total base quantity filled.
            - ``avg_price``   – volume-weighted average fill price.
            - ``slippage``    – difference between avg_price and mid_price
              in basis points.
            - ``num_fills``   – number of fully/partially filled slices.
            - ``elapsed``     – wall-clock seconds.
        """
        side = side.upper()
        slice_size = target_qty / self._num_slices
        prices = self._compute_prices(side, mid_price)

        logger.info(
            "VWAP execute: %s %.8f %s in %d slices (spread=%d bps, "
            "max_duration=%ds)",
            side,
            target_qty,
            product_id,
            self._num_slices,
            self._spread_bps,
            self._max_duration,
        )

        # Place initial slices.
        order_ids: list[str] = []
        for price in prices:
            oid = await self._place_slice(product_id, side, price, slice_size)
            if oid:
                order_ids.append(oid)

        start_time = time.monotonic()
        total_filled_qty = 0.0
        total_filled_value = 0.0
        num_fills = 0

        while time.monotonic() - start_time < self._max_duration:
            await asyncio.sleep(self._MONITOR_INTERVAL)

            fills = await self._check_fills(order_ids)

            # Accumulate fill information.
            still_open: list[str] = []
            for oid in order_ids:
                info = fills.get(oid, {})
                status = info.get("status", "UNKNOWN")
                filled = float(info.get("filled_size", 0))
                avg_fill = float(info.get("average_filled_price", 0))

                if status == "FILLED":
                    total_filled_qty += filled
                    total_filled_value += filled * avg_fill
                    num_fills += 1
                elif status in ("OPEN", "PENDING"):
                    still_open.append(oid)
                # CANCELLED / FAILED orders are simply dropped.

            order_ids = still_open

            if not order_ids:
                logger.info("All slices filled.")
                break

            # Re-place unfilled slices that may have been skipped by the
            # market.  Keep the same prices.
            logger.info(
                "%d slices still open after %.0fs",
                len(order_ids),
                time.monotonic() - start_time,
            )

        # Cancel anything still open after the deadline.
        if order_ids:
            # One final fill check before cancelling.
            fills = await self._check_fills(order_ids)
            for oid in order_ids:
                info = fills.get(oid, {})
                filled = float(info.get("filled_size", 0))
                avg_fill = float(info.get("average_filled_price", 0))
                if filled > 0:
                    total_filled_qty += filled
                    total_filled_value += filled * avg_fill
                    num_fills += 1
            await self._cancel_remaining(order_ids)

        elapsed = time.monotonic() - start_time
        avg_price = total_filled_value / total_filled_qty if total_filled_qty else 0.0
        slippage_bps = (
            ((avg_price - mid_price) / mid_price) * 10_000
            if mid_price and total_filled_qty
            else 0.0
        )
        # For buys, positive slippage means we paid more than mid.
        # For sells, flip the sign so positive still means unfavourable.
        if side == "SELL":
            slippage_bps = -slippage_bps

        summary: dict[str, Any] = {
            "filled_qty": total_filled_qty,
            "avg_price": avg_price,
            "slippage": round(slippage_bps, 4),
            "num_fills": num_fills,
            "elapsed": round(elapsed, 2),
        }
        logger.info("VWAP execution summary: %s", summary)
        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_prices(self, side: str, mid_price: float) -> list[float]:
        """Compute *num_slices* prices spaced *spread_bps* apart.

        For BUY orders the prices step downward from mid_price so that the
        closest slice is at mid_price and the furthest is the cheapest.
        For SELL orders the prices step upward.
        """
        bps_step = self._spread_bps / 10_000
        prices: list[float] = []
        for i in range(self._num_slices):
            offset = bps_step * i
            if side == "BUY":
                prices.append(round(mid_price * (1 - offset), 8))
            else:
                prices.append(round(mid_price * (1 + offset), 8))
        return prices

    async def _place_slice(
        self,
        product_id: str,
        side: str,
        price: float,
        size: float,
    ) -> str:
        """Place a single limit-order slice and return its order ID.

        Returns an empty string if the order fails.
        """
        try:
            resp = await self._client.place_limit_order(
                product_id=product_id,
                side=side,
                price=price,
                size=size,
            )
            order_id: str = resp.get("success_response", {}).get("order_id", "")
            if order_id:
                logger.debug(
                    "Placed %s slice: price=%.8f size=%.8f order_id=%s",
                    side,
                    price,
                    size,
                    order_id,
                )
            else:
                logger.warning("Order placement returned no order_id: %s", resp)
            return order_id
        except Exception:
            logger.exception(
                "Failed to place slice: %s %.8f @ %.8f", side, size, price
            )
            return ""

    async def _check_fills(
        self,
        order_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Query the status of each order in *order_ids*.

        Returns a mapping ``{order_id: order_detail_dict}``.
        """
        results: dict[str, dict[str, Any]] = {}
        for oid in order_ids:
            try:
                data = await self._client._request(
                    "GET", f"/api/v3/brokerage/orders/historical/{oid}"
                )
                results[oid] = data.get("order", {})
            except Exception:
                logger.exception("Failed to check order %s", oid)
        return results

    async def _cancel_remaining(self, order_ids: list[str]) -> None:
        """Cancel all orders in *order_ids*."""
        for oid in order_ids:
            try:
                await self._client.cancel_order(oid)
                logger.info("Cancelled remaining order %s", oid)
            except Exception:
                logger.exception("Failed to cancel order %s", oid)
