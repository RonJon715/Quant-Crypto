"""Data provider modules for the Quant-Crypto trading bot.

Each provider inherits from :class:`BaseProvider` and normalises raw API
responses into the schema records defined in :mod:`data.schema`.
"""

from data.providers.base_provider import BaseProvider
from data.providers.binance_bulk import BinanceBulkProvider
from data.providers.blockchain_info import BlockchainInfoProvider
from data.providers.ccxt_provider import CcxtProvider
from data.providers.coinmetrics import CoinMetricsProvider
from data.providers.cryptocompare import CryptoCompareProvider
from data.providers.cryptoquant import CryptoQuantProvider
from data.providers.defi_llama import DefiLlamaProvider
from data.providers.fear_greed import FearGreedProvider
from data.providers.fred import FredProvider
from data.providers.glassnode import GlassnodeProvider
from data.providers.lunarcrush import LunarCrushProvider
from data.providers.polymarket import PolymarketProvider
from data.providers.tardis_provider import TardisProvider
from data.providers.twelve_data import TwelveDataProvider
from data.providers.whale_alert import WhaleAlertProvider

__all__ = [
    "BaseProvider",
    "BinanceBulkProvider",
    "BlockchainInfoProvider",
    "CcxtProvider",
    "CoinMetricsProvider",
    "CryptoCompareProvider",
    "CryptoQuantProvider",
    "DefiLlamaProvider",
    "FearGreedProvider",
    "FredProvider",
    "GlassnodeProvider",
    "LunarCrushProvider",
    "PolymarketProvider",
    "TardisProvider",
    "TwelveDataProvider",
    "WhaleAlertProvider",
]
