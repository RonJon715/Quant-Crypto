import time

import numpy as np

from signals.base import BaseSignal


# ---------------------------------------------------------------------------
# Signal 1 – Exchange Net Flow
# ---------------------------------------------------------------------------


class ExchangeNetFlow(BaseSignal):
    """Large net inflows to exchanges signal selling pressure.

    Positive net flow (coins entering exchanges) => bearish (-1).
    Negative net flow (coins leaving exchanges)  => accumulation (+1).

    market_data["exchange_net_flow"]: list of dicts with "value" and "timestamp"
        value > 0 => net inflow to exchanges
        value < 0 => net outflow from exchanges
    """

    def __init__(
        self,
        lookback: int = 30,
        z_clip: float = 3.0,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="exchange_net_flow",
            category="onchain",
            lookback_d=lookback,
            enabled=enabled,
        )
        self.lookback = lookback
        self.z_clip = z_clip
        self._prev_signal: float = 0.0
        self._flow_history: list[float] = []

    def update(self, market_data: dict) -> None:
        flow_records: list[dict] = market_data["exchange_net_flow"]

        if not flow_records:
            return

        values = np.array([float(r["value"]) for r in flow_records], dtype=np.float64)
        timestamps = [int(r["timestamp"]) for r in flow_records]

        current_flow = values[-1]
        self._flow_history.append(float(current_flow))

        window = np.array(self._flow_history[-self.lookback :])
        if len(window) < 2:
            return

        mean = float(np.mean(window))
        std = float(np.std(window))
        std = max(std, 1e-9)

        z = (current_flow - mean) / std
        # Inflows (positive z) => bearish, outflows (negative z) => bullish
        raw = -z / self.z_clip

        # Return tracking
        if len(values) >= 2:
            # Proxy: if signal predicted direction of flow correctly
            flow_change = values[-1] - values[-2]
            pnl = self._prev_signal * (-float(flow_change) / max(abs(float(values[-2])), 1e-9))
            self._append_return(timestamps[-1], pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 2 – Stablecoin Supply Ratio
# ---------------------------------------------------------------------------


class StablecoinSupplyRatio(BaseSignal):
    """Growing stablecoin supply relative to BTC market cap = dry powder = bullish.

    A declining ratio means stablecoins are growing faster than BTC price,
    indicating capital is available to rotate into BTC.

    market_data["stablecoin_ratio"]: list of dicts with "value" and "timestamp"
        value = BTC market cap / total stablecoin supply
        Lower value => more dry powder relative to BTC => bullish
    """

    def __init__(
        self,
        lookback: int = 90,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="stablecoin_supply_ratio",
            category="onchain",
            lookback_d=lookback,
            enabled=enabled,
        )
        self.lookback = lookback
        self._prev_signal: float = 0.0
        self._ratio_history: list[float] = []

    def update(self, market_data: dict) -> None:
        ratio_records: list[dict] = market_data["stablecoin_ratio"]

        if not ratio_records:
            return

        values = np.array([float(r["value"]) for r in ratio_records], dtype=np.float64)
        timestamps = [int(r["timestamp"]) for r in ratio_records]

        current = values[-1]
        self._ratio_history.append(float(current))

        window = np.array(self._ratio_history[-self.lookback :])
        if len(window) < 2:
            return

        mean = float(np.mean(window))
        std = float(np.std(window))
        std = max(std, 1e-9)

        z = (current - mean) / std
        # Lower ratio => more dry powder => bullish (invert z)
        raw = -z / 3.0

        # Return tracking via ratio change
        if len(values) >= 2 and values[-2] != 0:
            ratio_change = (values[-1] - values[-2]) / abs(values[-2])
            pnl = self._prev_signal * (-float(ratio_change))
            self._append_return(timestamps[-1], pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 3 – Whale Movement
# ---------------------------------------------------------------------------


class WhaleMovement(BaseSignal):
    """Large on-chain transactions signal.

    Clusters of large transactions (whales moving coins) can signal
    imminent volatility. Direction inferred from destination:
    - to exchange => selling pressure => bearish
    - from exchange => accumulation => bullish

    market_data["whale_transactions"]: list of dicts:
        {"amount": float, "direction": "to_exchange"|"from_exchange",
         "timestamp": int}
    """

    def __init__(
        self,
        amount_threshold: float = 100.0,
        decay_alpha: float = 0.1,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="whale_movement",
            category="onchain",
            lookback_d=7,
            enabled=enabled,
        )
        self.amount_threshold = amount_threshold
        self.decay_alpha = decay_alpha
        self._prev_signal: float = 0.0
        self._ema: float = 0.0
        self._initialized_ema: bool = False

    def update(self, market_data: dict) -> None:
        transactions: list[dict] = market_data["whale_transactions"]

        if not transactions:
            return

        # Filter significant transactions
        net_flow: float = 0.0
        total_volume: float = 0.0

        for tx in transactions:
            amount = float(tx["amount"])
            if amount < self.amount_threshold:
                continue

            direction = tx.get("direction", "to_exchange")
            total_volume += amount

            if direction == "to_exchange":
                net_flow -= amount  # selling pressure
            else:
                net_flow += amount  # accumulation

        if total_volume <= 0:
            return

        # Normalize by total volume
        normalized = net_flow / total_volume  # range [-1, 1]

        # EMA smoothing
        if not self._initialized_ema:
            self._ema = normalized
            self._initialized_ema = True
        else:
            self._ema = self.decay_alpha * normalized + (1.0 - self.decay_alpha) * self._ema

        timestamp = int(transactions[-1].get("timestamp", time.time()))

        # Return tracking
        if self._returns:
            pnl = self._prev_signal * normalized * 0.01  # scaled proxy
            self._append_return(timestamp, pnl)
        else:
            self._append_return(timestamp, 0.0)

        self._prev_signal = self._clip_output(self._ema)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value
