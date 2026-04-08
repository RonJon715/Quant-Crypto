"""Blockchain.info free charts API provider.

Endpoint
--------
``https://api.blockchain.info/charts/{chart_name}``

Supported charts
~~~~~~~~~~~~~~~~
* ``hash-rate`` -- network hash rate
* ``n-transactions`` -- confirmed transactions per day
* ``mempool-size`` -- mempool size in bytes
* ``miners-revenue`` -- total miner revenue (USD)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from data.schema import OnChainMetric
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.blockchain.info/charts"
_SOURCE = "blockchain_info"
_REQUEST_TIMEOUT = 30.0

SUPPORTED_CHARTS = frozenset({
    "hash-rate",
    "n-transactions",
    "mempool-size",
    "miners-revenue",
})


class BlockchainInfoProvider(BaseProvider):
    """Fetch on-chain chart data from Blockchain.info."""

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return True  # no API key required

    async def fetch(self, **kwargs: Any) -> list[OnChainMetric]:
        return await self.fetch_chart(
            chart_name=kwargs["chart_name"],
            timespan=kwargs.get("timespan", "1year"),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_chart(
        self,
        chart_name: str,
        timespan: str = "1year",
    ) -> list[OnChainMetric]:
        """Fetch a named chart from Blockchain.info.

        Parameters
        ----------
        chart_name:
            One of :data:`SUPPORTED_CHARTS`.
        timespan:
            Human-readable duration, e.g. ``"1year"``, ``"6months"``,
            ``"30days"``.

        Returns
        -------
        list[OnChainMetric]
        """
        if chart_name not in SUPPORTED_CHARTS:
            raise ValueError(
                f"Unsupported chart '{chart_name}'. "
                f"Choose from {sorted(SUPPORTED_CHARTS)}."
            )

        url = f"{_BASE_URL}/{chart_name}"
        params: dict[str, str] = {
            "timespan": timespan,
            "format": "json",
            "sampled": "true",
        }

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

        values: list[dict[str, Any]] = body.get("values", [])
        records: list[OnChainMetric] = []
        for point in values:
            # The API returns UNIX *seconds*.
            ts_s: int = point["x"]
            records.append(
                OnChainMetric(
                    timestamp=ts_s * 1000,
                    source=_SOURCE,
                    asset="BTC",
                    metric_name=chart_name,
                    value=float(point["y"]),
                )
            )

        logger.info(
            "Blockchain.info: fetched %d data points for chart '%s'",
            len(records),
            chart_name,
        )
        return records
