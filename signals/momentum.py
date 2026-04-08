import time

import numpy as np

from signals.base import BaseSignal


def _extract_closes(candles: list[dict]) -> np.ndarray:
    """Pull close prices from candle dicts into a numpy array."""
    return np.array([float(c["close"]) for c in candles], dtype=np.float64)


def _extract_timestamps(candles: list[dict]) -> list[int]:
    """Pull integer timestamps from candle dicts."""
    return [int(c["timestamp"]) for c in candles]


def _roc(prices: np.ndarray, window: int) -> np.ndarray:
    """Rate of change over *window* periods. Returns array of same length (NaN-padded)."""
    roc = np.full_like(prices, np.nan)
    if len(prices) > window:
        roc[window:] = (prices[window:] - prices[:-window]) / prices[:-window]
    return roc


# ---------------------------------------------------------------------------
# Signal 1 – Dual-Timeframe Momentum
# ---------------------------------------------------------------------------


class DualTimeframeMomentum(BaseSignal):
    """Compare short-window ROC vs medium-window ROC.

    Signal = (short_roc - medium_roc) normalised to [-1, 1].
    """

    def __init__(
        self,
        short_window: int = 4,
        medium_window: int = 24,
        norm_window: int = 100,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="dual_timeframe_momentum",
            category="momentum",
            lookback_d=max(medium_window // 24, 1) * 2,
            enabled=enabled,
        )
        self.short_window = short_window
        self.medium_window = medium_window
        self.norm_window = norm_window
        self._prev_signal: float = 0.0
        self._raw_history: list[float] = []

    # ----- core -----

    def update(self, market_data: dict) -> None:
        candles: list[dict] = market_data["candles"]
        closes = _extract_closes(candles)
        timestamps = _extract_timestamps(candles)

        if len(closes) < self.medium_window + 1:
            return

        short_roc = _roc(closes, self.short_window)
        medium_roc = _roc(closes, self.medium_window)

        # Use last valid entries
        idx = len(closes) - 1
        if np.isnan(short_roc[idx]) or np.isnan(medium_roc[idx]):
            return

        raw = float(short_roc[idx] - medium_roc[idx])
        self._raw_history.append(raw)

        # Normalise using recent history std
        tail = self._raw_history[-self.norm_window :]
        std = float(np.std(tail)) if len(tail) > 1 else 1.0
        std = max(std, 1e-9)
        normalised = raw / (2.0 * std)

        # Track P&L-like return: prev_signal * period price change
        if len(closes) >= 2:
            period_ret = (closes[-1] - closes[-2]) / closes[-2]
            pnl = self._prev_signal * period_ret
            self._append_return(timestamps[-1], pnl)

        self._prev_signal = self._clip_output(normalised)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 2 – Rate-of-Change Acceleration
# ---------------------------------------------------------------------------


class RateOfChangeAcceleration(BaseSignal):
    """Second derivative of price: change-in-ROC.

    Positive => momentum accelerating upward.
    """

    def __init__(
        self,
        roc_window: int = 12,
        accel_window: int = 6,
        norm_window: int = 100,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="roc_acceleration",
            category="momentum",
            lookback_d=max((roc_window + accel_window) // 24, 1) * 2,
            enabled=enabled,
        )
        self.roc_window = roc_window
        self.accel_window = accel_window
        self.norm_window = norm_window
        self._prev_signal: float = 0.0
        self._raw_history: list[float] = []

    def update(self, market_data: dict) -> None:
        candles: list[dict] = market_data["candles"]
        closes = _extract_closes(candles)
        timestamps = _extract_timestamps(candles)

        min_needed = self.roc_window + self.accel_window + 1
        if len(closes) < min_needed:
            return

        roc_series = _roc(closes, self.roc_window)

        # Acceleration = change in ROC over accel_window
        accel = np.full_like(roc_series, np.nan)
        for i in range(self.roc_window + self.accel_window, len(roc_series)):
            if not np.isnan(roc_series[i]) and not np.isnan(roc_series[i - self.accel_window]):
                accel[i] = roc_series[i] - roc_series[i - self.accel_window]

        idx = len(closes) - 1
        if np.isnan(accel[idx]):
            return

        raw = float(accel[idx])
        self._raw_history.append(raw)

        tail = self._raw_history[-self.norm_window :]
        std = float(np.std(tail)) if len(tail) > 1 else 1.0
        std = max(std, 1e-9)
        normalised = raw / (2.0 * std)

        if len(closes) >= 2:
            period_ret = (closes[-1] - closes[-2]) / closes[-2]
            pnl = self._prev_signal * period_ret
            self._append_return(timestamps[-1], pnl)

        self._prev_signal = self._clip_output(normalised)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 3 – Cross-Asset Momentum (BTC as leading indicator)
# ---------------------------------------------------------------------------


class CrossAssetMomentum(BaseSignal):
    """BTC momentum as a leading indicator for alt-coins.

    Computes BTC ROC and uses it as a directional signal for the target asset.
    A positive BTC momentum lead suggests the alt will follow.
    """

    def __init__(
        self,
        btc_roc_window: int = 12,
        alt_roc_window: int = 12,
        lead_periods: int = 4,
        norm_window: int = 100,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="cross_asset_momentum",
            category="momentum",
            lookback_d=max((btc_roc_window + lead_periods) // 24, 1) * 2,
            enabled=enabled,
        )
        self.btc_roc_window = btc_roc_window
        self.alt_roc_window = alt_roc_window
        self.lead_periods = lead_periods
        self.norm_window = norm_window
        self._prev_signal: float = 0.0
        self._raw_history: list[float] = []

    def update(self, market_data: dict) -> None:
        btc_candles: list[dict] = market_data["btc_candles"]
        alt_candles: list[dict] = market_data["candles"]

        btc_closes = _extract_closes(btc_candles)
        alt_closes = _extract_closes(alt_candles)
        alt_timestamps = _extract_timestamps(alt_candles)

        min_len = min(len(btc_closes), len(alt_closes))
        if min_len < self.btc_roc_window + self.lead_periods + 1:
            return

        # Align from the end
        btc_closes = btc_closes[-min_len:]
        alt_closes = alt_closes[-min_len:]

        btc_roc = _roc(btc_closes, self.btc_roc_window)
        alt_roc = _roc(alt_closes, self.alt_roc_window)

        # BTC ROC *lead_periods* ago vs current alt ROC
        btc_lead_idx = len(btc_closes) - 1 - self.lead_periods
        alt_idx = len(alt_closes) - 1

        if btc_lead_idx < 0 or np.isnan(btc_roc[btc_lead_idx]) or np.isnan(alt_roc[alt_idx]):
            return

        # Signal: BTC leading momentum minus alt current momentum
        # Positive means BTC was ahead and alt hasn't caught up yet => bullish
        raw = float(btc_roc[btc_lead_idx] - alt_roc[alt_idx])
        self._raw_history.append(raw)

        tail = self._raw_history[-self.norm_window :]
        std = float(np.std(tail)) if len(tail) > 1 else 1.0
        std = max(std, 1e-9)
        normalised = raw / (2.0 * std)

        if len(alt_closes) >= 2:
            period_ret = (alt_closes[-1] - alt_closes[-2]) / alt_closes[-2]
            pnl = self._prev_signal * period_ret
            ts = alt_timestamps[-1] if alt_timestamps else int(time.time())
            self._append_return(ts, pnl)

        self._prev_signal = self._clip_output(normalised)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value
