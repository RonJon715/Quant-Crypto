"""Tests for data provider schema compliance."""

import pytest

from data.schema import CandleRecord, OnChainMetric, SentimentRecord, OrderbookSnapshot


class TestCandleRecord:
    def test_creation(self):
        record = CandleRecord(
            timestamp=1700000000000,
            source="binance",
            pair="BTC-USD",
            open=50000.0,
            high=50500.0,
            low=49500.0,
            close=50200.0,
            volume=1234.5,
            timeframe="1h",
        )
        assert record.pair == "BTC-USD"
        assert record.source == "binance"
        assert record.close == 50200.0

    def test_fields_required(self):
        with pytest.raises(TypeError):
            CandleRecord(timestamp=1700000000000)


class TestOnChainMetric:
    def test_creation(self):
        metric = OnChainMetric(
            timestamp=1700000000000,
            source="glassnode",
            asset="BTC",
            metric_name="mvrv",
            value=2.5,
        )
        assert metric.source == "glassnode"
        assert metric.metric_name == "mvrv"
        assert metric.value == 2.5


class TestSentimentRecord:
    def test_creation(self):
        record = SentimentRecord(
            timestamp=1700000000000,
            source="fear_greed",
            metric_name="fear_greed_index",
            value=25.0,
        )
        assert record.source == "fear_greed"
        assert record.value == 25.0


class TestOrderbookSnapshot:
    def test_creation(self):
        snapshot = OrderbookSnapshot(
            timestamp=1700000000000,
            source="coinbase",
            pair="BTC-USD",
            bids=[(50000.0, 1.0), (49999.0, 0.5)],
            asks=[(50001.0, 1.0), (50002.0, 0.5)],
            mid_price=50000.5,
        )
        assert snapshot.mid_price == 50000.5
        assert len(snapshot.bids) == 2
        assert len(snapshot.asks) == 2
