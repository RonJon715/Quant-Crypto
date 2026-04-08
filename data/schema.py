"""Normalized data records for any provider.

Every ingestion adapter converts raw API responses into one of these
dataclass records so downstream consumers never depend on provider-specific
shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CandleRecord:
    """Single OHLCV candle."""

    timestamp: int  # unix milliseconds
    source: str  # e.g. "coinbase", "binance"
    pair: str  # normalised, e.g. "BTC-USD"
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str  # e.g. "1m", "1h", "1d"


@dataclass(frozen=True, slots=True)
class OrderbookSnapshot:
    """Point-in-time L2 orderbook snapshot."""

    timestamp: int  # unix milliseconds
    source: str
    pair: str
    bids: list[tuple[float, float]] = field(default_factory=list)  # (price, qty)
    asks: list[tuple[float, float]] = field(default_factory=list)  # (price, qty)
    mid_price: float = 0.0


@dataclass(frozen=True, slots=True)
class OnChainMetric:
    """Single on-chain metric observation."""

    timestamp: int  # unix milliseconds
    source: str  # e.g. "glassnode", "cryptoquant"
    asset: str  # e.g. "BTC"
    metric_name: str  # e.g. "active_addresses"
    value: float


@dataclass(frozen=True, slots=True)
class SentimentRecord:
    """Single sentiment metric observation."""

    timestamp: int  # unix milliseconds
    source: str  # e.g. "reddit", "fear_greed_index"
    metric_name: str  # e.g. "fear_greed", "social_volume"
    value: float
