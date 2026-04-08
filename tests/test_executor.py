"""Tests for the VWAP executor."""

import asyncio
import pytest

from exchange.executor import VWAPExecutor


class MockRestClient:
    """Mock Coinbase REST client for testing.

    Matches the interface the VWAPExecutor actually uses:
    - place_limit_order() returns {"success_response": {"order_id": "..."}}
    - _request("GET", "/api/v3/brokerage/orders/historical/{oid}") returns order info
    - cancel_order() cancels an order
    """

    def __init__(self):
        self._orders = {}
        self._next_id = 1

    async def place_limit_order(self, product_id, side, price, size):
        order_id = f"order_{self._next_id}"
        self._next_id += 1
        self._orders[order_id] = {
            "order_id": order_id,
            "product_id": product_id,
            "side": side,
            "price": str(price),
            "size": str(size),
            "status": "FILLED",
            "filled_size": str(size),
            "average_filled_price": str(price),
        }
        return {"success_response": {"order_id": order_id}}

    async def _request(self, method, path, body=None):
        """Mock the raw _request method used by _check_fills."""
        # Extract order_id from path like /api/v3/brokerage/orders/historical/order_1
        parts = path.rstrip("/").split("/")
        order_id = parts[-1]
        order_data = self._orders.get(order_id, {})
        return {"order": order_data}

    async def cancel_order(self, order_id):
        if order_id in self._orders:
            self._orders[order_id]["status"] = "CANCELLED"
        return {"success": True}


class TestVWAPExecutor:
    def setup_method(self):
        self.client = MockRestClient()
        self.executor = VWAPExecutor(
            rest_client=self.client,
            num_slices=3,
            spread_bps=10,
            max_duration_seconds=5,
        )
        # Reduce monitor interval so tests don't wait 60s
        self.executor._MONITOR_INTERVAL = 0.1

    @pytest.mark.asyncio
    async def test_execute_buy(self):
        """Execute a buy order should split into slices."""
        result = await self.executor.execute(
            product_id="BTC-USD",
            side="buy",
            target_qty=0.1,
            mid_price=50000.0,
        )
        assert result["filled_qty"] > 0
        assert "avg_price" in result

    @pytest.mark.asyncio
    async def test_execute_sell(self):
        """Execute a sell order."""
        result = await self.executor.execute(
            product_id="ETH-USD",
            side="sell",
            target_qty=1.0,
            mid_price=3000.0,
        )
        assert result["filled_qty"] > 0

    @pytest.mark.asyncio
    async def test_slices_correct_total(self):
        """Total quantity across slices should equal target."""
        result = await self.executor.execute(
            product_id="BTC-USD",
            side="buy",
            target_qty=0.3,
            mid_price=50000.0,
        )
        assert result["filled_qty"] == pytest.approx(0.3, rel=0.01)

    @pytest.mark.asyncio
    async def test_zero_quantity(self):
        """Zero quantity should return empty result."""
        result = await self.executor.execute(
            product_id="BTC-USD",
            side="buy",
            target_qty=0.0,
            mid_price=50000.0,
        )
        assert result["filled_qty"] == 0.0
