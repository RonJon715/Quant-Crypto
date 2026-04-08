"""CCXT-based OHLCV provider supporting multiple exchanges.

Supported exchanges: binance, kraken, okx.  Pair format is normalised from
the exchange-native ``BTC/USDT`` style to the internal ``BTC-USD`` style.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import ccxt.async_support as ccxt_async  # type: ignore[import-untyped]

from data.schema import CandleRecord
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pair normalisation helpers
# ---------------------------------------------------------------------------

_STABLE_QUOTE_RE = re.compile(r"^(USDT|USDC|BUSD|TUSD|DAI|FDUSD|UST)$", re.IGNORECASE)


def _normalise_pair(exchange_pair: str) -> str:
    """Convert exchange pair like ``BTC/USDT`` to internal ``BTC-USD``."""
    base, quote = exchange_pair.split("/")
    if _STABLE_QUOTE_RE.match(quote):
        quote = "USD"
    return f"{base}-{quote}"


def _exchange_pair(internal_pair: str, exchange_id: str) -> str:
    """Convert internal pair like ``BTC-USD`` back to exchange format.

    If the quote is ``USD`` we default to ``USDT`` for spot exchanges that
    don't carry a native USD book.
    """
    base, quote = internal_pair.split("-")
    if quote == "USD" and exchange_id not in ("kraken",):
        quote = "USDT"
    return f"{base}/{quote}"


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

SUPPORTED_EXCHANGES = ("binance", "kraken", "okx")

# Maximum candles most exchanges return per request.
_DEFAULT_PAGE_LIMIT = 1000

# Be polite: sleep between paginated requests (seconds).
_RATE_SLEEP: float = 0.35


class CcxtProvider(BaseProvider):
    """Fetch OHLCV candles via *ccxt* from any supported exchange."""

    def __init__(self, exchange_id: str = "binance") -> None:
        if exchange_id not in SUPPORTED_EXCHANGES:
            raise ValueError(
                f"Unsupported exchange '{exchange_id}'. "
                f"Choose from {SUPPORTED_EXCHANGES}."
            )
        self._exchange_id = exchange_id
        self._exchange: ccxt_async.Exchange | None = None

    # -- lifecycle -----------------------------------------------------------

    async def _get_exchange(self) -> ccxt_async.Exchange:
        if self._exchange is None:
            cls = getattr(ccxt_async, self._exchange_id)
            self._exchange = cls({"enableRateLimit": True})
        return self._exchange

    async def close(self) -> None:
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return True  # ccxt needs no API key for public OHLCV

    async def fetch(self, **kwargs: Any) -> list[CandleRecord]:
        """Convenience wrapper that delegates to :meth:`fetch_ohlcv`."""
        return await self.fetch_ohlcv(
            symbol=kwargs["symbol"],
            timeframe=kwargs.get("timeframe", "1h"),
            since_ms=kwargs.get("since_ms"),
            limit=kwargs.get("limit", _DEFAULT_PAGE_LIMIT),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since_ms: int | None = None,
        limit: int = _DEFAULT_PAGE_LIMIT,
    ) -> list[CandleRecord]:
        """Fetch a single page of OHLCV candles.

        Parameters
        ----------
        symbol:
            Internal pair format, e.g. ``BTC-USD``.
        timeframe:
            ccxt timeframe string, e.g. ``1m``, ``1h``, ``1d``.
        since_ms:
            Start time in UNIX milliseconds.  ``None`` means latest.
        limit:
            Maximum candles per request (exchange may cap lower).

        Returns
        -------
        list[CandleRecord]
        """
        exchange = await self._get_exchange()
        ex_pair = _exchange_pair(symbol, self._exchange_id)
        norm_pair = _normalise_pair(ex_pair)

        try:
            raw: list[list[float]] = await exchange.fetch_ohlcv(
                ex_pair, timeframe=timeframe, since=since_ms, limit=limit
            )
        except ccxt_async.BaseError as exc:
            logger.error("ccxt error [%s] %s: %s", self._exchange_id, ex_pair, exc)
            raise

        records: list[CandleRecord] = []
        for row in raw:
            ts, o, h, l, c, v = row[:6]
            records.append(
                CandleRecord(
                    timestamp=int(ts),
                    source=self._exchange_id,
                    pair=norm_pair,
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    volume=float(v),
                    timeframe=timeframe,
                )
            )
        logger.info(
            "Fetched %d candles from %s (%s %s)",
            len(records),
            self._exchange_id,
            symbol,
            timeframe,
        )
        return records

    async def fetch_all_since(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
    ) -> list[CandleRecord]:
        """Paginate through all candles from *since_ms* until now.

        Automatically handles pagination by advancing the ``since`` cursor
        after each batch.  A short sleep is inserted between requests to
        respect exchange rate limits.
        """
        all_records: list[CandleRecord] = []
        cursor = since_ms

        while True:
            page = await self.fetch_ohlcv(
                symbol, timeframe=timeframe, since_ms=cursor, limit=_DEFAULT_PAGE_LIMIT
            )
            if not page:
                break
            all_records.extend(page)
            last_ts = page[-1].timestamp
            if last_ts <= cursor:
                # No progress – we've reached the end.
                break
            cursor = last_ts + 1
            await asyncio.sleep(_RATE_SLEEP)

        logger.info(
            "Paginated fetch complete: %d total candles for %s %s",
            len(all_records),
            symbol,
            timeframe,
        )
        return all_records
