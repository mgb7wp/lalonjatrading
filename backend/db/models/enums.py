"""Vocabularios cerrados.

Todos se persisten como texto con una restriccion CHECK, no como tipos ENUM
nativos de Postgres. Un ENUM nativo obliga a un `ALTER TYPE` para anadir un
valor, no se puede quitar uno dentro de una transaccion, y convierte cada
ampliacion del vocabulario en una migracion delicada. Texto + CHECK da la misma
garantia de integridad y se modifica sin ceremonia.

Que sean enumeraciones y no cadenas sueltas es lo que permite contar: el informe
responde a "por que no hubo ninguna compra esta semana" agrupando por motivo, y
sin vocabulario cerrado esa pregunta no tiene respuesta.
"""

from __future__ import annotations

import enum


class AssetType(enum.StrEnum):
    COMMON_STOCK = "common_stock"
    ADR = "adr"
    ETF = "etf"
    REIT = "reit"
    INDEX = "index"
    FUND = "fund"


class MarketClassification(enum.StrEnum):
    DEVELOPED = "developed"
    EMERGING = "emerging"


class Period(enum.StrEnum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"


class PitOrigin(enum.StrEnum):
    """De donde sale el "que se sabia cuando" de una fila fundamental.

    `CAPTURED` es una foto tomada en su momento. `RECONSTRUCTED` es una
    deduccion posterior, que es lo que devuelven los proveedores gratuitos
    porque reexpresan las cifras a dia de hoy. La distincion se guarda en lugar
    de disimularse: el informe publica el porcentaje de filas reconstruidas.
    """

    CAPTURED = "captured"
    RECONSTRUCTED = "reconstructed"


class CorporateActionType(enum.StrEnum):
    SPLIT = "split"
    DIVIDEND = "dividend"
    TICKER_CHANGE = "ticker_change"
    MERGER = "merger"
    DELISTING = "delisting"


class Pillar(enum.StrEnum):
    """Los cuatro pilares ortogonales que agregan al score global.

    Los sub-scores (crecimiento, calidad, valoracion, momentum...) descomponen
    un pilar y se publican, pero NO suman aparte: hacerlo contaria el momentum
    dentro de `technical` y otra vez por su cuenta. Decision D-3.
    """

    FUNDAMENTAL = "fundamental"
    TECHNICAL = "technical"
    SENTIMENT = "sentiment"
    RISK = "risk"


class Cohort(enum.StrEnum):
    """Sobre que conjunto se percentilo una puntuacion.

    Se guarda en cada score para que una puntuacion rara se pueda rastrear
    hasta una cohorte demasiado pequena para significar nada.
    """

    MARKET_SECTOR = "market_sector"
    MARKET = "market"
    BLOCK = "block"
    INSUFFICIENT = "insufficient"


class SignalType(enum.StrEnum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class ModelKind(enum.StrEnum):
    RULES = "rules"
    STATISTICAL = "statistical"


class SubscriptionPlan(enum.StrEnum):
    FREE = "free"
    PRO = "pro"
    PREMIUM = "premium"


class RiskProfile(enum.StrEnum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class InvestmentHorizon(enum.StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class TransactionType(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    FEE = "fee"


class AlertType(enum.StrEnum):
    SCORE_CROSSES_THRESHOLD = "score_crosses_threshold"
    SCORE_CHANGES_BY = "score_changes_by"
    SIGNAL_CHANGES = "signal_changes"
    PRICE_MOVES_BY = "price_moves_by"
    VOLATILITY_INCREASES = "volatility_increases"
    FUNDAMENTAL_DETERIORATION = "fundamental_deterioration"
    TECHNICAL_DETERIORATION = "technical_deterioration"
    EARNINGS_APPROACHING = "earnings_approaching"


class AlertChannel(enum.StrEnum):
    EMAIL = "email"
    PUSH = "push"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"


class RunStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class CheckStatus(enum.StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class Severity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class BacktestPeriod(enum.StrEnum):
    """Sobre que tramo del historico se ha corrido un backtest.

    La distincion no es informativa: es el guardarrail de RT-1. El periodo de
    validacion esta cerrado hasta el final, y solo se puede comprobar que se ha
    respetado si cada ejecucion deja escrito sobre cual de los dos corrio.
    """

    DISENO = "diseno"
    VALIDACION = "validacion"
    COMPLETO = "completo"
