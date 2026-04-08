"""Tests for signal modules."""

import numpy as np
import pytest

from signals.base import BaseSignal
from signals.momentum import DualTimeframeMomentum, RateOfChangeAcceleration
from signals.mean_reversion import BollingerZScore
from signals.volatility import VolatilityRegime, VolOfVol


def make_candle_data(n=300, base_price=50000.0, volatility=0.02, trend=0.0001, seed=42):
    """Generate synthetic candle data for testing."""
    rng = np.random.RandomState(seed)
    prices = [base_price]
    for _ in range(n - 1):
        ret = trend + rng.normal(0, volatility)
        prices.append(prices[-1] * (1 + ret))

    candles = []
    for i, p in enumerate(prices):
        candles.append({
            "timestamp": 1700000000000 + i * 3600000,
            "open": p * (1 + rng.uniform(-0.001, 0.001)),
            "high": p * (1 + abs(rng.normal(0, 0.005))),
            "low": p * (1 - abs(rng.normal(0, 0.005))),
            "close": p,
            "volume": rng.uniform(100, 1000),
        })
    return candles


class TestDualTimeframeMomentum:
    def test_output_range(self):
        """Signal output should be in [-1, 1]."""
        sig = DualTimeframeMomentum(short_window=4, medium_window=24)
        candles = make_candle_data(100, trend=0.001)
        sig.update({"candles": candles})
        assert -1.0 <= sig.current_output() <= 1.0

    def test_accelerating_trend(self):
        """Accelerating uptrend (recent > medium) should produce positive signal."""
        sig = DualTimeframeMomentum(short_window=4, medium_window=24)
        # Flat early, then strong recent surge -> short ROC > medium ROC
        candles = make_candle_data(100, trend=0.0, volatility=0.001)
        for i in range(-4, 0):
            candles[i]["close"] = candles[i]["close"] * 1.03
        sig.update({"candles": candles})
        assert sig.current_output() > 0

    def test_decelerating_trend(self):
        """Decelerating trend (recent < medium) should produce negative signal."""
        sig = DualTimeframeMomentum(short_window=4, medium_window=24)
        # Strong early momentum, then flatten -> short ROC < medium ROC
        candles = make_candle_data(100, trend=0.0, volatility=0.001)
        for i in range(-24, -4):
            candles[i]["close"] = candles[i]["close"] * 1.03
        sig.update({"candles": candles})
        assert sig.current_output() < 0

    def test_returns_accumulate(self):
        """Multiple updates should accumulate returns."""
        sig = DualTimeframeMomentum(short_window=4, medium_window=24)
        for _ in range(5):
            candles = make_candle_data(100)
            sig.update({"candles": candles})
        returns = sig.get_returns(100)
        assert len(returns) >= 1


class TestRateOfChangeAcceleration:
    def test_output_range(self):
        sig = RateOfChangeAcceleration(roc_window=12, accel_window=6)
        candles = make_candle_data(100)
        sig.update({"candles": candles})
        assert -1.0 <= sig.current_output() <= 1.0


class TestBollingerZScore:
    def test_output_range(self):
        sig = BollingerZScore(window=20, num_std=2.0)
        candles = make_candle_data(100)
        sig.update({"candles": candles})
        assert -1.0 <= sig.current_output() <= 1.0

    def test_high_price_negative(self):
        """Price well above upper band should produce negative (overbought) signal."""
        sig = BollingerZScore(window=20, num_std=2.0)
        candles = make_candle_data(100, trend=0.0)
        for i in range(-5, 0):
            candles[i]["close"] *= 1.1
        sig.update({"candles": candles})
        # Overbought -> contrarian signal should be negative
        assert sig.current_output() < 0


class TestVolatilityRegime:
    def test_output_range(self):
        sig = VolatilityRegime(vol_window=14, history_window=100)
        candles = make_candle_data(200, volatility=0.02)
        sig.update({"candles": candles})
        assert -1.0 <= sig.current_output() <= 1.0


class TestVolOfVol:
    def test_output_range(self):
        sig = VolOfVol(vol_window=14, vov_window=14, history_window=100)
        candles = make_candle_data(200, volatility=0.02)
        sig.update({"candles": candles})
        assert -1.0 <= sig.current_output() <= 1.0


class TestBaseSignal:
    def test_stale_detection(self):
        """Signal should report stale if not recently updated."""
        sig = DualTimeframeMomentum(short_window=4, medium_window=24)
        assert sig.is_stale()

    def test_not_stale_after_update(self):
        """Signal should not be stale right after update."""
        sig = DualTimeframeMomentum(short_window=4, medium_window=24)
        candles = make_candle_data(100)
        sig.update({"candles": candles})
        assert not sig.is_stale()

    def test_get_returns(self):
        """get_returns should return a pandas Series."""
        sig = DualTimeframeMomentum(short_window=4, medium_window=24)
        candles = make_candle_data(100)
        sig.update({"candles": candles})
        import pandas as pd
        returns = sig.get_returns(10)
        assert isinstance(returns, pd.Series)
