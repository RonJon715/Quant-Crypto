from signals.base import BaseSignal
from signals.momentum import (
    CrossAssetMomentum,
    DualTimeframeMomentum,
    RateOfChangeAcceleration,
)
from signals.mean_reversion import (
    BollingerZScore,
    CrossPairSpread,
    FundingRateMeanReversion,
)
from signals.volatility import (
    RealizedImpliedGap,
    VolatilityRegime,
    VolOfVol,
)
from signals.microstructure import (
    EffectiveSpread,
    OrderbookImbalance,
    VPIN,
)
from signals.onchain import (
    ExchangeNetFlow,
    StablecoinSupplyRatio,
    WhaleMovement,
)
from signals.sentiment import (
    FearGreedSignal,
    SocialVolume,
)
from signals.macro import (
    DXYCorrelation,
    M2MoneySupply,
)

__all__ = [
    "BaseSignal",
    # momentum
    "DualTimeframeMomentum",
    "RateOfChangeAcceleration",
    "CrossAssetMomentum",
    # mean reversion
    "CrossPairSpread",
    "BollingerZScore",
    "FundingRateMeanReversion",
    # volatility
    "VolatilityRegime",
    "VolOfVol",
    "RealizedImpliedGap",
    # microstructure
    "OrderbookImbalance",
    "EffectiveSpread",
    "VPIN",
    # onchain
    "ExchangeNetFlow",
    "StablecoinSupplyRatio",
    "WhaleMovement",
    # sentiment
    "FearGreedSignal",
    "SocialVolume",
    # macro
    "DXYCorrelation",
    "M2MoneySupply",
]
