"""SQLite-backed candle storage with async support.

Uses *aiosqlite* for non-blocking DB access.  The store enforces a
composite unique key on (timestamp, pair, timeframe, source) so
duplicate ingestion is idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from .schema import CandleRecord

logger = logging.getLogger(__name__)

# ── timeframe -> duration in milliseconds ──────────────────────────────
_TF_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS candles (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    source    TEXT    NOT NULL,
    pair      TEXT    NOT NULL,
    open      REAL    NOT NULL,
    high      REAL    NOT NULL,
    low       REAL    NOT NULL,
    close     REAL    NOT NULL,
    volume    REAL    NOT NULL,
    timeframe TEXT    NOT NULL,
    UNIQUE(timestamp, pair, timeframe, source)
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_candles_lookup
    ON candles (pair, timeframe, timestamp);
"""

_INSERT = """
INSERT OR IGNORE INTO candles
    (timestamp, source, pair, open, high, low, close, volume, timeframe)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

_SELECT = """
SELECT timestamp, source, pair, open, high, low, close, volume, timeframe
FROM candles
WHERE pair = ? AND timeframe = ? AND timestamp >= ? AND timestamp <= ?
ORDER BY timestamp;
"""

_LATEST = """
SELECT MAX(timestamp) FROM candles
WHERE pair = ? AND timeframe = ?;
"""


class CandleStore:
    """Async SQLite candle store with connection-pool pattern."""

    def __init__(self, db_path: str | Path = "candles.db", pool_size: int = 4) -> None:
        self._db_path = str(db_path)
        self._pool_size = pool_size
        self._pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue(
            maxsize=pool_size,
        )
        self._initialised = False

    # ── connection pool ────────────────────────────────────────────────

    async def init_db(self) -> None:
        """Create tables and fill the connection pool."""
        for _ in range(self._pool_size):
            conn = await aiosqlite.connect(self._db_path)
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
            await conn.execute(_CREATE_TABLE)
            await conn.execute(_CREATE_INDEX)
            await conn.commit()
            await self._pool.put(conn)
        self._initialised = True
        logger.info("CandleStore initialised – pool size %d", self._pool_size)

    @asynccontextmanager
    async def _acquire(self) -> AsyncIterator[aiosqlite.Connection]:
        """Borrow a connection from the pool, returning it when done."""
        if not self._initialised:
            raise RuntimeError("CandleStore.init_db() has not been called")
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def close(self) -> None:
        """Drain the pool and close every connection."""
        while not self._pool.empty():
            conn = await self._pool.get()
            await conn.close()
        self._initialised = False

    # ── public API ─────────────────────────────────────────────────────

    async def insert_candles(self, records: list[CandleRecord]) -> int:
        """Insert candles, ignoring duplicates.  Returns rows inserted."""
        if not records:
            return 0
        rows = [
            (
                r.timestamp, r.source, r.pair,
                r.open, r.high, r.low, r.close, r.volume,
                r.timeframe,
            )
            for r in records
        ]
        async with self._acquire() as conn:
            cursor = await conn.executemany(_INSERT, rows)
            await conn.commit()
            return cursor.rowcount  # type: ignore[return-value]

    async def get_candles(
        self,
        pair: str,
        timeframe: str,
        start_ts: int,
        end_ts: int,
    ) -> list[CandleRecord]:
        """Retrieve candles in a time range, ordered ascending."""
        async with self._acquire() as conn:
            cursor = await conn.execute(_SELECT, (pair, timeframe, start_ts, end_ts))
            rows = await cursor.fetchall()
        return [
            CandleRecord(
                timestamp=row[0],
                source=row[1],
                pair=row[2],
                open=row[3],
                high=row[4],
                low=row[5],
                close=row[6],
                volume=row[7],
                timeframe=row[8],
            )
            for row in rows
        ]

    async def get_latest_timestamp(
        self,
        pair: str,
        timeframe: str,
    ) -> int | None:
        """Return the most recent timestamp for *pair*/*timeframe*, or None."""
        async with self._acquire() as conn:
            cursor = await conn.execute(_LATEST, (pair, timeframe))
            row = await cursor.fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])

    async def fill_gaps(
        self,
        pair: str,
        timeframe: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> list[int]:
        """Detect missing candles and return their expected timestamps.

        Does **not** fetch the missing data (that is the responsibility of the
        ingestion pipeline); it simply reports gaps so callers can decide
        what to do.
        """
        step_ms = _TF_MS.get(timeframe)
        if step_ms is None:
            raise ValueError(f"Unknown timeframe {timeframe!r} – known: {list(_TF_MS)}")

        candles = await self.get_candles(
            pair,
            timeframe,
            start_ts or 0,
            end_ts or (2**53),
        )
        if len(candles) < 2:
            return []

        actual_ts = {c.timestamp for c in candles}
        first = candles[0].timestamp
        last = candles[-1].timestamp

        expected_ts: set[int] = set()
        ts = first
        while ts <= last:
            expected_ts.add(ts)
            ts += step_ms

        missing = sorted(expected_ts - actual_ts)
        if missing:
            logger.warning(
                "Gap report for %s/%s: %d missing candles between %d and %d",
                pair,
                timeframe,
                len(missing),
                first,
                last,
            )
        return missing
