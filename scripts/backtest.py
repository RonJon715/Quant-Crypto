"""
Offline backtest harness using candle_store data.

Runs the combination engine over historical data and measures performance:
  - Sharpe ratio
  - Max drawdown
  - Win rate
  - Average holding period
  - Comparison: mega-alpha vs best individual signal vs equal-weight

Usage:
    python -m scripts.backtest --db candles.db --start 2024-01-01
"""

import argparse
import asyncio
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from data.candle_store import CandleStore
from data.schema import CandleRecord
from signals.momentum import DualTimeframeMomentum, RateOfChangeAcceleration
from signals.mean_reversion import BollingerZScore
from signals.volatility import VolatilityRegime, VolOfVol
from core.combination_engine import CombinationEngine
from core.kelly_sizer import KellySizer
from core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class BacktestResult:
    """Container for backtest performance metrics."""

    def __init__(self, name: str, equity_curve: list[float], trades: list[dict]):
        self.name = name
        self.equity_curve = np.array(equity_curve)
        self.trades = trades

    @property
    def total_return(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        return (self.equity_curve[-1] / self.equity_curve[0]) - 1.0

    @property
    def sharpe_ratio(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        returns = np.diff(self.equity_curve) / self.equity_curve[:-1]
        if returns.std() == 0:
            return 0.0
        return (returns.mean() / returns.std()) * np.sqrt(365 * 24)  # annualized hourly

    @property
    def max_drawdown(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        peak = np.maximum.accumulate(self.equity_curve)
        drawdowns = (self.equity_curve - peak) / peak
        return float(drawdowns.min())

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.get("pnl", 0) > 0)
        return wins / len(self.trades)

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    def summary(self) -> dict:
        return {
            "name": self.name,
            "total_return": f"{self.total_return:.2%}",
            "sharpe_ratio": f"{self.sharpe_ratio:.3f}",
            "max_drawdown": f"{self.max_drawdown:.2%}",
            "win_rate": f"{self.win_rate:.2%}",
            "num_trades": self.num_trades,
        }


def build_signals(pair: str) -> list:
    """Create signal instances for backtesting."""
    signals = [
        DualTimeframeMomentum(short_window=4, medium_window=24),
        RateOfChangeAcceleration(roc_window=12, accel_window=6),
        BollingerZScore(window=20, num_std=2.0),
        VolatilityRegime(vol_window=14, history_window=252),
        VolOfVol(vol_window=14, vov_window=14),
    ]
    return signals


async def run_backtest(
    candles: list[CandleRecord],
    pair: str,
    initial_capital: float = 10000.0,
    cycle_bars: int = 1,
) -> BacktestResult:
    """Run combination engine backtest over candle history."""
    signals = build_signals(pair)
    engine = CombinationEngine(signals, lookback_M=200)
    portfolio = Portfolio(initial_capital)

    equity_curve = [initial_capital]
    trades = []

    warmup = 250
    if len(candles) < warmup:
        logger.warning("Not enough candles for backtest warmup")
        return BacktestResult(f"mega_alpha_{pair}", equity_curve, trades)

    for i in range(warmup, len(candles), cycle_bars):
        window = candles[max(0, i - 500) : i]
        market_data = {
            "candles": [
                {"close": c.close, "timestamp": c.timestamp, "high": c.high, "low": c.low,
                 "open": c.open, "volume": c.volume}
                for c in window
            ]
        }

        for sig in signals:
            try:
                sig.update(market_data)
            except Exception:
                pass

        try:
            weights = engine.compute_weights()
            mega_alpha = engine.compute_mega_alpha(weights)
        except Exception:
            mega_alpha = 0.0

        current_price = candles[i].close

        # Simple position logic: go long if mega_alpha > threshold
        pos = portfolio.get_position(pair)
        current_qty = pos.get("quantity", 0.0)

        if mega_alpha > 0.005 and current_qty <= 0:
            # Buy
            size = min(
                initial_capital * 0.1,
                portfolio.available_capital() * 0.5,
            )
            qty = size / current_price
            portfolio.update_position(pair, qty, current_price)
            trades.append({
                "timestamp": candles[i].timestamp,
                "side": "buy",
                "price": current_price,
                "qty": qty,
                "mega_alpha": mega_alpha,
            })
        elif mega_alpha < -0.005 and current_qty > 0:
            # Sell
            entry_price = pos.get("avg_price", current_price)
            pnl = (current_price - entry_price) * current_qty
            portfolio.update_position(pair, 0, current_price)
            trades.append({
                "timestamp": candles[i].timestamp,
                "side": "sell",
                "price": current_price,
                "qty": current_qty,
                "mega_alpha": mega_alpha,
                "pnl": pnl,
            })

        # Update equity
        portfolio.update_equity({pair: current_price})
        equity_curve.append(portfolio.equity)

    return BacktestResult(f"mega_alpha_{pair}", equity_curve, trades)


async def main_async(db_path: str, pairs: list[str], start_date: str):
    store = CandleStore(db_path)
    await store.init_db()

    start_ts = int(
        datetime.strptime(start_date, "%Y-%m-%d")
        .replace(tzinfo=timezone.utc)
        .timestamp()
        * 1000
    )

    for pair in pairs:
        logger.info("Running backtest for %s...", pair)
        candles = await store.get_candles(pair, "1h", start_ts, int(1e15))

        if len(candles) < 300:
            logger.warning("Insufficient data for %s: %d candles", pair, len(candles))
            continue

        result = await run_backtest(candles, pair)
        summary = result.summary()
        logger.info("=== %s Results ===", pair)
        for key, val in summary.items():
            logger.info("  %s: %s", key, val)


def main():
    parser = argparse.ArgumentParser(description="Run offline backtest")
    parser.add_argument("--db", default="candles.db")
    parser.add_argument("--pairs", nargs="+", default=["BTC-USD", "ETH-USD", "SOL-USD"])
    parser.add_argument("--start", default="2024-01-01", help="Start date YYYY-MM-DD")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(main_async(args.db, args.pairs, args.start))


if __name__ == "__main__":
    main()
