"""DefiLlama historical chain TVL provider.

Endpoint
--------
``https://api.llama.fi/v2/historicalChainTvl/{chain}``

No API key is required.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from data.schema import OnChainMetric
from data.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.llama.fi/v2/historicalChainTvl"
_SOURCE = "defillama"
_REQUEST_TIMEOUT = 30.0


class DefiLlamaProvider(BaseProvider):
    """Fetch historical Total Value Locked (TVL) for a given chain."""

    # -- BaseProvider --------------------------------------------------------

    def is_available(self) -> bool:
        return True

    async def fetch(self, **kwargs: Any) -> list[OnChainMetric]:
        return await self.fetch_chain_tvl(chain=kwargs["chain"])

    # -- public API ----------------------------------------------------------

    async def fetch_chain_tvl(self, chain: str) -> list[OnChainMetric]:
        """Fetch daily TVL history for *chain*.

        Parameters
        ----------
        chain:
            Chain name as recognised by DefiLlama, e.g. ``"Ethereum"``,
            ``"Solana"``, ``"Arbitrum"``.

        Returns
        -------
        list[OnChainMetric]
        """
        url = f"{_BASE_URL}/{chain}"

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()

        records: list[OnChainMetric] = []
        for point in data:
            # Each element: {"date": <unix_seconds>, "tvl": <float>}
            ts_s = int(point["date"])
            records.append(
                OnChainMetric(
                    timestamp=ts_s * 1000,
                    source=_SOURCE,
                    asset=chain,
                    metric_name="tvl",
                    value=float(point["tvl"]),
                )
            )

        logger.info("DefiLlama: fetched %d TVL records for %s", len(records), chain)
        return records
