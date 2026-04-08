"""CoinMetrics community data provider.

Downloads community-tier CSV data from CoinMetrics and converts it to
:class:`OnChainMetric` records.  The community endpoint is free but
provides a limited set of metrics.

Endpoint
--------
``https://community-api.coinmetrics.io/v4/timeseries/asset-metrics``
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from data.schema import OnChainMetric
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
_SOURCE = "coinmetrics"
_REQUEST_TIMEOUT = 60.0

# Default metrics to fetch when none are specified.
_DEFAULT_METRICS = (
    "AdrActCnt",       # active addresses
    "TxCnt",           # transaction count
    "TxTfrValAdjUSD",  # adjusted transfer value (USD)
    "CapMrktCurUSD",   # market cap (USD)
    "NVTAdj",          # network value to transactions (adjusted)
)


class CoinMetricsProvider(BaseProvider):
    """Fetch on-chain metrics from the CoinMetrics community API."""

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return True  # community tier is free

    async def fetch(self, **kwargs: Any) -> list[OnChainMetric]:
        return await self.fetch_community_data(
            asset=kwargs.get("asset", "btc"),
            metrics=kwargs.get("metrics"),
            start_time=kwargs.get("start_time"),
            end_time=kwargs.get("end_time"),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_community_data(
        self,
        asset: str = "btc",
        metrics: tuple[str, ...] | list[str] | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        page_size: int = 10_000,
    ) -> list[OnChainMetric]:
        """Fetch daily on-chain metrics for *asset*.

        Parameters
        ----------
        asset:
            CoinMetrics asset id, e.g. ``"btc"``, ``"eth"``.
        metrics:
            Iterable of metric names.  ``None`` uses :data:`_DEFAULT_METRICS`.
        start_time / end_time:
            ISO-8601 date strings bounding the query, e.g.
            ``"2020-01-01"``.
        page_size:
            Number of rows per request page.

        Returns
        -------
        list[OnChainMetric]
        """
        if metrics is None:
            metrics = list(_DEFAULT_METRICS)

        params: dict[str, Any] = {
            "assets": asset.lower(),
            "metrics": ",".join(metrics),
            "page_size": page_size,
            "frequency": "1d",
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        all_records: list[OnChainMetric] = []
        next_page_token: str | None = None

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            while True:
                if next_page_token:
                    params["next_page_token"] = next_page_token

                resp = await client.get(_BASE_URL, params=params)
                resp.raise_for_status()
                body: dict[str, Any] = resp.json()

                rows: list[dict[str, Any]] = body.get("data", [])
                for row in rows:
                    time_str: str = row.get("time", "")
                    if not time_str:
                        continue
                    # "2024-01-15T00:00:00.000000000Z"
                    dt = datetime.fromisoformat(
                        time_str.replace("Z", "+00:00")
                    )
                    ts_ms = int(dt.timestamp() * 1000)

                    for m in metrics:
                        val = row.get(m)
                        if val is None or val == "":
                            continue
                        try:
                            fval = float(val)
                        except (ValueError, TypeError):
                            continue

                        all_records.append(
                            OnChainMetric(
                                timestamp=ts_ms,
                                source=_SOURCE,
                                asset=asset.upper(),
                                metric_name=m,
                                value=fval,
                            )
                        )

                next_page_token = body.get("next_page_token")
                if not next_page_token:
                    break

        logger.info(
            "CoinMetrics: fetched %d metric records for %s",
            len(all_records),
            asset,
        )
        return all_records
