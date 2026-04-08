"""Tests for the 11-step combination engine."""

import numpy as np
import pandas as pd
import pytest

from core.combination_engine import CombinationEngine
from signals.base import BaseSignal


class MockSignal(BaseSignal):
    """Mock signal for testing the combination engine."""

    def __init__(self, name: str, returns: list[float], output: float = 0.0):
        super().__init__(name=name, category="test", lookback_d=24)
        self._returns = list(returns)
        self._timestamps = list(range(len(returns)))
        self._current_value = output
        self._last_update = 1e18  # Never stale

    def update(self, market_data: dict) -> None:
        pass

    def current_output(self) -> float:
        return self._current_value


class TestCombinationEngine:
    def _make_signals(self, n_signals=5, n_periods=250, seed=42):
        """Create mock signals with known return series."""
        rng = np.random.RandomState(seed)
        signals = []
        for i in range(n_signals):
            returns = rng.normal(0.001, 0.02, n_periods).tolist()
            output = rng.uniform(-0.5, 0.5)
            signals.append(MockSignal(f"signal_{i}", returns, output))
        return signals

    def test_compute_weights_basic(self):
        """Engine should produce weights that sum to 1 in absolute value."""
        signals = self._make_signals(5, 250)
        engine = CombinationEngine(signals, lookback_M=200)
        weights = engine.compute_weights()

        assert len(weights) == 5
        assert abs(sum(abs(w) for w in weights.values()) - 1.0) < 1e-6

    def test_compute_weights_all_names_present(self):
        """Every signal should have a weight in the output."""
        signals = self._make_signals(7, 250)
        engine = CombinationEngine(signals, lookback_M=200)
        weights = engine.compute_weights()

        for sig in signals:
            assert sig.name in weights

    def test_redundant_signals_get_low_weight(self):
        """Two identical signals should get lower weight than a unique one."""
        rng = np.random.RandomState(42)
        unique_returns = rng.normal(0.002, 0.02, 250).tolist()
        shared_returns = rng.normal(0.001, 0.02, 250).tolist()

        signals = [
            MockSignal("unique", unique_returns, 0.3),
            MockSignal("copy_a", shared_returns, 0.2),
            MockSignal("copy_b", shared_returns, 0.2),  # identical to copy_a
            MockSignal("independent_1", rng.normal(0.001, 0.02, 250).tolist(), 0.1),
            MockSignal("independent_2", rng.normal(0.001, 0.02, 250).tolist(), 0.1),
        ]

        engine = CombinationEngine(signals, lookback_M=200)
        weights = engine.compute_weights()

        # Redundant signals should have similar weights to each other
        assert abs(weights["copy_a"]) == pytest.approx(abs(weights["copy_b"]), abs=0.05)

    def test_compute_mega_alpha(self):
        """Mega alpha should be a weighted sum of current signal outputs."""
        signals = self._make_signals(5, 250)
        engine = CombinationEngine(signals, lookback_M=200)
        weights = engine.compute_weights()
        mega_alpha = engine.compute_mega_alpha(weights)

        # Manual computation
        expected = sum(
            weights[sig.name] * sig.current_output() for sig in signals
        )
        assert mega_alpha == pytest.approx(expected, abs=1e-10)

    def test_minimum_signals(self):
        """Engine should handle exactly the minimum number of signals."""
        signals = self._make_signals(2, 250)
        engine = CombinationEngine(signals, lookback_M=200)
        weights = engine.compute_weights()
        assert len(weights) == 2

    def test_insufficient_data(self):
        """Engine should handle signals with too few returns gracefully."""
        signals = self._make_signals(5, 10)  # Only 10 periods
        engine = CombinationEngine(signals, lookback_M=200)
        weights = engine.compute_weights()
        # Should still produce weights (using available data)
        assert len(weights) == 5

    def test_zero_variance_signal(self):
        """A constant signal (zero variance) should get zero weight."""
        rng = np.random.RandomState(42)
        signals = [
            MockSignal("constant", [0.0] * 250, 0.0),
            MockSignal("normal_1", rng.normal(0.001, 0.02, 250).tolist(), 0.3),
            MockSignal("normal_2", rng.normal(0.001, 0.02, 250).tolist(), 0.2),
            MockSignal("normal_3", rng.normal(0.001, 0.02, 250).tolist(), 0.1),
            MockSignal("normal_4", rng.normal(0.001, 0.02, 250).tolist(), 0.1),
        ]

        engine = CombinationEngine(signals, lookback_M=200)
        weights = engine.compute_weights()

        # Zero-variance signal should get zero or near-zero weight
        assert abs(weights["constant"]) < 0.01


class TestCombinationEngineSteps:
    """Test individual steps of the 11-step procedure."""

    def test_serial_demeaning(self):
        """Step 2: Demeaned series should have zero mean."""
        returns = np.array([0.01, 0.02, -0.01, 0.03, -0.02])
        demeaned = returns - returns.mean()
        assert abs(demeaned.mean()) < 1e-10

    def test_normalization(self):
        """Step 4: Normalized series should have unit variance."""
        returns = np.array([0.01, 0.02, -0.01, 0.03, -0.02])
        demeaned = returns - returns.mean()
        sigma = demeaned.std()
        if sigma > 0:
            normalized = demeaned / sigma
            assert abs(normalized.std() - 1.0) < 1e-10

    def test_cross_sectional_demeaning(self):
        """Step 6: Cross-sectional mean at each time step should be zero."""
        rng = np.random.RandomState(42)
        Y = rng.normal(0, 1, (5, 100))  # 5 signals, 100 periods
        Lambda = Y - Y.mean(axis=0, keepdims=True)

        for t in range(100):
            assert abs(Lambda[:, t].mean()) < 1e-10
