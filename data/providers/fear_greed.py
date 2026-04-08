"""Alternative.me Fear & Greed Index provider.

Endpoint
--------
``https://api.alternative.me/fng/``

No API key is required.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from data.schema import SentimentRecord
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_URL = "https://api.alternative.me/fng/"
_SOURCE = "fear_greed_index"
_METRIC = "fear_greed"
_REQUEST_TIMEOUT = 30.0


class FearGreedProvider(BaseProvider):
    """Fetch the Crypto Fear & Greed Index from Alternative.me."""

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return True

    async def fetch(self, **kwargs: Any) -> list[SentimentRecord]:
        return await self.fetch_fear_greed(
            limit=kwargs.get("limit", 365),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_fear_greed(
        self,
        limit: int = 365,
    ) -> list[SentimentRecord]:
        """Fetch the last *limit* days of the Fear & Greed Index.

        Parameters
        ----------
        limit:
            Number of past days to retrieve (max ~3650).

        Returns
        -------
        list[SentimentRecord]
            One record per day, value in [0, 100].
        """
        params: dict[str, Any] = {
            "limit": limit,
            "format": "json",
        }

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_URL, params=params)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

        data_points: list[dict[str, str]] = body.get("data", [])
        records: list[SentimentRecord] = []
        for dp in data_points:
            # "timestamp" is UNIX seconds (string).
            ts_s = int(dp["timestamp"])
            records.append(
                SentimentRecord(
                    timestamp=ts_s * 1000,
                    source=_SOURCE,
                    metric_name=_METRIC,
                    value=float(dp["value"]),
                )
            )

        logger.info("Fear & Greed: fetched %d records", len(records))
        return records
