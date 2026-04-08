"""Polymarket prediction-market provider.

Endpoint
--------
``https://clob.polymarket.com/``

No API key is required for reading public market data.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from data.schema import SentimentRecord
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://clob.polymarket.com"
_SOURCE = "polymarket"
_REQUEST_TIMEOUT = 30.0


class PolymarketProvider(BaseProvider):
    """Fetch event probabilities from Polymarket's CLOB API."""

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return True  # public API

    async def fetch(self, **kwargs: Any) -> list[SentimentRecord]:
        return await self.fetch_markets()

    # -- public API ----------------------------------------------------------

    async def fetch_markets(self) -> list[SentimentRecord]:
        """Fetch currently active markets and their implied probabilities.

        Returns one :class:`SentimentRecord` per market, where
        ``metric_name`` is the market question (truncated) and ``value``
        is the best-ask implied probability in [0, 1].
        """
        url = f"{_BASE_URL}/markets"
        now_ms = int(time.time() * 1000)

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()

        records: list[SentimentRecord] = []
        for market in data:
            question: str = market.get("question", "")
            if not question:
                continue

            # Tokens carry the latest prices (YES / NO).
            tokens: list[dict[str, Any]] = market.get("tokens", [])
            yes_price: float | None = None
            for token in tokens:
                if token.get("outcome", "").upper() == "YES":
                    yes_price = float(token.get("price", 0))
                    break

            if yes_price is None:
                continue

            records.append(
                SentimentRecord(
                    timestamp=now_ms,
                    source=_SOURCE,
                    metric_name=question[:120],
                    value=yes_price,
                )
            )

        logger.info("Polymarket: fetched %d active markets", len(records))
        return records
