from abc import ABC, abstractmethod
import pandas as pd
import time


class BaseSignal(ABC):
    """Abstract base class for all trading signals."""

    def __init__(
        self,
        name: str,
        category: str,
        lookback_d: int,
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.category = category
        self.lookback_d = lookback_d
        self.enabled = enabled
        self._returns: list[float] = []
        self._timestamps: list[int] = []
        self._last_update: float = 0.0
        self._current_value: float = 0.0

    @abstractmethod
    def update(self, market_data: dict) -> None:
        pass

    @abstractmethod
    def current_output(self) -> float:
        pass

    def get_returns(self, periods: int) -> pd.Series:
        n = min(periods, len(self._returns))
        return pd.Series(self._returns[-n:], index=self._timestamps[-n:])

    def is_stale(self, max_age_seconds: float = 1800.0) -> bool:
        return (time.time() - self._last_update) > max_age_seconds

    def _append_return(self, timestamp: int, ret: float) -> None:
        self._returns.append(ret)
        self._timestamps.append(timestamp)

    def _clip_output(self, value: float) -> float:
        return max(-1.0, min(1.0, value))
