import time

import numpy as np

from signals.base import BaseSignal


def _extract_closes(candles: list[dict]) -> np.ndarray:
    return np.array([float(c["close"]) for c in candles], dtype=np.float64)


def _extract_timestamps(candles: list[dict]) -> list[int]:
    return [int(c["timestamp"]) for c in candles]


def _log_returns(prices: np.ndarray) -> np.ndarray:
    """Compute log returns from a price array."""
    return np.diff(np.log(prices))


def _rolling_std(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling standard deviation (NaN-padded to match input length)."""
    out = np.full(len(arr), np.nan)
    for i in range(window - 1, len(arr)):
        out[i] = float(np.std(arr[i - window + 1 : i + 1], ddof=1))
    return out


# ---------------------------------------------------------------------------
# Signal 1 – Volatility Regime
# ---------------------------------------------------------------------------


class VolatilityRegime(BaseSignal):
    """Classify current vol as low / normal / high using percentile rank.

    - High vol (>= 80th pct) => reduce exposure  => signal = -1
    - Low  vol (<= 20th pct) => increase exposure => signal = +1
    - Normal vol             => linear interpolation between the two
    """

    def __init__(
        self,
        vol_window: int = 14,
        history_window: int = 252,
        high_pct: float = 80.0,
        low_pct: float = 20.0,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="volatility_regime",
            category="volatility",
            lookback_d=max(history_window, vol_window) + 1,
            enabled=enabled,
        )
        self.vol_window = vol_window
        self.history_window = history_window
        self.high_pct = high_pct
        self.low_pct = low_pct
        self._prev_signal: float = 0.0
        self._vol_history: list[float] = []

    def update(self, market_data: dict) -> None:
        candles: list[dict] = market_data["candles"]
        closes = _extract_closes(candles)
        timestamps = _extract_timestamps(candles)

        if len(closes) < self.vol_window + 2:
            return

        log_ret = _log_returns(closes)
        realized_vol = float(np.std(log_ret[-self.vol_window :], ddof=1))
        self._vol_history.append(realized_vol)

        # Percentile rank of current vol within its own history
        history = np.array(self._vol_history[-self.history_window :])
        pct_rank = float(np.sum(history <= realized_vol) / len(history) * 100.0)

        # Map percentile to signal
        if pct_rank >= self.high_pct:
            raw = -1.0
        elif pct_rank <= self.low_pct:
            raw = 1.0
        else:
            # Linear interpolation: low_pct -> +1, high_pct -> -1
            raw = 1.0 - 2.0 * (pct_rank - self.low_pct) / (self.high_pct - self.low_pct)

        # Return tracking
        if len(closes) >= 2:
            period_ret = (closes[-1] - closes[-2]) / closes[-2]
            pnl = self._prev_signal * period_ret
            self._append_return(timestamps[-1], pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 2 – Vol-of-Vol
# ---------------------------------------------------------------------------


class VolOfVol(BaseSignal):
    """Rising volatility-of-volatility signals regime transitions.

    High vol-of-vol => unstable regime => reduce risk => negative signal.
    """

    def __init__(
        self,
        vol_window: int = 14,
        vov_window: int = 14,
        history_window: int = 252,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="vol_of_vol",
            category="volatility",
            lookback_d=vol_window + vov_window + 2,
            enabled=enabled,
        )
        self.vol_window = vol_window
        self.vov_window = vov_window
        self.history_window = history_window
        self._prev_signal: float = 0.0
        self._rolling_vol_series: list[float] = []
        self._vov_history: list[float] = []

    def update(self, market_data: dict) -> None:
        candles: list[dict] = market_data["candles"]
        closes = _extract_closes(candles)
        timestamps = _extract_timestamps(candles)

        if len(closes) < self.vol_window + 2:
            return

        log_ret = _log_returns(closes)
        realized_vol = float(np.std(log_ret[-self.vol_window :], ddof=1))
        self._rolling_vol_series.append(realized_vol)

        if len(self._rolling_vol_series) < self.vov_window:
            return

        # Vol-of-vol: std of rolling vol
        vol_arr = np.array(self._rolling_vol_series[-self.vov_window :])
        vov = float(np.std(vol_arr, ddof=1))
        self._vov_history.append(vov)

        # Percentile rank for signal
        history = np.array(self._vov_history[-self.history_window :])
        pct_rank = float(np.sum(history <= vov) / len(history) * 100.0)

        # High vol-of-vol => reduce exposure
        if pct_rank >= 80.0:
            raw = -1.0
        elif pct_rank <= 20.0:
            raw = 1.0
        else:
            raw = 1.0 - 2.0 * (pct_rank - 20.0) / 60.0

        if len(closes) >= 2:
            period_ret = (closes[-1] - closes[-2]) / closes[-2]
            pnl = self._prev_signal * period_ret
            self._append_return(timestamps[-1], pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 3 – Realized-Implied Volatility Gap (stub – needs options data)
# ---------------------------------------------------------------------------


class RealizedImpliedGap(BaseSignal):
    """Gap between realized volatility and implied volatility.

    Positive gap (IV > RV) => market over-pricing risk => sell vol / bullish.
    Negative gap (RV > IV) => market under-pricing risk => buy vol / bearish.

    NOTE: implied volatility requires options market data (e.g. Deribit DVOL).
    This implementation computes the realised side and expects IV to be
    supplied in market_data["implied_vol"]. If IV is absent, the signal
    falls back to a realised-vol-only heuristic.
    """

    def __init__(
        self,
        vol_window: int = 14,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="realized_implied_gap",
            category="volatility",
            lookback_d=vol_window + 2,
            enabled=enabled,
        )
        self.vol_window = vol_window
        self._prev_signal: float = 0.0
        self._gap_history: list[float] = []

    def update(self, market_data: dict) -> None:
        candles: list[dict] = market_data["candles"]
        closes = _extract_closes(candles)
        timestamps = _extract_timestamps(candles)

        if len(closes) < self.vol_window + 2:
            return

        log_ret = _log_returns(closes)
        realized_vol = float(np.std(log_ret[-self.vol_window :], ddof=1)) * np.sqrt(365)

        # Try to get implied vol; if missing, output neutral
        implied_vol = market_data.get("implied_vol")
        if implied_vol is None:
            self._current_value = 0.0
            self._last_update = time.time()
            return

        implied_vol = float(implied_vol)
        gap = implied_vol - realized_vol
        self._gap_history.append(gap)

        # Normalise by historical gap std
        history = np.array(self._gap_history[-252:])
        std = float(np.std(history)) if len(history) > 1 else 1.0
        std = max(std, 1e-9)

        # Positive gap (IV > RV) => signal positive (market overpricing risk => bullish)
        raw = gap / (2.0 * std)

        if len(closes) >= 2:
            period_ret = (closes[-1] - closes[-2]) / closes[-2]
            pnl = self._prev_signal * period_ret
            self._append_return(timestamps[-1], pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value
