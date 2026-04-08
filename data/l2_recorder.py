"""Background daemon for recording L2 orderbook snapshots to Parquet.

The actual WebSocket connection will be wired in later.  For now the
recorder accepts snapshots via its :meth:`feed` method and periodically
flushes them to disk as Parquet row groups.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .schema import OrderbookSnapshot

logger = logging.getLogger(__name__)

# Each bid/ask level is stored as (price, qty).  We record up to 20
# levels per side, yielding 80 float columns + timestamp/source/pair.
_MAX_LEVELS = 20


def _build_arrow_schema() -> pa.Schema:
    """Build a PyArrow schema for L2 snapshot rows."""
    fields: list[pa.Field] = [
        pa.field("timestamp", pa.int64()),
        pa.field("source", pa.string()),
        pa.field("pair", pa.string()),
        pa.field("mid_price", pa.float64()),
    ]
    for side in ("bid", "ask"):
        for i in range(_MAX_LEVELS):
            fields.append(pa.field(f"{side}_price_{i}", pa.float64()))
            fields.append(pa.field(f"{side}_qty_{i}", pa.float64()))
    return pa.schema(fields)


_ARROW_SCHEMA = _build_arrow_schema()


def _snapshot_to_row(snap: OrderbookSnapshot) -> dict[str, Any]:
    """Convert a single snapshot into a flat dict matching ``_ARROW_SCHEMA``."""
    row: dict[str, Any] = {
        "timestamp": snap.timestamp,
        "source": snap.source,
        "pair": snap.pair,
        "mid_price": snap.mid_price,
    }
    for side, levels in (("bid", snap.bids), ("ask", snap.asks)):
        for i in range(_MAX_LEVELS):
            if i < len(levels):
                price, qty = levels[i]
            else:
                price, qty = 0.0, 0.0
            row[f"{side}_price_{i}"] = price
            row[f"{side}_qty_{i}"] = qty
    return row


class L2Recorder:
    """Records L2 orderbook snapshots to Parquet files.

    Usage::

        recorder = L2Recorder(output_dir="data/l2")
        await recorder.start(pairs=["BTC-USD", "ETH-USD"])

        # Feed snapshots from your WS adapter:
        recorder.feed(snapshot)

        # When done:
        await recorder.stop()
    """

    def __init__(
        self,
        output_dir: str | Path = "data/l2",
        flush_interval: float = 5.0,
        max_buffer: int = 5_000,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._flush_interval = flush_interval
        self._max_buffer = max_buffer

        self._pairs: list[str] = []
        self._buffer: list[OrderbookSnapshot] = []
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    # ── public API ─────────────────────────────────────────────────────

    async def start(self, pairs: list[str]) -> None:
        """Begin the background recording loop for *pairs*."""
        if self._running:
            logger.warning("L2Recorder already running")
            return
        self._pairs = list(pairs)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._task = asyncio.create_task(self._flush_loop(), name="l2-recorder-flush")
        logger.info(
            "L2Recorder started – pairs=%s  flush_interval=%.1fs  dir=%s",
            self._pairs,
            self._flush_interval,
            self._output_dir,
        )

    async def stop(self) -> None:
        """Stop the background loop and flush remaining data."""
        if not self._running:
            return
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Final flush
        await self._flush()
        logger.info("L2Recorder stopped")

    def feed(self, snapshot: OrderbookSnapshot) -> None:
        """Accept a snapshot from an external WebSocket adapter.

        This method is synchronous so it can be called directly from a
        WS message callback without awaiting.
        """
        if not self._running:
            return
        # Trim to top 20 levels
        trimmed = OrderbookSnapshot(
            timestamp=snapshot.timestamp,
            source=snapshot.source,
            pair=snapshot.pair,
            bids=snapshot.bids[:_MAX_LEVELS],
            asks=snapshot.asks[:_MAX_LEVELS],
            mid_price=snapshot.mid_price,
        )
        self._buffer.append(trimmed)

        # Safety valve: if the buffer is way too large, drop oldest entries
        if len(self._buffer) > self._max_buffer:
            overflow = len(self._buffer) - self._max_buffer
            self._buffer = self._buffer[overflow:]
            logger.warning("L2Recorder buffer overflow – dropped %d snapshots", overflow)

    # ── background loop ────────────────────────────────────────────────

    async def _flush_loop(self) -> None:
        """Periodically flush buffered snapshots to Parquet."""
        try:
            while self._running:
                await asyncio.sleep(self._flush_interval)
                await self._flush()
        except asyncio.CancelledError:
            pass

    async def _flush(self) -> None:
        """Write buffered snapshots to a Parquet file."""
        async with self._lock:
            if not self._buffer:
                return
            to_write = self._buffer.copy()
            self._buffer.clear()

        rows = [_snapshot_to_row(s) for s in to_write]
        # Build columnar dict for PyArrow
        columns: dict[str, list[Any]] = {field.name: [] for field in _ARROW_SCHEMA}
        for row in rows:
            for key in columns:
                columns[key].append(row[key])

        table = pa.table(columns, schema=_ARROW_SCHEMA)
        ts_tag = int(time.time() * 1000)
        filename = self._output_dir / f"l2_snapshot_{ts_tag}.parquet"

        # Run the blocking Parquet write in a thread so we don't block
        # the event loop.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: pq.write_table(table, str(filename), compression="snappy"),
        )
        logger.info("Flushed %d snapshots -> %s", len(rows), filename)
