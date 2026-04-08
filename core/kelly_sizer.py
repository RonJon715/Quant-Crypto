"""Empirical Kelly criterion position sizer with Monte Carlo CV estimation.

Provides:
- Classic Kelly fraction calculation
- Bootstrap-based coefficient-of-variation estimation for the trading edge
- Empirical (shrunk) Kelly that accounts for estimation uncertainty
- Hard-cap enforcement (single-position %, total-exposure %, max Kelly multiple)
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class KellySizer:
    """Position sizing via the empirical Kelly criterion."""

    def __init__(
        self,
        max_fraction: float = 0.5,
        mc_paths: int = 10_000,
        max_single_pct: float = 15.0,
        max_total_pct: float = 80.0,
        rng_seed: int | None = None,
    ) -> None:
        """
        Parameters
        ----------
        max_fraction : float
            Upper bound on the Kelly fraction itself (e.g. 0.5 = half-Kelly).
        mc_paths : int
            Number of bootstrap resamples for CV estimation.
        max_single_pct : float
            Maximum exposure for a single position as a percentage of NAV.
        max_total_pct : float
            Maximum total portfolio exposure as a percentage of NAV.
        rng_seed : int | None
            Optional seed for reproducible Monte Carlo runs.
        """
        self.max_fraction = max_fraction
        self.mc_paths = mc_paths
        self.max_single_pct = max_single_pct
        self.max_total_pct = max_total_pct
        self._rng = np.random.default_rng(rng_seed)

    # ------------------------------------------------------------------
    # Classic Kelly
    # ------------------------------------------------------------------

    @staticmethod
    def compute_kelly_fraction(win_prob: float, win_loss_ratio: float) -> float:
        """Classic Kelly: f* = (p * b - q) / b.

        Parameters
        ----------
        win_prob : float
            Probability of a winning trade (0 < p < 1).
        win_loss_ratio : float
            Ratio of average win to average loss (b > 0).

        Returns
        -------
        float
            Optimal Kelly fraction.  Can be negative (= no edge).
        """
        if win_loss_ratio <= 0.0:
            return 0.0
        p = np.clip(win_prob, 0.0, 1.0)
        q = 1.0 - p
        return (p * win_loss_ratio - q) / win_loss_ratio

    # ------------------------------------------------------------------
    # Monte Carlo CV
    # ------------------------------------------------------------------

    def estimate_cv(self, returns: pd.Series) -> float:
        """Monte Carlo estimation of the edge coefficient of variation.

        Draws ``mc_paths`` bootstrap resamples (with replacement) of the
        returns series, computes the mean return (edge) for each path, then
        returns  CV = std(edges) / |mean(edges)|.

        Parameters
        ----------
        returns : pd.Series
            Historical per-trade or per-period returns.

        Returns
        -------
        float
            Coefficient of variation of the estimated edge.
            Returns ``inf`` when mean edge is indistinguishable from zero.
        """
        arr = returns.dropna().values.astype(np.float64)
        n = len(arr)
        if n < 2:
            return float("inf")

        # Bootstrap: draw (mc_paths x n) indices with replacement
        indices = self._rng.integers(0, n, size=(self.mc_paths, n))
        samples = arr[indices]  # (mc_paths, n)
        edges = samples.mean(axis=1)  # (mc_paths,)

        mean_edge = np.mean(edges)
        std_edge = np.std(edges, ddof=1)

        if np.abs(mean_edge) < 1e-15:
            return float("inf")

        return float(std_edge / np.abs(mean_edge))

    # ------------------------------------------------------------------
    # Empirical Kelly
    # ------------------------------------------------------------------

    def empirical_kelly(self, returns: pd.Series) -> float:
        """Shrunk Kelly fraction that accounts for estimation uncertainty.

        ``f_empirical = f_kelly * (1 - CV_edge)``, capped at ``max_fraction``.

        Parameters
        ----------
        returns : pd.Series
            Historical per-trade or per-period returns.

        Returns
        -------
        float
            Empirical Kelly fraction in [0, max_fraction].
        """
        arr = returns.dropna().values.astype(np.float64)
        if len(arr) < 2:
            return 0.0

        wins = arr[arr > 0]
        losses = arr[arr <= 0]

        if len(wins) == 0:
            return 0.0

        win_prob = len(wins) / len(arr)

        avg_win = float(np.mean(wins))
        avg_loss = float(np.abs(np.mean(losses))) if len(losses) > 0 else 1e-9

        if avg_loss < 1e-15:
            avg_loss = 1e-9

        win_loss_ratio = avg_win / avg_loss

        f_kelly = self.compute_kelly_fraction(win_prob, win_loss_ratio)
        if f_kelly <= 0.0:
            return 0.0

        cv = self.estimate_cv(returns)
        shrinkage = max(0.0, 1.0 - cv)
        f_emp = f_kelly * shrinkage

        # Enforce upper cap
        return float(np.clip(f_emp, 0.0, self.max_fraction))

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def size_position(
        self,
        portfolio_value: float,
        returns: pd.Series,
        current_exposure_pct: float,
    ) -> float:
        """Return dollar amount to allocate, respecting all hard caps.

        Hard caps applied (in order):
        1. Empirical Kelly fraction of portfolio value.
        2. Single-position cap (``max_single_pct``).
        3. Remaining room under total-exposure cap (``max_total_pct``).

        Parameters
        ----------
        portfolio_value : float
            Current total portfolio value (NAV).
        returns : pd.Series
            Historical per-trade or per-period returns for the signal/strategy.
        current_exposure_pct : float
            Current total portfolio exposure as a percentage of NAV.

        Returns
        -------
        float
            Dollar amount to allocate.  Always >= 0.
        """
        if portfolio_value <= 0.0:
            return 0.0

        f = self.empirical_kelly(returns)
        if f <= 0.0:
            return 0.0

        # Raw Kelly allocation
        kelly_dollars = f * portfolio_value

        # Cap 1: max single position
        single_cap = (self.max_single_pct / 100.0) * portfolio_value

        # Cap 2: remaining room under total exposure
        remaining_pct = max(0.0, self.max_total_pct - current_exposure_pct)
        total_cap = (remaining_pct / 100.0) * portfolio_value

        allocation = min(kelly_dollars, single_cap, total_cap)
        return max(0.0, float(allocation))
