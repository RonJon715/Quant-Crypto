"""CryptoQuant on-chain analytics API provider.

Endpoint
--------
``https://api.cryptoquant.com/v1/{metric_path}``

Key metrics
~~~~~~~~~~~
* ``btc/exchange-flows/netflow`` -- exchange net flow
* ``btc/flow-indicator/fund-flow-ratio`` -- fund flow ratio
* ``btc/market-indicator/stablecoin-supply-ratio`` -- stablecoin supply ratio (SSR)

An API key is **required** (passed as a Bearer token).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from data.schema import OnChainMetric
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.cryptoquant.com/v1"
_SOURCE = "cryptoquant"
_REQUEST_TIMEOUT = 30.0


class CryptoQuantProvider(BaseProvider):
    """Async client for the CryptoQuant REST API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return self._api_key is not None

    async def fetch(self, **kwargs: Any) -> list[OnChainMetric]:
        return await self.fetch_metric(
            metric_path=kwargs["metric_path"],
            api_key=kwargs.get("api_key", self._api_key),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_metric(
        self,
        metric_path: str,
        api_key: str | None = None,
        window: str = "day",
        limit: int = 365,
    ) -> list[OnChainMetric]:
        """Fetch a CryptoQuant metric time-series.

        Parameters
        ----------
        metric_path:
            Slash-separated path, e.g.
            ``"btc/exchange-flows/netflow"``.
        api_key:
            CryptoQuant API key (overrides instance default).
        window:
            Aggregation window: ``"day"``, ``"hour"``, ``"block"``.
        limit:
            Maximum data points to return.

        Returns
        -------
        list[OnChainMetric]
        """
        key = api_key or self._api_key
        if not key:
            raise ValueError("CryptoQuant requires an API key.")

        url = f"{_BASE_URL}/{metric_path}"
        headers = {"Authorization": f"Bearer {key}"}
        params: dict[str, Any] = {
            "window": window,
            "limit": limit,
        }

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

        # CryptoQuant wraps the results under "result" -> "data".
        result = body.get("result", {})
        data_points: list[dict[str, Any]] = result.get("data", [])

        # Derive asset from the first path segment (e.g. "btc").
        asset = metric_path.split("/")[0].upper() if "/" in metric_path else "BTC"

        records: list[OnChainMetric] = []
        for dp in data_points:
            # Timestamps may be ISO strings or UNIX ms depending on the
            # endpoint.  We normalise both forms.
            raw_ts = dp.get("datetime") or dp.get("date") or dp.get("timestamp")
            if isinstance(raw_ts, str):
                # ISO 8601 -- parse with stdlib
                from datetime import datetime, timezone

                dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                ts_ms = int(dt.timestamp() * 1000)
            elif isinstance(raw_ts, (int, float)):
                ts_ms = int(raw_ts) if raw_ts > 1e12 else int(raw_ts * 1000)
            else:
                continue  # skip if we can't parse

            value = dp.get("value")
            if value is None:
                continue
            records.append(
                OnChainMetric(
                    timestamp=ts_ms,
                    source=_SOURCE,
                    asset=asset,
                    metric_name=metric_path,
                    value=float(value),
                )
            )

        logger.info(
            "CryptoQuant: fetched %d records for %s",
            len(records),
            metric_path,
        )
        return records
