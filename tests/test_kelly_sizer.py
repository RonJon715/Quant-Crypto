"""Tests for the Kelly position sizer."""

import numpy as np
import pandas as pd
import pytest

from core.kelly_sizer import KellySizer


class TestKellySizer:
    def setup_method(self):
        self.sizer = KellySizer(
            max_fraction=0.5,
            mc_paths=1000,  # fewer paths for faster tests
            max_single_pct=15,
            max_total_pct=80,
        )

    def test_kelly_fraction_positive_edge(self):
        """Positive edge should produce positive Kelly fraction."""
        f = self.sizer.compute_kelly_fraction(win_prob=0.55, win_loss_ratio=1.0)
        assert f > 0
        assert f == pytest.approx(0.10, abs=0.01)  # (0.55*1 - 0.45)/1 = 0.10

    def test_kelly_fraction_no_edge(self):
        """50/50 with 1:1 ratio should produce zero Kelly fraction."""
        f = self.sizer.compute_kelly_fraction(win_prob=0.50, win_loss_ratio=1.0)
        assert f == pytest.approx(0.0, abs=1e-10)

    def test_kelly_fraction_negative_edge(self):
        """Negative edge should produce negative or zero Kelly fraction."""
        f = self.sizer.compute_kelly_fraction(win_prob=0.40, win_loss_ratio=1.0)
        assert f <= 0

    def test_kelly_fraction_high_win_rate(self):
        """High win rate should produce larger fraction."""
        f = self.sizer.compute_kelly_fraction(win_prob=0.70, win_loss_ratio=1.5)
        assert f > 0.3

    def test_estimate_cv(self):
        """CV should be positive and finite for reasonable returns."""
        rng = np.random.RandomState(42)
        returns = pd.Series(rng.normal(0.001, 0.02, 500))
        cv = self.sizer.estimate_cv(returns)
        assert cv >= 0
        assert np.isfinite(cv)

    def test_estimate_cv_consistent_returns(self):
        """Very consistent returns should have low CV."""
        returns = pd.Series(np.full(500, 0.001))
        cv = self.sizer.estimate_cv(returns)
        assert cv < 0.1

    def test_empirical_kelly_capped(self):
        """Empirical Kelly should never exceed max_fraction."""
        rng = np.random.RandomState(42)
        # Very profitable returns
        returns = pd.Series(rng.normal(0.01, 0.005, 500))
        f = self.sizer.empirical_kelly(returns)
        assert f <= self.sizer.max_fraction + 1e-10

    def test_empirical_kelly_non_negative(self):
        """Empirical Kelly should be non-negative."""
        rng = np.random.RandomState(42)
        returns = pd.Series(rng.normal(0.001, 0.02, 500))
        f = self.sizer.empirical_kelly(returns)
        assert f >= 0

    def test_size_position_respects_single_cap(self):
        """Position size should not exceed max_single_position_pct."""
        rng = np.random.RandomState(42)
        returns = pd.Series(rng.normal(0.01, 0.005, 500))
        portfolio_value = 100000.0
        size = self.sizer.size_position(
            portfolio_value=portfolio_value,
            returns=returns,
            current_exposure_pct=0.0,
        )
        max_allowed = portfolio_value * (self.sizer.max_single_pct / 100.0)
        assert size <= max_allowed + 1e-2

    def test_size_position_respects_total_exposure(self):
        """Position size should respect remaining exposure capacity."""
        rng = np.random.RandomState(42)
        returns = pd.Series(rng.normal(0.01, 0.005, 500))
        portfolio_value = 100000.0
        # Already 75% exposed
        size = self.sizer.size_position(
            portfolio_value=portfolio_value,
            returns=returns,
            current_exposure_pct=75.0,
        )
        max_remaining = portfolio_value * ((self.sizer.max_total_pct - 75.0) / 100.0)
        assert size <= max_remaining + 1e-2

    def test_size_position_zero_when_maxed(self):
        """No position when total exposure is at max."""
        rng = np.random.RandomState(42)
        returns = pd.Series(rng.normal(0.01, 0.005, 500))
        size = self.sizer.size_position(
            portfolio_value=100000.0,
            returns=returns,
            current_exposure_pct=80.0,
        )
        assert size == pytest.approx(0.0, abs=1e-2)

    def test_negative_returns_zero_position(self):
        """Losing strategy should produce zero position size."""
        returns = pd.Series(np.full(500, -0.01))
        size = self.sizer.size_position(
            portfolio_value=100000.0,
            returns=returns,
            current_exposure_pct=0.0,
        )
        assert size == pytest.approx(0.0, abs=1e-2)
