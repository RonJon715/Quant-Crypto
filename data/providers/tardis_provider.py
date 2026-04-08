"""Tardis.dev L2 orderbook replay client (stub).

Endpoint
--------
``https://api.tardis.dev/v1/``

This is a **paid** service.  The client structure is implemented but
full replay logic depends on the specific subscription tier.

An API key is **required**.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from data.schema import OrderbookSnapshot
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.tardis.dev/v1"
_SOURCE = "tardis"
_REQUEST_TIMEOUT = 60.0


class TardisProvider(BaseProvider):
    """Fetch historical L2 orderbook snapshots from Tardis.dev."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return self._api_key is not None

    async def fetch(self, **kwargs: Any) -> list[OrderbookSnapshot]:
        return await self.fetch_l2_snapshots(
            exchange=kwargs["exchange"],
            symbol=kwargs["symbol"],
            from_date=kwargs["from_date"],
            to_date=kwargs["to_date"],
            api_key=kwargs.get("api_key", self._api_key),
        )

    # -- public API ----------------------------------------------------------

    async def fetch_l2_snapshots(
        self,
        exchange: str,
        symbol: str,
        from_date: str,
        to_date: str,
        api_key: str | None = None,
        depth: int = 25,
    ) -> list[OrderbookSnapshot]:
        """Fetch historical L2 orderbook snapshots.

        Parameters
        ----------
        exchange:
            Exchange identifier, e.g. ``"binance"``, ``"deribit"``.
        symbol:
            Exchange-native symbol, e.g. ``"BTCUSDT"``.
        from_date / to_date:
            ISO-8601 date strings, e.g. ``"2024-01-01"``.
        api_key:
            Tardis API key (overrides instance default).
        depth:
            Number of price levels per side.

        Returns
        -------
        list[OrderbookSnapshot]
        """
        key = api_key or self._api_key
        if not key:
            raise ValueError("Tardis.dev requires an API key.")

        # Tardis exposes a streaming / replay endpoint.  For the REST
        # data-download approach, we hit the data-feeds endpoint.
        url = f"{_BASE_URL}/data-feeds/{exchange}"
        headers = {"Authorization": f"Bearer {key}"}
        params: dict[str, Any] = {
            "from": from_date,
            "to": to_date,
            "symbols": symbol,
            "data-types": "book_snapshot",
            "depth": depth,
        }

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()

        # Normalise the pair from exchange-specific format.
        norm_pair = symbol.replace("USDT", "-USD").replace("/", "-")

        records: list[OrderbookSnapshot] = []
        for snap in data:
            ts_us: int = snap.get("timestamp", 0)
            ts_ms = ts_us // 1000 if ts_us > 1e15 else ts_us  # microseconds -> ms

            raw_bids: list[list[float]] = snap.get("bids", [])
            raw_asks: list[list[float]] = snap.get("asks", [])

            bids = [(float(b[0]), float(b[1])) for b in raw_bids[:depth]]
            asks = [(float(a[0]), float(a[1])) for a in raw_asks[:depth]]

            mid = (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else 0.0

            records.append(
                OrderbookSnapshot(
                    timestamp=int(ts_ms),
                    source=_SOURCE,
                    pair=norm_pair,
                    bids=bids,
                    asks=asks,
                    mid_price=mid,
                )
            )

        logger.info(
            "Tardis: fetched %d L2 snapshots for %s/%s (%s -> %s)",
            len(records),
            exchange,
            symbol,
            from_date,
            to_date,
        )
        return records
