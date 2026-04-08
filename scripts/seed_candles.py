"""
Bulk download 6+ months of hourly OHLCV data via CCXT.
Seeds the SQLite candle store for training and backtesting.

Usage:
    python -m scripts.seed_candles --months 6 --exchange binance
"""

import asyncio
import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

import ccxt

from data.schema import CandleRecord
from data.candle_store import CandleStore

logger = logging.getLogger(__name__)

PAIR_MAP = {
    "BTC-USD": "BTC/USDT",
    "ETH-USD": "ETH/USDT",
    "SOL-USD": "SOL/USDT",
}


def fetch_ohlcv_sync(
    exchange_id: str,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
    limit: int = 1000,
) -> list[list]:
    """Paginate through CCXT fetch_ohlcv to get all candles in range."""
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})

    all_candles = []
    current_since = since_ms

    while current_since < until_ms:
        try:
            candles = exchange.fetch_ohlcv(
                symbol, timeframe, since=current_since, limit=limit
            )
        except ccxt.RateLimitExceeded:
            logger.warning("Rate limited, sleeping 10s...")
            time.sleep(10)
            continue
        except ccxt.BaseError as e:
            logger.error("CCXT error fetching %s: %s", symbol, e)
            break

        if not candles:
            break

        all_candles.extend(candles)
        last_ts = candles[-1][0]
        if last_ts <= current_since:
            break
        current_since = last_ts + 1

        logger.info(
            "Fetched %d candles for %s, last: %s",
            len(candles),
            symbol,
            datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).isoformat(),
        )
        time.sleep(exchange.rateLimit / 1000)

    return all_candles


def normalize_pair(exchange_symbol: str) -> str:
    """Convert exchange symbol back to internal format."""
    for internal, external in PAIR_MAP.items():
        if external == exchange_symbol:
            return internal
    return exchange_symbol.replace("/", "-")


def candles_to_records(
    raw: list[list], source: str, pair: str, timeframe: str
) -> list[CandleRecord]:
    """Convert raw CCXT candle arrays to CandleRecord objects."""
    records = []
    for ts, o, h, l, c, v in raw:
        records.append(
            CandleRecord(
                timestamp=int(ts),
                source=source,
                pair=pair,
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=float(v),
                timeframe=timeframe,
            )
        )
    return records


async def seed(
    exchange_id: str,
    pairs: list[str],
    timeframe: str,
    months: int,
    db_path: str,
):
    """Main seed routine."""
    store = CandleStore(db_path)
    await store.init_db()

    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(days=months * 30)
    since_ms = int(since.timestamp() * 1000)
    until_ms = int(now.timestamp() * 1000)

    for pair in pairs:
        exchange_symbol = PAIR_MAP.get(pair, pair.replace("-", "/"))
        logger.info(
            "Seeding %s from %s (%d months)...", pair, exchange_id, months
        )

        raw = fetch_ohlcv_sync(
            exchange_id, exchange_symbol, timeframe, since_ms, until_ms
        )
        if not raw:
            logger.warning("No data returned for %s", pair)
            continue

        records = candles_to_records(raw, exchange_id, pair, timeframe)
        await store.insert_candles(records)
        logger.info("Inserted %d candles for %s", len(records), pair)


def main():
    parser = argparse.ArgumentParser(description="Seed candle store with OHLCV data")
    parser.add_argument("--exchange", default="binance", help="Exchange ID (ccxt)")
    parser.add_argument("--months", type=int, default=6, help="Months of history")
    parser.add_argument("--timeframe", default="1h", help="Candle timeframe")
    parser.add_argument("--db", default="candles.db", help="SQLite database path")
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=["BTC-USD", "ETH-USD", "SOL-USD"],
        help="Trading pairs",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(seed(args.exchange, args.pairs, args.timeframe, args.months, args.db))


if __name__ == "__main__":
    main()
