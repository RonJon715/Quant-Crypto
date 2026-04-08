import time

import numpy as np

from signals.base import BaseSignal


def _extract_closes(candles: list[dict]) -> np.ndarray:
    return np.array([float(c["close"]) for c in candles], dtype=np.float64)


def _extract_timestamps(candles: list[dict]) -> list[int]:
    return [int(c["timestamp"]) for c in candles]


# ---------------------------------------------------------------------------
# Signal 1 – DXY Correlation
# ---------------------------------------------------------------------------


class DXYCorrelation(BaseSignal):
    """USD strength (DXY) inverse correlation with crypto.

    Rising DXY => risk-off, USD strength => bearish for crypto.
    Falling DXY => risk-on, USD weakness  => bullish for crypto.

    market_data:
        "dxy_value": list of dicts with "value" and "timestamp"
        "candles":   list of candle dicts with "close" and "timestamp"
    """

    def __init__(
        self,
        correlation_window: int = 30,
        roc_window: int = 5,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="dxy_correlation",
            category="macro",
            lookback_d=correlation_window + roc_window,
            enabled=enabled,
        )
        self.correlation_window = correlation_window
        self.roc_window = roc_window
        self._prev_signal: float = 0.0
        self._dxy_history: list[float] = []
        self._crypto_history: list[float] = []

    def update(self, market_data: dict) -> None:
        dxy_records: list[dict] = market_data["dxy_value"]
        candles: list[dict] = market_data["candles"]

        if not dxy_records or not candles:
            return

        dxy_values = np.array([float(r["value"]) for r in dxy_records], dtype=np.float64)
        dxy_timestamps = [int(r["timestamp"]) for r in dxy_records]
        crypto_closes = _extract_closes(candles)
        crypto_timestamps = _extract_timestamps(candles)

        # Use the latest values
        self._dxy_history.append(float(dxy_values[-1]))
        self._crypto_history.append(float(crypto_closes[-1]))

        if len(self._dxy_history) < self.roc_window + 1:
            return

        # DXY rate of change
        dxy_arr = np.array(self._dxy_history)
        dxy_roc = (dxy_arr[-1] - dxy_arr[-1 - self.roc_window]) / dxy_arr[
            -1 - self.roc_window
        ]

        # Rolling correlation between DXY and crypto returns
        if len(self._dxy_history) >= self.correlation_window:
            dxy_window = np.array(self._dxy_history[-self.correlation_window :])
            crypto_window = np.array(self._crypto_history[-self.correlation_window :])

            # Compute returns
            dxy_rets = np.diff(dxy_window) / dxy_window[:-1]
            crypto_rets = np.diff(crypto_window) / crypto_window[:-1]

            if len(dxy_rets) > 1:
                corr = float(np.corrcoef(dxy_rets, crypto_rets)[0, 1])
                if np.isnan(corr):
                    corr = -0.5  # assume typical inverse correlation
            else:
                corr = -0.5
        else:
            corr = -0.5

        # Signal: DXY rising => bearish for crypto (scaled by correlation strength)
        # The stronger the inverse correlation, the stronger the signal
        inv_corr_weight = max(0.0, -corr)  # weight by how inverse the corr is
        raw = -dxy_roc * inv_corr_weight * 50.0  # scale to reasonable range

        # Return tracking
        if len(crypto_closes) >= 2:
            period_ret = (crypto_closes[-1] - crypto_closes[-2]) / crypto_closes[-2]
            pnl = self._prev_signal * period_ret
            ts = crypto_timestamps[-1]
            self._append_return(ts, pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 2 – M2 Money Supply
# ---------------------------------------------------------------------------


class M2MoneySupply(BaseSignal):
    """M2 money supply expansion is bullish for crypto (global liquidity).

    Accelerating M2 growth => excess liquidity seeking returns => bullish.
    Decelerating M2 growth => tightening conditions => bearish.

    market_data["m2_value"]: list of dicts with "value" and "timestamp"
        value = M2 aggregate (e.g. in trillions USD)
    """

    def __init__(
        self,
        growth_window: int = 12,
        acceleration_window: int = 3,
        history_len: int = 60,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="m2_money_supply",
            category="macro",
            lookback_d=growth_window * 30,
            enabled=enabled,
        )
        self.growth_window = growth_window
        self.acceleration_window = acceleration_window
        self.history_len = history_len
        self._prev_signal: float = 0.0
        self._m2_history: list[float] = []
        self._growth_history: list[float] = []

    def update(self, market_data: dict) -> None:
        m2_records: list[dict] = market_data["m2_value"]

        if not m2_records:
            return

        values = np.array([float(r["value"]) for r in m2_records], dtype=np.float64)
        timestamps = [int(r["timestamp"]) for r in m2_records]

        self._m2_history.append(float(values[-1]))

        if len(self._m2_history) < self.growth_window + 1:
            return

        m2_arr = np.array(self._m2_history)

        # Year-over-year (or window-over-window) growth rate
        current = m2_arr[-1]
        past = m2_arr[-1 - self.growth_window]
        if past <= 0:
            return

        growth_rate = (current - past) / past
        self._growth_history.append(growth_rate)

        if len(self._growth_history) < self.acceleration_window + 1:
            return

        # Acceleration: change in growth rate
        growth_arr = np.array(self._growth_history)
        acceleration = growth_arr[-1] - growth_arr[-1 - self.acceleration_window]

        # Normalise by historical std of acceleration
        if len(self._growth_history) >= 5:
            accel_series = np.diff(growth_arr[-self.history_len :])
            std = float(np.std(accel_series))
            std = max(std, 1e-9)
        else:
            std = max(abs(acceleration), 1e-9)

        z = acceleration / std

        # Positive acceleration => liquidity expanding => bullish
        raw = z / 2.0

        # Return tracking
        if len(self._growth_history) >= 2:
            prev_growth = self._growth_history[-2]
            growth_change = growth_rate - prev_growth
            pnl = self._prev_signal * growth_change * 10.0  # scaled proxy
            self._append_return(timestamps[-1], pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value
