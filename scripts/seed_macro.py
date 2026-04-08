"""
Bulk download macro and sentiment data.

Sources:
  - FRED (DFF, T10Y2Y, DTWEXBGS, M2SL)
  - Fear & Greed Index (alternative.me)

Usage:
    python -m scripts.seed_macro --fred-key YOUR_KEY
"""

import asyncio
import argparse
import json
import logging
from pathlib import Path

from data.providers.fred import FREDProvider
from data.providers.fear_greed import FearGreedProvider

logger = logging.getLogger(__name__)


async def seed_fred(output_dir: Path, api_key: str, series_ids: list[str]):
    """Download FRED economic data series."""
    if not api_key:
        logger.warning("No FRED API key provided, skipping FRED data")
        return

    provider = FREDProvider(api_key=api_key)

    for series_id in series_ids:
        logger.info("Fetching FRED series: %s", series_id)
        try:
            records = await provider.fetch_series(series_id)
            outfile = output_dir / f"fred_{series_id.lower()}.json"
            data = [
                {
                    "timestamp": r.timestamp,
                    "source": r.source,
                    "metric_name": r.metric_name,
                    "value": r.value,
                }
                for r in records
            ]
            outfile.write_text(json.dumps(data, indent=2))
            logger.info("Saved %d records to %s", len(data), outfile)
        except Exception as e:
            logger.error("Failed to fetch FRED %s: %s", series_id, e)


async def seed_fear_greed(output_dir: Path):
    """Download Fear & Greed Index history."""
    provider = FearGreedProvider()
    logger.info("Fetching Fear & Greed Index...")

    try:
        records = await provider.fetch(limit=365)
        outfile = output_dir / "fear_greed_index.json"
        data = [
            {
                "timestamp": r.timestamp,
                "source": r.source,
                "metric_name": r.metric_name,
                "value": r.value,
            }
            for r in records
        ]
        outfile.write_text(json.dumps(data, indent=2))
        logger.info("Saved %d records to %s", len(data), outfile)
    except Exception as e:
        logger.error("Failed to fetch Fear & Greed: %s", e)


async def main_async(output_dir: str, fred_key: str, series_ids: list[str]):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    await asyncio.gather(
        seed_fred(out, fred_key, series_ids),
        seed_fear_greed(out),
    )


def main():
    parser = argparse.ArgumentParser(description="Seed macro and sentiment data")
    parser.add_argument("--output", default="data_cache/macro", help="Output directory")
    parser.add_argument("--fred-key", default="", help="FRED API key (or set FRED_API_KEY env)")
    parser.add_argument(
        "--series",
        nargs="+",
        default=["DFF", "T10Y2Y", "DTWEXBGS", "M2SL"],
        help="FRED series IDs",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    import os
    fred_key = args.fred_key or os.environ.get("FRED_API_KEY", "")
    asyncio.run(main_async(args.output, fred_key, args.series))


if __name__ == "__main__":
    main()
