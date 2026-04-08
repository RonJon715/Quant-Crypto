"""Binance public klines (OHLCV) provider -- no authentication required.

Endpoint
--------
``GET https://api.binance.com/api/v3/klines``

The provider supports single-page and paginated (bulk) downloads.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from data.schema import CandleRecord
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_KLINES_URL = "https://api.binance.com/api/v3/klines"
_SOURCE = "binance"
_MAX_LIMIT = 1000
_REQUEST_TIMEOUT = 30.0
_RATE_SLEEP: float = 0.25  # seconds between paginated requests


def _binance_symbol(internal_pair: str) -> str:
    """Convert ``BTC-USD`` to Binance format ``BTCUSDT``."""
    base, quote = internal_pair.split("-")
    if quote == "USD":
        quote = "USDT"
    return f"{base}{quote}".upper()


class BinanceBulkProvider(BaseProvider):
    """Fetch OHLCV klines from Binance's public REST API."""

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return True  # public endpoint, no key needed

    async def fetch(self, **kwargs: Any) -> list[CandleRecord]:
        return await self.fetch_klines(
            symbol=kwargs["symbol"],
            interval=kwargs.get("interval", "1h"),
            start_time=kwargs.get("start_time"),
            end_time=kwargs.get("end_time"),
            limit=kwargs.get("limit", _MAX_LIMIT),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_klines(
        self,
        symbol: str,
        interval: str = "1h",
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = _MAX_LIMIT,
    ) -> list[CandleRecord]:
        """Fetch a single page of klines.

        Parameters
        ----------
        symbol:
            Internal pair format, e.g. ``BTC-USD``.
        interval:
            Binance interval string: ``1m``, ``5m``, ``1h``, ``1d``, etc.
        start_time / end_time:
            UNIX milliseconds bounding the query.
        limit:
            Number of klines (max 1000).

        Returns
        -------
        list[CandleRecord]
        """
        bn_symbol = _binance_symbol(symbol)
        params: dict[str, Any] = {
            "symbol": bn_symbol,
            "interval": interval,
            "limit": min(limit, _MAX_LIMIT),
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_KLINES_URL, params=params)
            resp.raise_for_status()
            raw: list[list[Any]] = resp.json()

        norm_pair = symbol  # caller already passes internal format

        records: list[CandleRecord] = []
        for k in raw:
            # Binance kline array layout:
            # [open_time, open, high, low, close, volume, close_time, ...]
            records.append(
                CandleRecord(
                    timestamp=int(k[0]),
                    source=_SOURCE,
                    pair=norm_pair,
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    timeframe=interval,
                )
            )

        logger.info("Binance klines: %d records for %s (%s)", len(records), symbol, interval)
        return records

    async def paginate_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int | None = None,
    ) -> list[CandleRecord]:
        """Paginate through the full history between *start_time* and *end_time*.

        Each page fetches up to 1000 klines.  The cursor advances using the
        last candle's timestamp + 1 ms to avoid overlap.
        """
        end = end_time or int(time.time() * 1000)
        all_records: list[CandleRecord] = []
        cursor = start_time

        while cursor < end:
            page = await self.fetch_klines(
                symbol=symbol,
                interval=interval,
                start_time=cursor,
                end_time=end,
                limit=_MAX_LIMIT,
            )
            if not page:
                break
            all_records.extend(page)
            last_ts = page[-1].timestamp
            if last_ts <= cursor:
                break  # no forward progress
            cursor = last_ts + 1
            await asyncio.sleep(_RATE_SLEEP)

        logger.info(
            "Binance bulk download complete: %d candles for %s %s",
            len(all_records),
            symbol,
            interval,
        )
        return all_records
