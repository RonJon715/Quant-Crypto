"""Twelve Data cross-asset time-series provider.

Endpoint
--------
``https://api.twelvedata.com/time_series``

Supports equities, forex, crypto, and ETFs -- useful for cross-asset
correlation analysis.

An API key is **required**.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from data.schema import CandleRecord
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com/time_series"
_SOURCE = "twelve_data"
_REQUEST_TIMEOUT = 30.0


class TwelveDataProvider(BaseProvider):
    """Async client for the Twelve Data time-series endpoint."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return self._api_key is not None

    async def fetch(self, **kwargs: Any) -> list[CandleRecord]:
        return await self.fetch_time_series(
            symbol=kwargs["symbol"],
            interval=kwargs.get("interval", "1h"),
            api_key=kwargs.get("api_key", self._api_key),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_time_series(
        self,
        symbol: str,
        interval: str = "1h",
        api_key: str | None = None,
        outputsize: int = 5000,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[CandleRecord]:
        """Fetch OHLCV time-series from Twelve Data.

        Parameters
        ----------
        symbol:
            Ticker or pair, e.g. ``"BTC/USD"``, ``"AAPL"``, ``"EUR/USD"``.
        interval:
            ``"1min"``, ``"5min"``, ``"1h"``, ``"1day"``, etc.
        api_key:
            Twelve Data API key (overrides instance default).
        outputsize:
            Number of data points (max 5000).
        start_date / end_date:
            ISO-8601 datetime strings bounding the query.

        Returns
        -------
        list[CandleRecord]
        """
        key = api_key or self._api_key
        if not key:
            raise ValueError("Twelve Data requires an API key.")

        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "apikey": key,
            "outputsize": outputsize,
            "format": "JSON",
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

        if "code" in body and body["code"] != 200:
            msg = body.get("message", "unknown error")
            logger.error("Twelve Data API error: %s", msg)
            raise RuntimeError(f"Twelve Data error: {msg}")

        values: list[dict[str, str]] = body.get("values", [])

        # Normalise pair: "BTC/USD" -> "BTC-USD", "AAPL" -> "AAPL"
        pair = symbol.replace("/", "-")

        records: list[CandleRecord] = []
        for v in values:
            dt_str = v["datetime"]  # e.g. "2024-01-15 14:00:00"
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                # Fallback for date-only format on daily bars.
                dt = datetime.strptime(dt_str, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            ts_ms = int(dt.timestamp() * 1000)

            records.append(
                CandleRecord(
                    timestamp=ts_ms,
                    source=_SOURCE,
                    pair=pair,
                    open=float(v["open"]),
                    high=float(v["high"]),
                    low=float(v["low"]),
                    close=float(v["close"]),
                    volume=float(v.get("volume", 0)),
                    timeframe=interval,
                )
            )

        # Twelve Data returns newest first; we want chronological order.
        records.sort(key=lambda r: r.timestamp)

        logger.info(
            "Twelve Data: fetched %d candles for %s (%s)",
            len(records),
            symbol,
            interval,
        )
        return records
