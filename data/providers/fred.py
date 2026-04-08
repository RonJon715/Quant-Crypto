"""FRED (Federal Reserve Economic Data) API provider.

Endpoint
--------
``https://api.stlouisfed.org/fred/series/observations``

Key series
~~~~~~~~~~
* ``DFF`` -- Federal Funds Effective Rate
* ``T10Y2Y`` -- 10-Year minus 2-Year Treasury spread
* ``DTWEXBGS`` -- Trade-Weighted US Dollar Index
* ``M2SL`` -- M2 Money Supply

An API key is **required** (free at https://fred.stlouisfed.org/docs/api/api_key.html).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from data.schema import SentimentRecord
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
_SOURCE = "fred"
_REQUEST_TIMEOUT = 30.0


class FredProvider(BaseProvider):
    """Async client for the FRED observations endpoint."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return self._api_key is not None

    async def fetch(self, **kwargs: Any) -> list[SentimentRecord]:
        return await self.fetch_series(
            series_id=kwargs["series_id"],
            api_key=kwargs.get("api_key", self._api_key),
            observation_start=kwargs.get("observation_start"),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_series(
        self,
        series_id: str,
        api_key: str | None = None,
        observation_start: str | None = None,
    ) -> list[SentimentRecord]:
        """Fetch observations for a FRED series.

        Parameters
        ----------
        series_id:
            FRED series identifier, e.g. ``"DFF"``.
        api_key:
            FRED API key (overrides instance default).
        observation_start:
            Earliest observation date as ``YYYY-MM-DD``.  Defaults to
            ``None`` (no lower bound).

        Returns
        -------
        list[SentimentRecord]
            Each observation is mapped to a :class:`SentimentRecord`
            using ``series_id`` as the ``metric_name``.
        """
        key = api_key or self._api_key
        if not key:
            raise ValueError("FRED API requires an API key.")

        params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "sort_order": "asc",
        }
        if observation_start:
            params["observation_start"] = observation_start

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_BASE_URL, params=params)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

        observations: list[dict[str, str]] = body.get("observations", [])
        records: list[SentimentRecord] = []
        for obs in observations:
            date_str: str = obs["date"]  # "YYYY-MM-DD"
            value_str: str = obs["value"]
            if value_str == ".":
                continue  # FRED uses "." for missing values
            try:
                value = float(value_str)
            except ValueError:
                continue

            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ts_ms = int(dt.timestamp() * 1000)

            records.append(
                SentimentRecord(
                    timestamp=ts_ms,
                    source=_SOURCE,
                    metric_name=series_id,
                    value=value,
                )
            )

        logger.info("FRED: fetched %d observations for %s", len(records), series_id)
        return records
