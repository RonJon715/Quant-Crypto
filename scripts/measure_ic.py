"""
Compute Information Coefficient (IC) for each signal over historical data.

IC = correlation between signal forecast and subsequent realized returns.
A signal must have IC > 0 over at least 200 observations to be included.

Usage:
    python -m scripts.measure_ic --db candles.db
"""

import argparse
import asyncio
import logging

import numpy as np
import pandas as pd
from scipy import stats

from data.candle_store import CandleStore

logger = logging.getLogger(__name__)


def compute_ic(
    signal_values: np.ndarray,
    forward_returns: np.ndarray,
    method: str = "spearman",
) -> tuple[float, float]:
    """
    Compute Information Coefficient between signal values and forward returns.

    Args:
        signal_values: Array of signal predictions at each time step.
        forward_returns: Array of realized returns in the next period.
        method: "spearman" (rank) or "pearson" (linear).

    Returns:
        (ic, p_value) tuple.
    """
    mask = np.isfinite(signal_values) & np.isfinite(forward_returns)
    sv = signal_values[mask]
    fr = forward_returns[mask]

    if len(sv) < 30:
        return 0.0, 1.0

    if method == "spearman":
        ic, pval = stats.spearmanr(sv, fr)
    else:
        ic, pval = stats.pearsonr(sv, fr)

    return float(ic), float(pval)


def compute_ic_rolling(
    signal_values: np.ndarray,
    forward_returns: np.ndarray,
    window: int = 60,
    method: str = "spearman",
) -> pd.Series:
    """Compute rolling IC to check stability over time."""
    n = len(signal_values)
    ics = []
    for i in range(window, n):
        sv = signal_values[i - window : i]
        fr = forward_returns[i - window : i]
        ic, _ = compute_ic(sv, fr, method)
        ics.append(ic)
    return pd.Series(ics)


def analyze_signal_quality(
    signal_values: np.ndarray,
    forward_returns: np.ndarray,
    signal_name: str,
) -> dict:
    """Full quality analysis for a single signal."""
    ic_spearman, p_spearman = compute_ic(signal_values, forward_returns, "spearman")
    ic_pearson, p_pearson = compute_ic(signal_values, forward_returns, "pearson")

    rolling_ic = compute_ic_rolling(signal_values, forward_returns)
    ic_mean = rolling_ic.mean() if len(rolling_ic) > 0 else 0.0
    ic_std = rolling_ic.std() if len(rolling_ic) > 0 else 0.0
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0.0
    pct_positive = (rolling_ic > 0).mean() if len(rolling_ic) > 0 else 0.0

    n_obs = int(np.isfinite(signal_values).sum())

    result = {
        "signal": signal_name,
        "n_observations": n_obs,
        "ic_spearman": round(ic_spearman, 4),
        "p_spearman": round(p_spearman, 4),
        "ic_pearson": round(ic_pearson, 4),
        "p_pearson": round(p_pearson, 4),
        "rolling_ic_mean": round(ic_mean, 4),
        "rolling_ic_std": round(ic_std, 4),
        "ic_information_ratio": round(ic_ir, 4),
        "pct_positive_ic": round(pct_positive, 4),
        "passes_threshold": ic_spearman > 0 and n_obs >= 200 and p_spearman < 0.05,
    }

    return result


def generate_synthetic_signal(
    prices: np.ndarray, lookback: int = 24, noise_level: float = 0.5
) -> np.ndarray:
    """Generate a synthetic momentum signal for testing IC measurement."""
    n = len(prices)
    returns = np.diff(np.log(prices))
    signal = np.full(n, np.nan)

    for i in range(lookback, n):
        momentum = returns[i - lookback : i].mean()
        noise = np.random.normal(0, noise_level * abs(momentum) + 1e-6)
        signal[i] = momentum + noise

    return signal


async def main_async(db_path: str, pairs: list[str], timeframe: str):
    """Run IC measurement on synthetic signals over historical candle data."""
    store = CandleStore(db_path)
    await store.init_db()

    for pair in pairs:
        logger.info("Measuring IC for %s...", pair)
        candles = await store.get_candles(pair, timeframe, 0, int(1e15))

        if len(candles) < 250:
            logger.warning("Insufficient data for %s: %d candles", pair, len(candles))
            continue

        prices = np.array([c.close for c in candles])
        forward_returns = np.zeros(len(prices))
        forward_returns[:-1] = np.diff(np.log(prices))
        forward_returns[-1] = np.nan

        # Test multiple momentum lookbacks
        for lookback in [6, 12, 24, 48, 96]:
            signal_name = f"momentum_{lookback}h_{pair}"
            signal = generate_synthetic_signal(prices, lookback, noise_level=0.3)

            result = analyze_signal_quality(signal, forward_returns, signal_name)

            status = "PASS" if result["passes_threshold"] else "FAIL"
            logger.info(
                "[%s] %s: IC=%.4f (p=%.4f), n=%d, rolling_mean=%.4f",
                status,
                signal_name,
                result["ic_spearman"],
                result["p_spearman"],
                result["n_observations"],
                result["rolling_ic_mean"],
            )


def main():
    parser = argparse.ArgumentParser(description="Measure IC for trading signals")
    parser.add_argument("--db", default="candles.db", help="Candle store path")
    parser.add_argument(
        "--pairs",
        nargs="+",
        default=["BTC-USD", "ETH-USD", "SOL-USD"],
    )
    parser.add_argument("--timeframe", default="1h")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(main_async(args.db, args.pairs, args.timeframe))


if __name__ == "__main__":
    main()
