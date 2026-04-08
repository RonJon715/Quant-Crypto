import time

import numpy as np

from signals.base import BaseSignal


# ---------------------------------------------------------------------------
# Signal 1 – Fear & Greed Index (Contrarian)
# ---------------------------------------------------------------------------


class FearGreedSignal(BaseSignal):
    """Contrarian signal based on the Crypto Fear & Greed Index (0-100).

    Extreme fear  (< 20) => market oversold => bullish  => +1
    Extreme greed (> 80) => market euphoric => bearish  => -1
    Neutral zone         => linear interpolation

    market_data["fear_greed_index"]: list of dicts with "value" (0-100) and "timestamp"
    """

    def __init__(
        self,
        fear_threshold: float = 20.0,
        greed_threshold: float = 80.0,
        ema_alpha: float = 0.2,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="fear_greed_signal",
            category="sentiment",
            lookback_d=30,
            enabled=enabled,
        )
        self.fear_threshold = fear_threshold
        self.greed_threshold = greed_threshold
        self.ema_alpha = ema_alpha
        self._prev_signal: float = 0.0
        self._ema: float = 50.0
        self._initialized_ema: bool = False

    def update(self, market_data: dict) -> None:
        fg_records: list[dict] = market_data["fear_greed_index"]

        if not fg_records:
            return

        current_value = float(fg_records[-1]["value"])
        timestamp = int(fg_records[-1]["timestamp"])

        # Clamp to [0, 100]
        current_value = max(0.0, min(100.0, current_value))

        # EMA smoothing to reduce noise
        if not self._initialized_ema:
            self._ema = current_value
            self._initialized_ema = True
        else:
            self._ema = self.ema_alpha * current_value + (1.0 - self.ema_alpha) * self._ema

        smoothed = self._ema

        # Map to signal: fear => bullish, greed => bearish
        if smoothed <= self.fear_threshold:
            # Extreme fear: strong buy
            raw = 1.0
        elif smoothed >= self.greed_threshold:
            # Extreme greed: strong sell
            raw = -1.0
        else:
            # Linear interpolation: fear_threshold -> +1, greed_threshold -> -1
            raw = 1.0 - 2.0 * (smoothed - self.fear_threshold) / (
                self.greed_threshold - self.fear_threshold
            )

        # Return tracking
        if len(fg_records) >= 2:
            # Use index change as proxy (contrarian: if fear dropped, price likely rose)
            prev_value = float(fg_records[-2]["value"])
            index_change = current_value - prev_value
            # Contrarian return: signal * (-index_change) normalized
            pnl = self._prev_signal * (-index_change / 100.0)
            self._append_return(timestamp, pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 2 – Social Volume
# ---------------------------------------------------------------------------


class SocialVolume(BaseSignal):
    """Social media mention velocity spikes.

    Abnormally high social volume can indicate retail FOMO (bearish contrarian)
    or genuine interest. We use a z-score approach: extreme spikes are
    contrarian bearish, while moderate increases are mildly bullish.

    market_data["social_volume"]: list of dicts with "value" and "timestamp"
        value = number of mentions / posts in the period
    """

    def __init__(
        self,
        lookback: int = 168,
        spike_z: float = 2.5,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="social_volume",
            category="sentiment",
            lookback_d=max(lookback // 24, 7),
            enabled=enabled,
        )
        self.lookback = lookback
        self.spike_z = spike_z
        self._prev_signal: float = 0.0
        self._volume_history: list[float] = []

    def update(self, market_data: dict) -> None:
        sv_records: list[dict] = market_data["social_volume"]

        if not sv_records:
            return

        current_volume = float(sv_records[-1]["value"])
        timestamp = int(sv_records[-1]["timestamp"])
        self._volume_history.append(current_volume)

        window = np.array(self._volume_history[-self.lookback :])
        if len(window) < 10:
            return

        mean = float(np.mean(window))
        std = float(np.std(window))
        std = max(std, 1e-9)

        z = (current_volume - mean) / std

        if z >= self.spike_z:
            # Extreme spike => retail FOMO => contrarian bearish
            raw = -1.0
        elif z <= -self.spike_z:
            # Extreme low volume => apathy => contrarian bullish
            raw = 0.5
        elif z > 0:
            # Moderate increase: mildly bullish up to spike threshold
            # then transitions to bearish
            if z < 1.0:
                raw = z * 0.3  # mild bullish
            else:
                # Between 1.0 and spike_z: linearly transition from mild bullish to bearish
                raw = 0.3 - (z - 1.0) / (self.spike_z - 1.0) * 1.3
        else:
            # Below average but not extreme
            raw = -z * 0.2  # mildly bullish on declining social volume

        # Return tracking
        if len(self._volume_history) >= 2:
            vol_change = (current_volume - self._volume_history[-2]) / max(
                self._volume_history[-2], 1e-9
            )
            pnl = self._prev_signal * (-vol_change * 0.01)
            self._append_return(timestamp, pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value
