"""
Alpha Combination Crypto Trading Bot — Main Entry Point.

Runs the main loop:
  1. Collect data from providers
  2. Update all signals
  3. Run combination engine (11-step procedure)
  4. Calculate edge per asset
  5. Size positions via empirical Kelly
  6. Execute via VWAP limit orders on Coinbase
  7. Journal everything

Usage:
    python main.py                    # Live mode (sandbox by default)
    python main.py --paper            # Paper trading (log orders, don't submit)
    python main.py --cycle-once       # Run single cycle and exit
"""

import asyncio
import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

import yaml

from core.combination_engine import CombinationEngine
from core.kelly_sizer import KellySizer
from core.portfolio import Portfolio
from data.candle_store import CandleStore
from data.orderbook_buffer import OrderbookBuffer
from data.trade_tape import TradeTape
from exchange.rest_client import CoinbaseRestClient
from exchange.ws_client import CoinbaseWebSocket
from exchange.executor import VWAPExecutor
from monitoring.journal import TradeJournal
from monitoring.dashboard import Dashboard
from monitoring.alerts import AlertManager
from signals.momentum import DualTimeframeMomentum, RateOfChangeAcceleration, CrossAssetMomentum
from signals.mean_reversion import BollingerZScore, CrossPairSpread, FundingRateMeanReversion
from signals.volatility import VolatilityRegime, VolOfVol
from signals.onchain import ExchangeNetFlow, StablecoinSupplyRatio
from signals.sentiment import FearGreedSignal
from signals.macro import DXYCorrelation, M2MoneySupply

logger = logging.getLogger("alpha_bot")

# Global shutdown flag
_shutdown = False


def handle_signal(signum, frame):
    global _shutdown
    logger.info("Received signal %d, shutting down gracefully...", signum)
    _shutdown = True


def load_config(config_path: str = "config/settings.yaml") -> dict:
    """Load configuration, overlaying environment variables."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Override with environment variables
    config["exchange"]["api_key"] = os.environ.get(
        "COINBASE_API_KEY", config["exchange"]["api_key"]
    )
    config["exchange"]["api_secret"] = os.environ.get(
        "COINBASE_API_SECRET", config["exchange"]["api_secret"]
    )

    for provider in ["cryptocompare", "glassnode", "whale_alert", "tardis", "lunarcrush"]:
        env_key = f"{provider.upper()}_API_KEY"
        if provider in config.get("data_providers", {}):
            config["data_providers"][provider]["api_key"] = os.environ.get(
                env_key, config["data_providers"][provider].get("api_key", "")
            )

    config["data_providers"]["fred"]["api_key"] = os.environ.get(
        "FRED_API_KEY", config["data_providers"]["fred"].get("api_key", "")
    )

    return config


def build_signals(config: dict, config_dir: str = "config") -> list:
    """Instantiate all enabled signals from configuration."""
    signals_config_path = os.path.join(config_dir, "signals.yaml")
    with open(signals_config_path) as f:
        sig_config = yaml.safe_load(f)

    signals = []
    signal_defs = sig_config.get("signals", {})

    for sig_name, sig_params in signal_defs.items():
        if not sig_params.get("enabled", False):
            continue

        try:
            if sig_name == "momentum_short":
                signals.append(DualTimeframeMomentum(
                    short_window=sig_params.get("short_window", 4),
                    medium_window=sig_params.get("medium_window", 24),
                ))
            elif sig_name == "momentum_roc":
                signals.append(RateOfChangeAcceleration(
                    roc_window=sig_params.get("window", 12),
                    accel_window=6,
                ))
            elif sig_name == "cross_asset_momentum":
                signals.append(CrossAssetMomentum(
                    btc_roc_window=12,
                    alt_roc_window=12,
                ))
            elif sig_name == "bollinger_zscore":
                signals.append(BollingerZScore(
                    window=sig_params.get("bollinger_window", 20),
                    num_std=sig_params.get("num_std", 2.0),
                ))
            elif sig_name == "cross_pair_spread":
                signals.append(CrossPairSpread(
                    rolling_window=sig_params.get("rolling_window", 720),
                ))
            elif sig_name == "funding_rate":
                signals.append(FundingRateMeanReversion())
            elif sig_name == "vol_regime":
                signals.append(VolatilityRegime(
                    vol_window=14,
                    history_window=252,
                ))
            elif sig_name == "vol_of_vol":
                signals.append(VolOfVol(
                    vol_window=14,
                    vov_window=14,
                ))
            elif sig_name == "exchange_net_flow":
                signals.append(ExchangeNetFlow())
            elif sig_name == "stablecoin_ratio":
                signals.append(StablecoinSupplyRatio())
            elif sig_name == "fear_greed":
                signals.append(FearGreedSignal())
            elif sig_name == "dxy_correlation":
                signals.append(DXYCorrelation())
            elif sig_name == "m2_money_supply":
                signals.append(M2MoneySupply())
            else:
                logger.debug("Unknown signal: %s (skipping)", sig_name)
        except Exception as e:
            logger.error("Failed to create signal %s: %s", sig_name, e)

    logger.info("Built %d signals", len(signals))
    return signals


async def collect_data(
    config: dict,
    rest_client: CoinbaseRestClient,
    candle_store: CandleStore,
    assets: list[str],
) -> dict[str, dict]:
    """Fetch latest data for all assets. Returns market_data dict per asset."""
    market_data = {}

    for asset in assets:
        try:
            # Fetch recent candles from Coinbase
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - (500 * 3600 * 1000)  # ~500 hours back

            # Try local store first
            candles = await candle_store.get_candles(asset, "1h", start_ms, now_ms)

            if len(candles) < 100:
                # Fetch from Coinbase REST
                try:
                    raw = await rest_client.get_candles(
                        asset, int(start_ms / 1000), int(now_ms / 1000)
                    )
                    candle_dicts = [
                        {
                            "timestamp": int(c.get("start", 0)) * 1000,
                            "open": float(c.get("open", 0)),
                            "high": float(c.get("high", 0)),
                            "low": float(c.get("low", 0)),
                            "close": float(c.get("close", 0)),
                            "volume": float(c.get("volume", 0)),
                        }
                        for c in raw
                    ]
                except Exception as e:
                    logger.warning("Failed to fetch candles from Coinbase for %s: %s", asset, e)
                    candle_dicts = []
            else:
                candle_dicts = [
                    {
                        "timestamp": c.timestamp,
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                    }
                    for c in candles
                ]

            market_data[asset] = {"candles": candle_dicts}

        except Exception as e:
            logger.error("Data collection failed for %s: %s", asset, e)
            market_data[asset] = {"candles": []}

    return market_data


async def run_cycle(
    config: dict,
    signals: list,
    engine: CombinationEngine,
    kelly: KellySizer,
    portfolio: Portfolio,
    executor: VWAPExecutor,
    rest_client: CoinbaseRestClient,
    candle_store: CandleStore,
    journal: TradeJournal,
    alert_mgr: AlertManager,
    assets: list[str],
    paper_mode: bool,
):
    """Execute one full trading cycle."""
    cycle_start = time.time()
    logger.info("=== Cycle Start ===")

    # Step 1: Collect data
    market_data = await collect_data(config, rest_client, candle_store, assets)

    # Step 2: Update signals
    enabled_signals = [s for s in signals if s.enabled and not s.is_stale()]
    min_required = config["engine"]["min_signals_required"]

    for sig in signals:
        for asset in assets:
            if asset in market_data and market_data[asset]["candles"]:
                try:
                    sig.update(market_data[asset])
                except Exception as e:
                    logger.warning("Signal %s update failed: %s", sig.name, e)

    active_signals = [s for s in signals if s.enabled and not s.is_stale()]
    if len(active_signals) < min_required:
        logger.warning(
            "Only %d active signals (need %d), skipping cycle",
            len(active_signals),
            min_required,
        )
        return

    # Step 3: Run combination engine
    try:
        weights = engine.compute_weights()
    except Exception as e:
        logger.error("Combination engine failed: %s", e)
        return

    # Step 4-5: Calculate edge and size positions per asset
    for asset in assets:
        try:
            mega_alpha = engine.compute_mega_alpha(weights)
        except Exception as e:
            logger.warning("Mega alpha computation failed for %s: %s", asset, e)
            continue

        # Determine minimum edge threshold
        if asset == "BTC-USD":
            min_edge_bps = config["engine"]["min_edge_threshold_bps"]
        else:
            min_edge_bps = config["engine"]["min_edge_threshold_alt_bps"]
        min_edge = min_edge_bps / 10000.0

        if abs(mega_alpha) < min_edge:
            logger.debug("Edge for %s (%.4f) below threshold (%.4f)", asset, mega_alpha, min_edge)
            continue

        # Get current price
        candles = market_data.get(asset, {}).get("candles", [])
        if not candles:
            continue
        current_price = candles[-1]["close"]

        # Check drawdown circuit breakers
        should_halt, halt_reason = portfolio.check_drawdown_breakers()
        if should_halt:
            logger.critical("CIRCUIT BREAKER: %s", halt_reason)
            await alert_mgr.send_alert(f"CIRCUIT BREAKER: {halt_reason}", level="critical")
            return

        # Size position via Kelly
        combined_returns = active_signals[0].get_returns(200) if active_signals else None
        if combined_returns is not None and len(combined_returns) > 30:
            target_fraction = kelly.empirical_kelly(combined_returns)
        else:
            target_fraction = 0.0

        if mega_alpha < 0:
            target_fraction = 0.0  # No shorts

        portfolio.update_equity({asset: current_price})
        portfolio_value = portfolio.equity
        target_dollar = portfolio_value * target_fraction

        # Check position limits
        can_trade, reason = portfolio.can_open_position(asset, target_dollar)
        if not can_trade:
            logger.info("Position limit for %s: %s", asset, reason)
            continue

        # Compute delta
        pos = portfolio.get_position(asset)
        current_dollar = pos.get("quantity", 0) * current_price
        delta_dollar = target_dollar - current_dollar

        if abs(delta_dollar) < 10:  # $10 minimum trade
            continue

        side = "buy" if delta_dollar > 0 else "sell"
        qty = abs(delta_dollar) / current_price

        logger.info(
            "Trade signal: %s %s %.6f @ %.2f (edge=%.4f, kelly=%.4f)",
            side, asset, qty, current_price, mega_alpha, target_fraction,
        )

        # Step 6: Execute
        if paper_mode:
            logger.info("[PAPER] Would %s %.6f %s @ %.2f", side, qty, asset, current_price)
            journal.log_trade({
                "timestamp": int(time.time() * 1000),
                "asset": asset,
                "side": side,
                "qty": qty,
                "price": current_price,
                "mega_alpha": mega_alpha,
                "weights": weights,
                "paper": True,
            })
        else:
            try:
                result = await executor.execute(asset, side, qty, current_price)
                journal.log_fill(result)
                portfolio.update_position(
                    asset,
                    pos.get("quantity", 0) + (qty if side == "buy" else -qty),
                    current_price,
                )
                await alert_mgr.alert_fill(asset, side, qty, current_price)
            except Exception as e:
                logger.error("Execution failed for %s: %s", asset, e)
                await alert_mgr.alert_error(f"Execution failed: {asset}: {e}")

    # Step 7: Journal
    journal.log_cycle({
        "timestamp": int(time.time() * 1000),
        "weights": weights,
        "active_signals": len(active_signals),
        "assets": assets,
        "portfolio": portfolio.get_all_positions(),
        "cycle_duration_s": time.time() - cycle_start,
    })

    logger.info("=== Cycle End (%.1fs) ===", time.time() - cycle_start)


async def run(config: dict, paper_mode: bool, cycle_once: bool, config_dir: str = "config"):
    """Main bot loop."""
    global _shutdown

    # Initialize components
    candle_store = CandleStore(config.get("db_path", "candles.db"))
    await candle_store.init_db()

    rest_client = CoinbaseRestClient(
        api_key=config["exchange"]["api_key"],
        api_secret=config["exchange"]["api_secret"],
        sandbox=config["exchange"]["sandbox"],
    )

    executor = VWAPExecutor(
        rest_client=rest_client,
        num_slices=config["execution"]["vwap_slices"],
        spread_bps=config["execution"]["vwap_spread_bps"],
        max_duration_seconds=config["execution"]["vwap_max_duration_seconds"],
    )

    signals = build_signals(config, config_dir)
    engine = CombinationEngine(
        signals=signals,
        lookback_M=config["engine"]["combination_lookback_M"],
    )
    kelly = KellySizer(
        max_fraction=config["kelly"]["max_fraction"],
        mc_paths=config["kelly"]["monte_carlo_paths"],
        max_single_pct=config["kelly"]["max_single_position_pct"],
        max_total_pct=config["kelly"]["max_total_exposure_pct"],
    )

    # Determine initial capital from exchange or default
    initial_capital = 10000.0
    try:
        accounts = await rest_client.get_accounts()
        for acct in accounts:
            if acct.get("currency") == "USD":
                initial_capital = float(acct.get("available_balance", {}).get("value", 10000))
                break
    except Exception:
        logger.warning("Could not fetch account balance, using default $%.0f", initial_capital)

    portfolio = Portfolio(
        initial_capital=initial_capital,
        max_single_pct=config["kelly"]["max_single_position_pct"],
        max_total_pct=config["kelly"]["max_total_exposure_pct"],
        max_dd_7d_pct=config["risk"]["max_drawdown_7d_pct"],
        max_dd_30d_pct=config["risk"]["max_drawdown_30d_pct"],
    )

    journal = TradeJournal()
    alert_mgr = AlertManager(
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", ""),
    )

    assets = config["universe"]["assets"]
    cycle_interval = config["engine"]["cycle_interval_minutes"] * 60

    mode_str = "PAPER" if paper_mode else ("SANDBOX" if config["exchange"]["sandbox"] else "LIVE")
    logger.info("Bot started in %s mode. Assets: %s. Cycle: %ds",
                mode_str, assets, cycle_interval)

    if cycle_once:
        await run_cycle(
            config, signals, engine, kelly, portfolio, executor,
            rest_client, candle_store, journal, alert_mgr, assets, paper_mode,
        )
        return

    while not _shutdown:
        try:
            await run_cycle(
                config, signals, engine, kelly, portfolio, executor,
                rest_client, candle_store, journal, alert_mgr, assets, paper_mode,
            )
        except Exception as e:
            logger.exception("Unhandled error in cycle: %s", e)
            await alert_mgr.alert_error(f"Cycle error: {e}")

        # Sleep until next cycle
        for _ in range(cycle_interval):
            if _shutdown:
                break
            await asyncio.sleep(1)

    logger.info("Bot shutdown complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Alpha Combination Crypto Trading Bot"
    )
    parser.add_argument("--config", default="config/settings.yaml", help="Config file path")
    parser.add_argument("--paper", action="store_true", help="Paper trading mode")
    parser.add_argument("--cycle-once", action="store_true", help="Run single cycle and exit")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("alpha_bot.log"),
        ],
    )

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    config = load_config(args.config)
    config_dir = str(Path(args.config).parent)
    asyncio.run(run(config, args.paper, args.cycle_once, config_dir))


if __name__ == "__main__":
    main()
