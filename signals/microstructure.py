import time

import numpy as np

from signals.base import BaseSignal


# ---------------------------------------------------------------------------
# Signal 1 – Orderbook Imbalance
# ---------------------------------------------------------------------------


class OrderbookImbalance(BaseSignal):
    """Bid depth vs ask depth within X% of mid price.

    Positive imbalance (more bids) => buying pressure  => bullish signal.
    Negative imbalance (more asks) => selling pressure  => bearish signal.

    market_data["orderbook"]:
        {
            "bids": [[price, qty], ...],   # sorted descending by price
            "asks": [[price, qty], ...],   # sorted ascending  by price
        }
    """

    def __init__(
        self,
        depth_pct: float = 2.0,
        ema_alpha: float = 0.3,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="orderbook_imbalance",
            category="microstructure",
            lookback_d=1,
            enabled=enabled,
        )
        self.depth_pct = depth_pct
        self.ema_alpha = ema_alpha
        self._prev_signal: float = 0.0
        self._ema: float = 0.0
        self._initialized_ema: bool = False

    def update(self, market_data: dict) -> None:
        ob = market_data["orderbook"]
        bids: list[list[float]] = ob["bids"]
        asks: list[list[float]] = ob["asks"]

        if not bids or not asks:
            return

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid = (best_bid + best_ask) / 2.0

        if mid <= 0:
            return

        lower_bound = mid * (1.0 - self.depth_pct / 100.0)
        upper_bound = mid * (1.0 + self.depth_pct / 100.0)

        bid_depth = sum(float(qty) for price, qty in bids if float(price) >= lower_bound)
        ask_depth = sum(float(qty) for price, qty in asks if float(price) <= upper_bound)

        total = bid_depth + ask_depth
        if total <= 0:
            return

        imbalance = (bid_depth - ask_depth) / total  # range [-1, 1]

        # EMA smoothing
        if not self._initialized_ema:
            self._ema = imbalance
            self._initialized_ema = True
        else:
            self._ema = self.ema_alpha * imbalance + (1.0 - self.ema_alpha) * self._ema

        # Return tracking using mid-price change
        timestamp = int(market_data.get("timestamp", time.time()))
        prev_mid = market_data.get("prev_mid")
        if prev_mid is not None and float(prev_mid) > 0:
            mid_ret = (mid - float(prev_mid)) / float(prev_mid)
            pnl = self._prev_signal * mid_ret
            self._append_return(timestamp, pnl)

        self._prev_signal = self._clip_output(self._ema)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 2 – Effective Spread
# ---------------------------------------------------------------------------


class EffectiveSpread(BaseSignal):
    """Track effective spread expansion / compression.

    Widening spread => liquidity draining => risk-off => bearish.
    Narrowing spread => healthy liquidity  => risk-on  => bullish.

    market_data["trades"]:
        list of {"price": float, "side": "buy"|"sell", "timestamp": int}
    market_data["mid_price"]: current mid price
    """

    def __init__(
        self,
        window: int = 100,
        history_len: int = 500,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="effective_spread",
            category="microstructure",
            lookback_d=1,
            enabled=enabled,
        )
        self.window = window
        self.history_len = history_len
        self._prev_signal: float = 0.0
        self._spread_history: list[float] = []

    def update(self, market_data: dict) -> None:
        trades: list[dict] = market_data["trades"]
        mid_price = float(market_data["mid_price"])

        if not trades or mid_price <= 0:
            return

        # Effective spread = 2 * |trade_price - mid| / mid  (in bps)
        spreads: list[float] = []
        for t in trades[-self.window :]:
            price = float(t["price"])
            eff = 2.0 * abs(price - mid_price) / mid_price * 10000.0  # bps
            spreads.append(eff)

        current_spread = float(np.mean(spreads))
        self._spread_history.append(current_spread)

        history = np.array(self._spread_history[-self.history_len :])

        if len(history) < 2:
            return

        mean_spread = float(np.mean(history))
        std_spread = float(np.std(history))
        std_spread = max(std_spread, 1e-9)

        z = (current_spread - mean_spread) / std_spread

        # Wide spread => bearish signal (contrarian: liquidity drying up)
        raw = -z / 3.0

        timestamp = int(trades[-1].get("timestamp", time.time()))
        if len(self._spread_history) >= 2:
            # We don't have direct price return here, use spread-change proxy
            prev_spread = self._spread_history[-2]
            spread_change = (current_spread - prev_spread) / max(prev_spread, 1e-9)
            pnl = self._prev_signal * (-spread_change)  # wider spread = bad for longs
            self._append_return(timestamp, pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value


# ---------------------------------------------------------------------------
# Signal 3 – VPIN (Volume-Synchronized Probability of Informed Trading)
# ---------------------------------------------------------------------------


class VPIN(BaseSignal):
    """Volume-Synchronized Probability of Informed Trading.

    High VPIN => high probability of informed trading => imminent large move.
    Signal is negative (reduce exposure) when VPIN is elevated.

    market_data["trades"]:
        list of {"price": float, "volume": float, "side": "buy"|"sell",
                 "timestamp": int}
    """

    def __init__(
        self,
        bucket_volume: float = 1.0,
        n_buckets: int = 50,
        history_len: int = 200,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            name="vpin",
            category="microstructure",
            lookback_d=1,
            enabled=enabled,
        )
        self.bucket_volume = bucket_volume
        self.n_buckets = n_buckets
        self.history_len = history_len
        self._prev_signal: float = 0.0
        self._buckets: list[tuple[float, float]] = []  # (buy_vol, sell_vol) per bucket
        self._current_bucket_buy: float = 0.0
        self._current_bucket_sell: float = 0.0
        self._current_bucket_total: float = 0.0
        self._vpin_history: list[float] = []

    def _finalize_bucket(self) -> None:
        self._buckets.append((self._current_bucket_buy, self._current_bucket_sell))
        # Keep only recent buckets
        if len(self._buckets) > self.n_buckets * 3:
            self._buckets = self._buckets[-self.n_buckets * 2 :]
        self._current_bucket_buy = 0.0
        self._current_bucket_sell = 0.0
        self._current_bucket_total = 0.0

    def update(self, market_data: dict) -> None:
        trades: list[dict] = market_data["trades"]

        if not trades:
            return

        for t in trades:
            vol = float(t["volume"])
            side = t.get("side", "buy")

            if side == "buy":
                self._current_bucket_buy += vol
            else:
                self._current_bucket_sell += vol
            self._current_bucket_total += vol

            # When bucket is full, finalize it
            while self._current_bucket_total >= self.bucket_volume:
                overflow = self._current_bucket_total - self.bucket_volume
                # Proportionally split the overflow
                if self._current_bucket_total > 0:
                    ratio = self.bucket_volume / (self._current_bucket_total)
                else:
                    ratio = 1.0

                buy_in = self._current_bucket_buy * ratio
                sell_in = self._current_bucket_sell * ratio
                remaining_buy = self._current_bucket_buy - buy_in
                remaining_sell = self._current_bucket_sell - sell_in

                self._current_bucket_buy = buy_in
                self._current_bucket_sell = sell_in
                self._current_bucket_total = self.bucket_volume
                self._finalize_bucket()

                self._current_bucket_buy = remaining_buy
                self._current_bucket_sell = remaining_sell
                self._current_bucket_total = overflow

        # Compute VPIN if we have enough buckets
        if len(self._buckets) < self.n_buckets:
            return

        recent = self._buckets[-self.n_buckets :]
        order_imbalances = [abs(b - s) for b, s in recent]
        vpin = float(np.sum(order_imbalances)) / (self.n_buckets * self.bucket_volume)
        self._vpin_history.append(vpin)

        # Percentile rank
        history = np.array(self._vpin_history[-self.history_len :])
        pct = float(np.sum(history <= vpin) / len(history) * 100.0)

        # High VPIN => danger => reduce exposure
        if pct >= 80.0:
            raw = -1.0
        elif pct <= 20.0:
            raw = 0.5  # Low VPIN => calm market => mild positive
        else:
            raw = 0.5 - 1.5 * (pct - 20.0) / 60.0

        timestamp = int(trades[-1].get("timestamp", time.time()))
        if len(self._vpin_history) >= 2:
            vpin_change = self._vpin_history[-1] - self._vpin_history[-2]
            pnl = self._prev_signal * (-vpin_change)
            self._append_return(timestamp, pnl)

        self._prev_signal = self._clip_output(raw)
        self._current_value = self._prev_signal
        self._last_update = time.time()

    def current_output(self) -> float:
        return self._current_value
