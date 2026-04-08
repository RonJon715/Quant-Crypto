"""CryptoCompare REST provider for hourly OHLCV candles.

Endpoint
--------
``https://min-api.cryptocompare.com/data/v2/histohour``

An API key is optional for low-rate usage but recommended for production.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from data.schema import CandleRecord
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://min-api.cryptocompare.com/data/v2/histohour"
_SOURCE = "cryptocompare"
_REQUEST_TIMEOUT = 30.0


class CryptoCompareProvider(BaseProvider):
    """Async client for the CryptoCompare *histohour* endpoint."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        # The endpoint works without an API key (rate-limited).
        return True

    async def fetch(self, **kwargs: Any) -> list[CandleRecord]:
        return await self.fetch_hourly(
            fsym=kwargs["fsym"],
            tsym=kwargs.get("tsym", "USD"),
            limit=kwargs.get("limit", 2000),
            api_key=kwargs.get("api_key", self._api_key),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_hourly(
        self,
        fsym: str,
        tsym: str = "USD",
        limit: int = 2000,
        api_key: str | None = None,
    ) -> list[CandleRecord]:
        """Fetch up to *limit* hourly candles.

        Parameters
        ----------
        fsym:
            From-symbol, e.g. ``BTC``.
        tsym:
            To-symbol, e.g. ``USD``.
        limit:
            Number of data points (max 2000).
        api_key:
            Optional CryptoCompare API key.

        Returns
        -------
        list[CandleRecord]
        """
        key = api_key or self._api_key
        headers: dict[str, str] = {}
        if key:
            headers["authorization"] = f"Apikey {key}"

        params: dict[str, Any] = {
            "fsym": fsym.upper(),
            "tsym": tsym.upper(),
            "limit": min(limit, 2000),
        }

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_BASE_URL, params=params, headers=headers)
            resp.raise_for_status()
            body = resp.json()

        if body.get("Response") != "Success":
            msg = body.get("Message", "unknown error")
            logger.error("CryptoCompare API error: %s", msg)
            raise RuntimeError(f"CryptoCompare error: {msg}")

        data_points: list[dict[str, Any]] = body["Data"]["Data"]
        pair = f"{fsym.upper()}-{tsym.upper()}"

        records: list[CandleRecord] = []
        for dp in data_points:
            # The API returns UNIX *seconds*; our schema uses milliseconds.
            ts_s: int = dp["time"]
            if ts_s == 0:
                continue  # sentinel row sometimes at the start
            records.append(
                CandleRecord(
                    timestamp=ts_s * 1000,
                    source=_SOURCE,
                    pair=pair,
                    open=float(dp["open"]),
                    high=float(dp["high"]),
                    low=float(dp["low"]),
                    close=float(dp["close"]),
                    volume=float(dp.get("volumefrom", 0.0)),
                    timeframe="1h",
                )
            )

        logger.info("CryptoCompare: fetched %d hourly candles for %s", len(records), pair)
        return records
