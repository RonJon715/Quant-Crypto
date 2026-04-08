"""Glassnode on-chain metrics API provider.

Endpoint
--------
``https://api.glassnode.com/v1/metrics/{category}/{metric}``

Key metrics
~~~~~~~~~~~
* ``market/mvrv`` -- Market Value to Realised Value
* ``addresses/active_count`` -- daily active addresses
* ``transactions/transfers_volume_sum`` -- total transfer volume

An API key is **required**.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from data.schema import OnChainMetric
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.glassnode.com/v1/metrics"
_SOURCE = "glassnode"
_REQUEST_TIMEOUT = 30.0


class GlassnodeProvider(BaseProvider):
    """Async client for the Glassnode REST API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return self._api_key is not None

    async def fetch(self, **kwargs: Any) -> list[OnChainMetric]:
        return await self.fetch_metric(
            category=kwargs["category"],
            metric=kwargs["metric"],
            asset=kwargs.get("asset", "BTC"),
            api_key=kwargs.get("api_key", self._api_key),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_metric(
        self,
        category: str,
        metric: str,
        asset: str = "BTC",
        api_key: str | None = None,
        since: int | None = None,
        until: int | None = None,
        resolution: str = "24h",
    ) -> list[OnChainMetric]:
        """Fetch a single Glassnode metric time-series.

        Parameters
        ----------
        category:
            Metric category, e.g. ``"market"``, ``"addresses"``,
            ``"transactions"``.
        metric:
            Metric name, e.g. ``"mvrv"``, ``"active_count"``,
            ``"transfers_volume_sum"``.
        asset:
            Crypto asset ticker, e.g. ``"BTC"``, ``"ETH"``.
        api_key:
            Glassnode API key (overrides the instance default).
        since / until:
            UNIX *seconds* bounding the query.
        resolution:
            ``"1h"``, ``"24h"``, ``"10m"``, ``"1w"``, ``"1month"``.

        Returns
        -------
        list[OnChainMetric]
        """
        key = api_key or self._api_key
        if not key:
            raise ValueError("Glassnode requires an API key.")

        url = f"{_BASE_URL}/{category}/{metric}"
        params: dict[str, Any] = {
            "a": asset.upper(),
            "api_key": key,
            "i": resolution,
        }
        if since is not None:
            params["s"] = since
        if until is not None:
            params["u"] = until

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()

        metric_name = f"{category}/{metric}"
        records: list[OnChainMetric] = []
        for point in data:
            # Glassnode returns {"t": <unix_seconds>, "v": <value>}
            ts_s: int = point["t"]
            value = point.get("v")
            if value is None:
                continue  # some data points may lack a value
            records.append(
                OnChainMetric(
                    timestamp=ts_s * 1000,
                    source=_SOURCE,
                    asset=asset.upper(),
                    metric_name=metric_name,
                    value=float(value),
                )
            )

        logger.info(
            "Glassnode: fetched %d records for %s %s/%s",
            len(records),
            asset,
            category,
            metric,
        )
        return records
