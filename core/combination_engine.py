"""11-step alpha combination engine.

Implements the full signal-combination procedure:
  1. Collect signal return series
  2. Serial demeaning
  3. Sample variance
  4. Normalize by standard deviation
  5. Drop most recent observation (prevent look-ahead)
  6. Cross-sectional demeaning
  7. Trim to M-2 periods
  8. Forward return estimate
  9. Residual regression (orthogonalisation)
 10. Raw weights: w_i = epsilon_i / sigma_i
 11. Normalize weights so sum(|w|) = 1
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

if TYPE_CHECKING:
    from signals.base import BaseSignal

logger = logging.getLogger(__name__)


class CombinationEngine:
    """Combine heterogeneous alpha signals into a single mega-alpha score."""

    def __init__(
        self,
        signals: list[BaseSignal],
        lookback_M: int = 200,
        forward_d: int = 5,
    ) -> None:
        """
        Parameters
        ----------
        signals : list[BaseSignal]
            Trading signals that expose ``get_returns`` and ``current_output``.
        lookback_M : int
            Maximum look-back window for the combination procedure.
        forward_d : int
            Number of periods used to build the forward-return estimate
            (d-day moving average in Step 8).
        """
        if not signals:
            raise ValueError("At least one signal is required")
        self.signals = signals
        self.lookback_M = lookback_M
        self.forward_d = forward_d

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_weights(self) -> dict[str, float]:
        """Run the full 11-step procedure and return signal weights.

        Returns
        -------
        dict[str, float]
            Mapping of signal name -> normalised weight.
        """
        names = [s.name for s in self.signals]
        n_signals = len(names)

        # Handle trivial case: single signal gets weight 1.0
        if n_signals == 1:
            return {names[0]: 1.0}

        # ----- Step 1: Collect signal return series -----
        raw: dict[str, pd.Series] = {}
        for sig in self.signals:
            ret = sig.get_returns(self.lookback_M)
            if len(ret) < 3:
                logger.warning(
                    "Signal %s has fewer than 3 return observations; skipping",
                    sig.name,
                )
                continue
            raw[sig.name] = ret
        if not raw:
            raise ValueError("No signal has enough return history")

        # Align all series on a common index (outer join, forward-fill gaps)
        df_raw = pd.DataFrame(raw)
        df_raw = df_raw.sort_index().ffill().bfill()

        active_names = list(df_raw.columns)

        # ----- Step 2: Serial demeaning -----
        df_demeaned = df_raw - df_raw.mean(axis=0)

        # ----- Step 3: Sample variance for each signal -----
        variances = df_demeaned.var(axis=0, ddof=1)

        # ----- Step 4: Normalize by standard deviation -----
        stdevs = np.sqrt(variances)
        # Replace zero-variance signals to avoid division by zero
        stdevs_safe = stdevs.replace(0.0, np.nan)
        zero_var_mask = stdevs_safe.isna()
        if zero_var_mask.all():
            # Every signal is constant -- equal weight fallback
            w = 1.0 / len(active_names)
            return {n: w for n in active_names}

        df_norm = df_demeaned.div(stdevs_safe, axis=1)
        # Drop signals that had zero variance
        df_norm = df_norm.dropna(axis=1, how="all")
        active_names = list(df_norm.columns)
        if len(active_names) == 0:
            raise ValueError("All signals have zero variance")
        stdevs_safe = stdevs_safe[active_names]

        # ----- Step 5: Drop most recent observation (prevent look-ahead) -----
        if len(df_norm) > 1:
            df_norm = df_norm.iloc[:-1]

        # ----- Step 6: Cross-sectional demeaning -----
        cross_mean = df_norm.mean(axis=1)
        df_cross = df_norm.sub(cross_mean, axis=0)

        # ----- Step 7: Trim to M-2 periods -----
        keep = max(1, self.lookback_M - 2)
        if len(df_cross) > keep:
            df_cross = df_cross.iloc[-keep:]

        # ----- Step 8: Forward return estimate -----
        # d-day rolling mean of the normalised returns, then standardise
        df_fwd = df_cross.rolling(window=self.forward_d, min_periods=1).mean()
        fwd_std = df_fwd.std(axis=0, ddof=1).replace(0.0, np.nan)
        df_fwd_norm = df_fwd.div(fwd_std, axis=1).fillna(0.0)

        # We need at least 2 rows to run the regression
        if len(df_fwd_norm) < 2:
            w = 1.0 / len(active_names)
            return {n: w for n in active_names}

        # ----- Step 9: Residual regression (orthogonalisation) -----
        # For each signal i, regress its forward-return column on the
        # cross-sectionally demeaned matrix Lambda (all *other* signals).
        # The residual epsilon_i is the independent contribution of signal i.
        epsilons: dict[str, np.ndarray] = {}
        for col in active_names:
            y = df_fwd_norm[col].values  # (T,)
            other_cols = [c for c in active_names if c != col]
            if not other_cols:
                # Only one signal left -- residual equals the signal itself
                epsilons[col] = y
                continue
            X = df_cross[other_cols].values  # (T, K-1)

            # Drop rows with any NaN in X or y
            valid = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
            if valid.sum() < 2:
                epsilons[col] = y
                continue

            X_v = X[valid]
            y_v = y[valid]

            # Guard against singular / near-singular X
            try:
                reg = LinearRegression(fit_intercept=False)
                reg.fit(X_v, y_v)
                y_hat = reg.predict(X_v)
                residual = np.zeros_like(y)
                residual[valid] = y_v - y_hat
                epsilons[col] = residual
            except Exception:
                logger.warning(
                    "Regression failed for signal %s; using raw values", col
                )
                epsilons[col] = y

        # ----- Step 10: Raw weights: w_i = epsilon_i / sigma_i -----
        raw_weights: dict[str, float] = {}
        for col in active_names:
            eps = epsilons[col]
            eps_finite = eps[np.isfinite(eps)]
            if len(eps_finite) == 0:
                raw_weights[col] = 0.0
                continue
            sigma_i = float(stdevs_safe[col])
            if sigma_i == 0.0 or np.isnan(sigma_i):
                raw_weights[col] = 0.0
                continue
            # Use mean absolute residual as the residual "score"
            raw_weights[col] = float(np.mean(eps_finite)) / sigma_i

        # ----- Step 11: Normalize weights so sum(|w|) = 1.0 -----
        total_abs = sum(abs(w) for w in raw_weights.values())
        if total_abs == 0.0:
            # Fallback: equal weight
            n = len(active_names)
            return {name: 1.0 / n for name in active_names}

        weights = {name: w / total_abs for name, w in raw_weights.items()}

        # Include signals that were dropped (zero variance / too short) as 0
        all_names = [s.name for s in self.signals]
        for n in all_names:
            if n not in weights:
                weights[n] = 0.0

        return weights

    def compute_mega_alpha(self, weights: dict[str, float]) -> float:
        """Combine current signal outputs using weights to produce mega alpha.

        Parameters
        ----------
        weights : dict[str, float]
            Signal-name -> weight mapping (output of ``compute_weights``).

        Returns
        -------
        float
            Combined alpha score, typically in [-1, 1].
        """
        alpha = 0.0
        for sig in self.signals:
            w = weights.get(sig.name, 0.0)
            alpha += w * sig.current_output()
        # Clip to [-1, 1] for downstream consumers
        return max(-1.0, min(1.0, alpha))
