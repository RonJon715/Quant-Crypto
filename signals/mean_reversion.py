import time

import numpy as np

from signals.base import BaseSignal


def _extract_closes(candles: list[dict]) -> np.ndarray:
    return np.array([float(c["close"]) for c in candles], dtype=np.float64)


def _extract_timestamps(candles: list[dict]) -> list[int]:
    return [int(c["timestamp"]) for c in candles]


# ---------------------------------------------------------------------------
# Signal 1 – Cross-Pair Spread (e.g. ETH/BTC ratio mean-reversion)
# ---------------------------------------------------------------------------


class CrossPairSpread(BaseSignal):
    """ETH/BTC (or any A/B) ratio deviation from its rolling mean.

    market_data keys: "candles_a", "candles_b"
    Signal is positive when the ratio is below the mean (buy A / sell B)
    and negative when the ratio is above the mean (sell A / buy B).
    """

    def __init__(
        self,
        rolling_window: int = 168,
        z_clip: float = 3.0,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="cross_pair_spread",
            category="mean_reversion",
            lookback_d=max(rolling_window // 24, 7),
            enabled=enabled,
        )
        self.rolling_window = rolling_window
        self.z_clip = z_clip
        self._prev_signal: float = 0.0

    def update(self, market_data: dict) -> None:
        closes_a = _extract_closes(market_data["candles_a"])
        closes_b = _extract_closes(market_data["candles_b"])
        timestamps_a = _extract_timestamps(market_data["candles_a"])

        min_len = min(len(closes_a), len(closes_b))
        if min_len < self.rolling_window + 1:
            return

        closes_a = closes_a[-min_len:]
        closes_b = closes_b[-min_len:]

        # Avoid division by zero
        ratio = np.where(closes_b != 0, closes_a / closes_b, np.nan)

        # Rolling mean & std of the ratio
        window_slice = ratio[-self.rolling_window :]
        valid = window_slice[~np.isnan(window_slice)]
        if len(valid) < 2:
            return

        mean = float(np.mean(valid))
        std = float(np.std(valid))
        std = max(std, 1e-12)

        current_ratio = ratio[-1]
        if np.isnan(current_ratio):
            return

        z = (current_ratio - mean) / std
        # Contrarian: negative z-score => ratio is cheap => buy signal
        raw = -z / self.z_clip

        # Track return
        if min_len >= 2 and not np.isnan(ratio[-2]):
            ratio_ret = (ratio[-1] - ratio[-2]) / ratio[-2]
            pnl = self._prev_signal * ratio_ret
            ts = timestamps_a[-1] if timestamps_a else int(time.time())
            self._append_return(ts, pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 2 – Bollinger Z-Score
# ---------------------------------------------------------------------------


class BollingerZScore(BaseSignal):
    """Current price expressed as a z-score relative to Bollinger Bands.

    Positive z => above upper band => overbought => mean-reversion sell.
    Negative z => below lower band => oversold   => mean-reversion buy.
    Signal is the *contrarian* z (flipped sign).
    """

    def __init__(
        self,
        window: int = 20,
        num_std: float = 2.0,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="bollinger_zscore",
            category="mean_reversion",
            lookback_d=max(window // 24, 1) * 2,
            enabled=enabled,
        )
        self.window = window
        self.num_std = num_std
        self._prev_signal: float = 0.0

    def update(self, market_data: dict) -> None:
        candles: list[dict] = market_data["candles"]
        closes = _extract_closes(candles)
        timestamps = _extract_timestamps(candles)

        if len(closes) < self.window + 1:
            return

        window_slice = closes[-self.window :]
        mean = float(np.mean(window_slice))
        std = float(np.std(window_slice))
        std = max(std, 1e-12)

        current = closes[-1]
        z = (current - mean) / std

        # Contrarian signal: flip sign, scale by num_std
        raw = -z / self.num_std

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
# Signal 3 – Funding Rate Mean-Reversion
# ---------------------------------------------------------------------------


class FundingRateMeanReversion(BaseSignal):
    """Extreme perpetual funding rates tend to revert.

    Very positive funding (longs pay shorts) => market too bullish => contrarian sell.
    Very negative funding (shorts pay longs)  => market too bearish => contrarian buy.

    market_data key: "funding_rate" – a list of dicts with "rate" and "timestamp".
    """

    def __init__(
        self,
        lookback: int = 72,
        extreme_threshold: float = 0.001,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="funding_rate_mean_reversion",
            category="mean_reversion",
            lookback_d=max(lookback // 24, 3),
            enabled=enabled,
        )
        self.lookback = lookback
        self.extreme_threshold = extreme_threshold
        self._prev_signal: float = 0.0

    def update(self, market_data: dict) -> None:
        funding_records: list[dict] = market_data["funding_rate"]

        if len(funding_records) < 2:
            return

        rates = np.array([float(r["rate"]) for r in funding_records], dtype=np.float64)
        timestamps = [int(r["timestamp"]) for r in funding_records]

        n = min(self.lookback, len(rates))
        window = rates[-n:]
        mean = float(np.mean(window))
        std = float(np.std(window))
        std = max(std, 1e-12)

        current = rates[-1]
        z = (current - mean) / std

        # Contrarian: extreme positive funding => sell, extreme negative => buy
        raw = -z / 3.0  # scale so +-3 std maps to +-1

        # Return tracking: if the previous signal was correct (price moved in
        # the signal direction after funding extremes), record positive return.
        # We approximate via the funding rate change itself as a proxy.
        if len(rates) >= 2:
            # Funding reversion proxy: did funding revert?
            rate_change = rates[-1] - rates[-2]
            pnl = self._prev_signal * (-rate_change / max(abs(rates[-2]), 1e-9))
            self._append_return(timestamps[-1], pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value
