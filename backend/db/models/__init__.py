"""Modelos de la base de datos.

Importar este paquete registra TODAS las tablas en `Base.metadata`. Alembic
depende de ello: un modelo que no se importe aqui no existe para las
migraciones, y el sintoma es una tabla que desaparece silenciosamente del
esquema en el proximo autogenerate.
"""

from .analysis import (
    BacktestRun,
    Explanation,
    FeatureSnapshot,
    ModelPrediction,
    ModelVersion,
    Score,
    Signal,
)
from .base import Base
from .market_data import (
    CorporateAction,
    FundamentalSnapshot,
    FxRate,
    Price,
    TechnicalIndicator,
)
from .ops import DataFreshness, DataQualityCheck, PipelineRun
from .reference import Country, Currency, Exchange, IndexComposition, Market, Security
from .users import (
    Alert,
    AlertEvent,
    Portfolio,
    PortfolioPosition,
    SavedScreener,
    Transaction,
    User,
    Watchlist,
    WatchlistItem,
)

__all__ = [
    "Alert",
    "AlertEvent",
    "BacktestRun",
    "Base",
    "CorporateAction",
    "Country",
    "Currency",
    "DataFreshness",
    "DataQualityCheck",
    "Exchange",
    "Explanation",
    "FeatureSnapshot",
    "FundamentalSnapshot",
    "FxRate",
    "IndexComposition",
    "Market",
    "ModelPrediction",
    "ModelVersion",
    "PipelineRun",
    "Portfolio",
    "PortfolioPosition",
    "Price",
    "SavedScreener",
    "Score",
    "Security",
    "Signal",
    "TechnicalIndicator",
    "Transaction",
    "User",
    "Watchlist",
    "WatchlistItem",
]
