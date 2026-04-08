"""Trade-print buffer for VPIN (Volume-synchronised Probability of
Informed Trading) calculation.

Keeps a bounded tape of recent trades and provides a ``compute_vpin``
method that buckets trades into equal-volume bars and measures order-flow
imbalance.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class TradePrint:
    """A single trade execution."""

    timestamp: int  # unix milliseconds
    price: float
    size: float  # unsigned quantity
    side: str  # "buy" | "sell"


class TradeTape:
    """Ring buffer of trade prints with VPIN computation."""

    def __init__(self, maxlen: int = 100_000) -> None:
        self._tape: deque[TradePrint] = deque(maxlen=maxlen)

    # ── mutators ───────────────────────────────────────────────────────

    def append_trade(
        self,
        timestamp: int,
        price: float,
        size: float,
        side: str,
    ) -> None:
        """Append a trade to the tape.

        Parameters
        ----------
        timestamp:
            Unix milliseconds.
        price:
            Execution price.
        size:
            Unsigned quantity.
        side:
            ``"buy"`` or ``"sell"``.
        """
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        self._tape.append(TradePrint(timestamp=timestamp, price=price, size=size, side=side))

    def clear(self) -> None:
        self._tape.clear()

    def __len__(self) -> int:
        return len(self._tape)

    # ── VPIN ───────────────────────────────────────────────────────────

    def compute_vpin(
        self,
        bucket_volume: float,
        num_buckets: int,
    ) -> float:
        """Compute VPIN over the most recent *num_buckets* volume bars.

        Algorithm
        ---------
        1. Walk the tape from oldest to newest, filling fixed-volume
           buckets.  Each bucket accumulates *bucket_volume* units of
           traded volume.
        2. Inside every bucket, track cumulative buy-volume (*V_b*) and
           sell-volume (*V_s*).
        3. ``VPIN = mean(|V_b - V_s|) / bucket_volume`` over the last
           *num_buckets* completed buckets.

        A trade that straddles a bucket boundary is split proportionally.

        Returns
        -------
        float
            VPIN in [0, 1].  Values near 1 suggest heavy informed trading.

        Raises
        ------
        ValueError
            If there are fewer completed buckets than *num_buckets*.
        """
        if bucket_volume <= 0:
            raise ValueError("bucket_volume must be positive")
        if num_buckets <= 0:
            raise ValueError("num_buckets must be positive")

        # Build buckets ──────────────────────────────────────────────────
        buckets: list[float] = []  # |V_b - V_s| for each completed bucket
        bucket_buy = 0.0
        bucket_sell = 0.0
        bucket_remaining = bucket_volume

        for trade in self._tape:
            remaining = trade.size
            while remaining > 0.0:
                fill = min(remaining, bucket_remaining)
                if trade.side == "buy":
                    bucket_buy += fill
                else:
                    bucket_sell += fill

                bucket_remaining -= fill
                remaining -= fill

                # Bucket full?
                if bucket_remaining <= 0.0:
                    buckets.append(abs(bucket_buy - bucket_sell))
                    bucket_buy = 0.0
                    bucket_sell = 0.0
                    bucket_remaining = bucket_volume

        if len(buckets) < num_buckets:
            raise ValueError(
                f"Only {len(buckets)} complete buckets available, "
                f"need {num_buckets}"
            )

        recent = buckets[-num_buckets:]
        return sum(recent) / (num_buckets * bucket_volume)
