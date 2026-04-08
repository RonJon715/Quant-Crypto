"""LunarCrush social-sentiment provider.

Endpoint
--------
``https://lunarcrush.com/api4/public/coins/{asset}/time-series/v2``

An API key is **required** (passed via ``Authorization: Bearer``).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from data.schema import SentimentRecord
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://lunarcrush.com/api4/public/coins"
_SOURCE = "lunarcrush"
_REQUEST_TIMEOUT = 30.0


class LunarCrushProvider(BaseProvider):
    """Fetch social-media sentiment metrics from LunarCrush."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return self._api_key is not None

    async def fetch(self, **kwargs: Any) -> list[SentimentRecord]:
        return await self.fetch_social_metrics(
            asset=kwargs["asset"],
            api_key=kwargs.get("api_key", self._api_key),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_social_metrics(
        self,
        asset: str,
        api_key: str | None = None,
        bucket: str = "day",
    ) -> list[SentimentRecord]:
        """Fetch social metrics time-series for *asset*.

        Parameters
        ----------
        asset:
            Coin symbol, e.g. ``"BTC"``, ``"ETH"``.
        api_key:
            LunarCrush API key (overrides instance default).
        bucket:
            Aggregation bucket: ``"hour"`` or ``"day"``.

        Returns
        -------
        list[SentimentRecord]
            Returns one record per bucket.  ``metric_name`` is set to
            ``"galaxy_score"`` (LunarCrush's composite social score).
        """
        key = api_key or self._api_key
        if not key:
            raise ValueError("LunarCrush requires an API key.")

        url = f"{_BASE_URL}/{asset.lower()}/time-series/v2"
        headers = {"Authorization": f"Bearer {key}"}
        params: dict[str, Any] = {"bucket": bucket}

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

        data_points: list[dict[str, Any]] = body.get("data", [])
        records: list[SentimentRecord] = []

        for dp in data_points:
            ts_s = int(dp.get("time", 0))
            if ts_s == 0:
                continue

            # galaxy_score is the headline metric; also capture social_volume.
            galaxy_score = dp.get("galaxy_score")
            if galaxy_score is not None:
                records.append(
                    SentimentRecord(
                        timestamp=ts_s * 1000,
                        source=_SOURCE,
                        metric_name="galaxy_score",
                        value=float(galaxy_score),
                    )
                )

            social_volume = dp.get("social_volume")
            if social_volume is not None:
                records.append(
                    SentimentRecord(
                        timestamp=ts_s * 1000,
                        source=_SOURCE,
                        metric_name="social_volume",
                        value=float(social_volume),
                    )
                )

        logger.info(
            "LunarCrush: fetched %d sentiment records for %s",
            len(records),
            asset,
        )
        return records
