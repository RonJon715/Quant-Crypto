"""Fixed-size ring buffer for L2 orderbook snapshots.

Keeps the most recent *maxlen* snapshots in memory and exposes helpers
for spread, mid-price, and volume imbalance calculations.
"""

from __future__ import annotations

from collections import deque

from .schema import OrderbookSnapshot


class OrderbookBuffer:
    """Deque-backed ring buffer of :class:`OrderbookSnapshot` objects."""

    def __init__(self, maxlen: int = 1000) -> None:
        self._buf: deque[OrderbookSnapshot] = deque(maxlen=maxlen)

    # ── mutators ───────────────────────────────────────────────────────

    def append(self, snapshot: OrderbookSnapshot) -> None:
        """Push a snapshot into the ring buffer (oldest evicted if full)."""
        self._buf.append(snapshot)

    def clear(self) -> None:
        self._buf.clear()

    # ── queries ────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def latest(self) -> OrderbookSnapshot | None:
        """Return the most recent snapshot, or *None* if buffer is empty."""
        return self._buf[-1] if self._buf else None

    def get_recent(self, n: int) -> list[OrderbookSnapshot]:
        """Return the *n* most recent snapshots (newest last)."""
        if n <= 0:
            return []
        # Slice the last n items from the deque.
        start = max(0, len(self._buf) - n)
        return list(self._buf)[start:]

    def current_mid(self) -> float:
        """Return the mid-price from the latest snapshot.

        Computes from the best bid/ask if the snapshot's ``mid_price``
        field is zero (not pre-computed).

        Raises ``ValueError`` when the buffer is empty.
        """
        snap = self._require_latest()
        if snap.mid_price != 0.0:
            return snap.mid_price
        best_bid = snap.bids[0][0] if snap.bids else 0.0
        best_ask = snap.asks[0][0] if snap.asks else 0.0
        if best_bid == 0.0 or best_ask == 0.0:
            raise ValueError("Cannot compute mid: insufficient orderbook data")
        return (best_bid + best_ask) / 2.0

    def current_spread(self) -> float:
        """Return the absolute spread (best_ask - best_bid).

        Raises ``ValueError`` when the buffer is empty or the book has no
        levels on either side.
        """
        snap = self._require_latest()
        if not snap.bids or not snap.asks:
            raise ValueError("Cannot compute spread: empty bid or ask side")
        return snap.asks[0][0] - snap.bids[0][0]

    def get_imbalance(self, depth_pct: float = 0.01) -> float:
        """Volume imbalance within *depth_pct* of mid.

        Returns ``bid_volume - ask_volume`` for all levels whose price is
        within *depth_pct* (e.g. 0.01 = 1 %) of the current mid-price.

        A positive value means heavier bid support; negative means heavier
        ask pressure.
        """
        mid = self.current_mid()
        snap = self._require_latest()

        lower_bound = mid * (1.0 - depth_pct)
        upper_bound = mid * (1.0 + depth_pct)

        bid_vol = sum(qty for price, qty in snap.bids if price >= lower_bound)
        ask_vol = sum(qty for price, qty in snap.asks if price <= upper_bound)

        return bid_vol - ask_vol

    # ── internals ──────────────────────────────────────────────────────

    def _require_latest(self) -> OrderbookSnapshot:
        snap = self.latest
        if snap is None:
            raise ValueError("OrderbookBuffer is empty")
        return snap
