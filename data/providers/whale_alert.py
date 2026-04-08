"""Whale Alert large-transaction tracker provider.

Endpoint
--------
``https://api.whale-alert.io/v1/transactions``

An API key is **required**.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from data.schema import OnChainMetric
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_URL = "https://api.whale-alert.io/v1/transactions"
_SOURCE = "whale_alert"
_REQUEST_TIMEOUT = 30.0
_DEFAULT_MIN_VALUE = 500_000  # USD


class WhaleAlertProvider(BaseProvider):
    """Fetch large crypto transactions from Whale Alert."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return self._api_key is not None

    async def fetch(self, **kwargs: Any) -> list[OnChainMetric]:
        return await self.fetch_transactions(
            api_key=kwargs.get("api_key", self._api_key),
            min_value=kwargs.get("min_value", _DEFAULT_MIN_VALUE),
            start=kwargs.get("start"),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_transactions(
        self,
        api_key: str | None = None,
        min_value: int = _DEFAULT_MIN_VALUE,
        start: int | None = None,
    ) -> list[OnChainMetric]:
        """Fetch recent large-value transactions.

        Parameters
        ----------
        api_key:
            Whale Alert API key (overrides instance default).
        min_value:
            Minimum transaction value in USD.
        start:
            UNIX *seconds* timestamp for the query start.  Defaults to
            one hour ago.

        Returns
        -------
        list[OnChainMetric]
            Each transaction is mapped to an :class:`OnChainMetric` with
            ``metric_name="whale_tx"`` and ``value`` equal to the USD
            amount.
        """
        key = api_key or self._api_key
        if not key:
            raise ValueError("Whale Alert requires an API key.")

        if start is None:
            start = int(time.time()) - 3600  # last hour

        params: dict[str, Any] = {
            "api_key": key,
            "min_value": min_value,
            "start": start,
        }

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(_URL, params=params)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()

        if body.get("result") != "success":
            msg = body.get("message", "unknown error")
            logger.error("Whale Alert API error: %s", msg)
            raise RuntimeError(f"Whale Alert error: {msg}")

        txns: list[dict[str, Any]] = body.get("transactions", [])
        records: list[OnChainMetric] = []
        for tx in txns:
            ts_s: int = tx.get("timestamp", 0)
            amount_usd: float = float(tx.get("amount_usd", 0))
            symbol: str = tx.get("symbol", "UNKNOWN").upper()

            records.append(
                OnChainMetric(
                    timestamp=ts_s * 1000,
                    source=_SOURCE,
                    asset=symbol,
                    metric_name="whale_tx",
                    value=amount_usd,
                )
            )

        logger.info("Whale Alert: fetched %d transactions", len(records))
        return records
