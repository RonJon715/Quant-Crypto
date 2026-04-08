"""
Bulk download on-chain metrics from free providers.

Sources:
  - Blockchain.info (BTC: hash-rate, n-transactions, mempool-size, miners-revenue)
  - DefiLlama (TVL by chain)

Usage:
    python -m scripts.seed_onchain
"""

import asyncio
import argparse
import json
import logging
from pathlib import Path

from data.providers.blockchain_info import BlockchainInfoProvider
from data.providers.defi_llama import DefiLlamaProvider

logger = logging.getLogger(__name__)


async def seed_blockchain_info(output_dir: Path):
    """Download BTC on-chain metrics from blockchain.info."""
    provider = BlockchainInfoProvider()
    charts = ["hash-rate", "n-transactions", "mempool-size", "miners-revenue"]

    for chart in charts:
        logger.info("Fetching blockchain.info chart: %s", chart)
        try:
            metrics = await provider.fetch_chart(chart, timespan="2years")
            outfile = output_dir / f"blockchain_info_{chart}.json"
            data = [
                {
                    "timestamp": m.timestamp,
                    "source": m.source,
                    "asset": m.asset,
                    "metric_name": m.metric_name,
                    "value": m.value,
                }
                for m in metrics
            ]
            outfile.write_text(json.dumps(data, indent=2))
            logger.info("Saved %d records to %s", len(data), outfile)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", chart, e)


async def seed_defi_llama(output_dir: Path, chains: list[str]):
    """Download TVL history from DefiLlama."""
    provider = DefiLlamaProvider()

    for chain in chains:
        logger.info("Fetching DefiLlama TVL for chain: %s", chain)
        try:
            metrics = await provider.fetch_chain_tvl(chain)
            outfile = output_dir / f"defi_llama_tvl_{chain.lower()}.json"
            data = [
                {
                    "timestamp": m.timestamp,
                    "source": m.source,
                    "asset": m.asset,
                    "metric_name": m.metric_name,
                    "value": m.value,
                }
                for m in metrics
            ]
            outfile.write_text(json.dumps(data, indent=2))
            logger.info("Saved %d records to %s", len(data), outfile)
        except Exception as e:
            logger.error("Failed to fetch TVL for %s: %s", chain, e)


async def main_async(output_dir: str, chains: list[str]):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    await asyncio.gather(
        seed_blockchain_info(out),
        seed_defi_llama(out, chains),
    )


def main():
    parser = argparse.ArgumentParser(description="Seed on-chain data from free providers")
    parser.add_argument("--output", default="data_cache/onchain", help="Output directory")
    parser.add_argument(
        "--chains",
        nargs="+",
        default=["Ethereum", "Solana"],
        help="Chains for DefiLlama TVL",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(main_async(args.output, args.chains))


if __name__ == "__main__":
    main()
