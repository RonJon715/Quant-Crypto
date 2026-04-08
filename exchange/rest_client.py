"""Coinbase Advanced Trade REST API wrapper with rate limiting and retries."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from typing import Any

import httpx

from exchange.auth import load_credentials, sign_request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_REQUESTS_PER_SECOND = 10
_BACKOFF_BASE = 1.0        # seconds
_BACKOFF_MAX = 30.0        # seconds
_BACKOFF_FACTOR = 2.0
_MAX_RETRIES = 6


class CoinbaseRestClient:
    """Async REST client for the Coinbase Advanced Trade API.

    Handles authentication, per-second rate limiting, and automatic retry
    with exponential back-off on HTTP 429 responses.

    Parameters
    ----------
    api_key : str
        Coinbase API key.  Falls back to ``COINBASE_API_KEY`` env var.
    api_secret : str
        Coinbase API secret.  Falls back to ``COINBASE_API_SECRET`` env var.
    sandbox : bool
        If *True* the sandbox base URL is used (currently the same domain;
        Coinbase Advanced Trade does not have a separate sandbox host, but
        the flag is kept for forward-compatibility).
    """

    BASE_URL = "https://api.coinbase.com"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        sandbox: bool = True,
    ) -> None:
        if not api_key or not api_secret:
            api_key, api_secret = load_credentials()
        self._api_key = api_key
        self._api_secret = api_secret
        self._sandbox = sandbox
        self._client: httpx.AsyncClient | None = None

        # Rate-limiting state: timestamps of recent requests.
        self._request_timestamps: deque[float] = deque()
        self._rate_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def close(self) -> None:
        """Shut down the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _enforce_rate_limit(self) -> None:
        """Sleep if the rolling 1-second window already has 10 requests."""
        async with self._rate_lock:
            now = time.monotonic()
            # Purge timestamps older than 1 second.
            while self._request_timestamps and self._request_timestamps[0] < now - 1.0:
                self._request_timestamps.popleft()
            if len(self._request_timestamps) >= _MAX_REQUESTS_PER_SECOND:
                sleep_for = 1.0 - (now - self._request_timestamps[0])
                if sleep_for > 0:
                    logger.debug("Rate limit: sleeping %.3fs", sleep_for)
                    await asyncio.sleep(sleep_for)
            self._request_timestamps.append(time.monotonic())

    # ------------------------------------------------------------------
    # Core request method
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request with rate limiting and retry on 429.

        Parameters
        ----------
        method : str
            HTTP verb (``GET``, ``POST``, ``DELETE``).
        path : str
            API path, e.g. ``/api/v3/brokerage/accounts``.
        body : dict | None
            JSON-serialisable request body (for POST/PUT).

        Returns
        -------
        dict
            Parsed JSON response.

        Raises
        ------
        httpx.HTTPStatusError
            On non-retryable HTTP errors.
        """
        body_str = json.dumps(body) if body else ""
        headers = sign_request(
            self._api_key,
            self._api_secret,
            method.upper(),
            path,
            body_str,
        )
        headers["Content-Type"] = "application/json"

        client = await self._get_client()
        delay = _BACKOFF_BASE

        for attempt in range(1, _MAX_RETRIES + 1):
            await self._enforce_rate_limit()

            response = await client.request(
                method=method.upper(),
                url=path,
                headers=headers,
                content=body_str if body_str else None,
            )

            if response.status_code == 429:
                logger.warning(
                    "429 Too Many Requests (attempt %d/%d) – backing off %.1fs",
                    attempt,
                    _MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * _BACKOFF_FACTOR, _BACKOFF_MAX)
                # Re-sign with a fresh timestamp for the retry.
                headers = sign_request(
                    self._api_key,
                    self._api_secret,
                    method.upper(),
                    path,
                    body_str,
                )
                headers["Content-Type"] = "application/json"
                continue

            response.raise_for_status()
            return response.json()

        # Exhausted all retries – raise the last 429 as an error.
        response.raise_for_status()
        return {}  # unreachable, keeps type-checker happy

    # ------------------------------------------------------------------
    # Account endpoints
    # ------------------------------------------------------------------

    async def get_accounts(self) -> list[dict[str, Any]]:
        """List all trading accounts."""
        data = await self._request("GET", "/api/v3/brokerage/accounts")
        return data.get("accounts", [])

    # ------------------------------------------------------------------
    # Product / market-data endpoints
    # ------------------------------------------------------------------

    async def get_products(self) -> list[dict[str, Any]]:
        """List all available trading pairs."""
        data = await self._request("GET", "/api/v3/brokerage/products")
        return data.get("products", [])

    async def get_candles(
        self,
        product_id: str,
        start: int,
        end: int,
        granularity: str = "ONE_HOUR",
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV candles for *product_id*.

        Parameters
        ----------
        product_id : str
            E.g. ``"BTC-USD"``.
        start : int
            Unix epoch start time.
        end : int
            Unix epoch end time.
        granularity : str
            One of ``ONE_MINUTE``, ``FIVE_MINUTE``, ``FIFTEEN_MINUTE``,
            ``THIRTY_MINUTE``, ``ONE_HOUR``, ``TWO_HOUR``, ``SIX_HOUR``,
            ``ONE_DAY``.
        """
        path = (
            f"/api/v3/brokerage/products/{product_id}/candles"
            f"?start={start}&end={end}&granularity={granularity}"
        )
        data = await self._request("GET", path)
        return data.get("candles", [])

    # ------------------------------------------------------------------
    # Order endpoints
    # ------------------------------------------------------------------

    async def place_limit_order(
        self,
        product_id: str,
        side: str,
        price: float,
        size: float,
    ) -> dict[str, Any]:
        """Place a limit GTC order.

        Parameters
        ----------
        product_id : str
            Trading pair, e.g. ``"BTC-USD"``.
        side : str
            ``"BUY"`` or ``"SELL"``.
        price : float
            Limit price.
        size : float
            Base quantity.

        Returns
        -------
        dict
            Order creation response from Coinbase.
        """
        client_order_id = str(uuid.uuid4())
        body = {
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side.upper(),
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": str(size),
                    "limit_price": str(price),
                }
            },
        }
        return await self._request("POST", "/api/v3/brokerage/orders", body)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel a single order by its server-assigned *order_id*."""
        body = {"order_ids": [order_id]}
        return await self._request(
            "POST", "/api/v3/brokerage/orders/batch_cancel", body
        )

    async def get_orders(
        self,
        product_id: str | None = None,
        status: str = "OPEN",
    ) -> list[dict[str, Any]]:
        """List orders, optionally filtered by product and status.

        Parameters
        ----------
        product_id : str | None
            Filter to this trading pair.
        status : str
            ``"OPEN"``, ``"FILLED"``, ``"CANCELLED"``, ``"PENDING"``, etc.
        """
        params: list[str] = []
        if product_id:
            params.append(f"product_id={product_id}")
        if status:
            params.append(f"order_status={status}")
        qs = "&".join(params)
        path = f"/api/v3/brokerage/orders/historical/batch?{qs}" if qs else "/api/v3/brokerage/orders/historical/batch"
        data = await self._request("GET", path)
        return data.get("orders", [])
