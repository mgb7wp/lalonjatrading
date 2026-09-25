"""Series de mercado: precios, fundamentales, indicadores, divisas y eventos.

Dos ideas gobiernan estas tablas.

**Clave natural explicita.** Cada serie tiene una restriccion unica sobre la
clave que la identifica de verdad —(valor, fecha) en precios, (valor, periodo)
en fundamentales— porque de ahi cuelga la idempotencia del pipeline: sin una
clave sobre la que hacer UPSERT, reejecutar un dia duplica filas. Decision D-9.

**`publication_date` obligatoria.** Sin ella no se puede saber que se sabia en
cada momento, y una fila fundamental sin esa fecha convierte todo backtest que
la toque en un ejercicio de adivinacion con datos del futuro.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Marcas
from .enums import CorporateActionType, Period, PitOrigin
from .reference import _check

#: Precios y magnitudes monetarias. Numeric y no float: un backtest tiene que
#: dar el mismo numero dos veces, y la suma de flotantes depende del orden.
PRECIO = Numeric(20, 6)
IMPORTE = Numeric(24, 4)
RATIO = Numeric(16, 8)


class Price(Base):
    """OHLCV diario en divisa local.

    Particionada por ano. Con cinco mercados y una decada de historico esto son
    decenas de millones de filas; sin particion, borrar y recargar un ano obliga
    a un DELETE masivo y el indice se degrada.

    Se guardan a la vez el precio ajustado y el bruto, y no es redundancia:
    calcular el ATR con maximos y minimos en bruto y las medias con el cierre
    ajustado convierte cada dividendo en un hueco fantasma. El volumen negociado
    se mide con precio bruto x volumen bruto, porque el volumen no se ajusta por
    dividendos y mezclarlo con el precio ajustado subestima la liquidez
    historica.
    """

    __tablename__ = "price"

    # La clave primaria de una tabla particionada tiene que incluir la columna
    # de particion. Coincide con la clave natural, asi que no hace falta un id
    # sintetico que solo serviria para permitir duplicados.
    security_id: Mapped[int] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)

    open: Mapped[Decimal | None] = mapped_column(PRECIO)
    high: Mapped[Decimal | None] = mapped_column(PRECIO)
    low: Mapped[Decimal | None] = mapped_column(PRECIO)
    close: Mapped[Decimal] = mapped_column(PRECIO, nullable=False)
    close_raw: Mapped[Decimal | None] = mapped_column(PRECIO, comment="sin ajustar")
    volume: Mapped[int | None] = mapped_column(BigInteger, comment="sin ajustar")

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # Yahoo revisa hacia atras los precios ajustados: el mismo backtest da
    # numeros distintos segun el dia en que se bajaron los datos. Guardar esto
    # es lo que permite reproducir un resultado.
    downloaded_at: Mapped[dt.date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        CheckConstraint("close >= 0", name="cierre_no_negativo"),
        CheckConstraint("high IS NULL OR low IS NULL OR high >= low", name="ohlc_coherente"),
        Index("ix_price_date", "date"),
        {"postgresql_partition_by": "RANGE (date)"},
    )


class FundamentalSnapshot(Base):
    """Estados financieros de un periodo, con la fecha en que se publicaron."""

    __tablename__ = "fundamental_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"), nullable=False
    )
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)

    # NOT NULL a proposito. Una fila sin fecha de publicacion no se puede usar
    # sin arriesgar sesgo de anticipacion, asi que no entra. El contrato del
    # motor ya lo rechaza; aqui se rechaza tambien a nivel de base de datos,
    # para que ninguna carga masiva se lo salte.
    publication_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    publication_date_origin: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="real | estimada_retraso"
    )
    pit_origin: Mapped[str] = mapped_column(String(16), nullable=False)

    revenue: Mapped[Decimal | None] = mapped_column(IMPORTE)
    gross_profit: Mapped[Decimal | None] = mapped_column(IMPORTE)
    operating_income: Mapped[Decimal | None] = mapped_column(IMPORTE)
    ebit: Mapped[Decimal | None] = mapped_column(IMPORTE)
    ebitda: Mapped[Decimal | None] = mapped_column(IMPORTE)
    net_income: Mapped[Decimal | None] = mapped_column(IMPORTE)
    eps: Mapped[Decimal | None] = mapped_column(RATIO)
    free_cash_flow: Mapped[Decimal | None] = mapped_column(IMPORTE)
    total_assets: Mapped[Decimal | None] = mapped_column(IMPORTE)
    total_debt: Mapped[Decimal | None] = mapped_column(IMPORTE)
    net_debt: Mapped[Decimal | None] = mapped_column(IMPORTE)
    cash: Mapped[Decimal | None] = mapped_column(IMPORTE)
    equity: Mapped[Decimal | None] = mapped_column(IMPORTE)
    shares_outstanding: Mapped[Decimal | None] = mapped_column(IMPORTE)
    enterprise_value: Mapped[Decimal | None] = mapped_column(IMPORTE)

    current_assets: Mapped[Decimal | None] = mapped_column(IMPORTE)
    current_liabilities: Mapped[Decimal | None] = mapped_column(IMPORTE)
    interest_expense: Mapped[Decimal | None] = mapped_column(IMPORTE)

    roe: Mapped[Decimal | None] = mapped_column(RATIO)
    roa: Mapped[Decimal | None] = mapped_column(RATIO)
    gross_margin: Mapped[Decimal | None] = mapped_column(RATIO)
    operating_margin: Mapped[Decimal | None] = mapped_column(RATIO)
    net_margin: Mapped[Decimal | None] = mapped_column(RATIO)

    # Los estados financieros vienen en la divisa en que REPORTA la empresa, que
    # no siempre es la de su cotizacion. Mezclarlas produce ratios sin sentido
    # que nadie detecta porque el numero parece razonable.
    reporting_currency: Mapped[str | None] = mapped_column(String(3))
    listing_currency: Mapped[str | None] = mapped_column(String(3))

    extra: Mapped[dict | None] = mapped_column(
        JSONB, comment="campos del proveedor que aun no tienen columna propia"
    )

    source: Mapped[str] = mapped_column(String(32), nullable=False)
    downloaded_at: Mapped[dt.date] = mapped_column(Date, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "period_end",
            "period",
            name="uq_fundamental_snapshot_security_id_period_end_period",
        ),
        _check("period", Period, "period_valido"),
        _check("pit_origin", PitOrigin, "pit_origin_valido"),
        # Publicar antes de cerrar el periodo es imposible; si aparece, es un
        # error de mapeo del proveedor y hay que verlo al cargar, no en el
        # backtest tres meses despues.
        CheckConstraint(
            "publication_date >= period_end",
            name="publicacion_tras_el_periodo",
        ),
        Index(
            "ix_fundamental_snapshot_security_id_publication_date",
            "security_id",
            "publication_date",
        ),
    )


class TechnicalIndicator(Base):
    """Indicadores tecnicos ya calculados, para servirlos sin recalcular.

    Tabla ancha con las columnas que la API sirve, mas `extra` en JSONB para el
    resto. La alternativa —una fila por indicador y fecha— es mas flexible pero
    multiplica por treinta el numero de filas y hace que pintar una ficha sean
    treinta lecturas.

    Ojo con lo que es esta tabla y lo que no: aqui estan los indicadores que se
    MUESTRAN. Las features de entrenamiento viven en Parquet versionado
    (decision D-10), porque el acceso analitico —"todas las features de 2019"—
    es otro problema.
    """

    __tablename__ = "technical_indicator"

    security_id: Mapped[int] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)

    sma_20: Mapped[Decimal | None] = mapped_column(PRECIO)
    sma_50: Mapped[Decimal | None] = mapped_column(PRECIO)
    sma_100: Mapped[Decimal | None] = mapped_column(PRECIO)
    sma_200: Mapped[Decimal | None] = mapped_column(PRECIO)
    ema_20: Mapped[Decimal | None] = mapped_column(PRECIO)

    rsi_14: Mapped[Decimal | None] = mapped_column(RATIO)
    macd: Mapped[Decimal | None] = mapped_column(RATIO)
    macd_signal: Mapped[Decimal | None] = mapped_column(RATIO)
    atr_14: Mapped[Decimal | None] = mapped_column(PRECIO)
    adx_14: Mapped[Decimal | None] = mapped_column(RATIO)
    stochastic_k: Mapped[Decimal | None] = mapped_column(RATIO)
    bollinger_position: Mapped[Decimal | None] = mapped_column(RATIO)

    volatility_annualized: Mapped[Decimal | None] = mapped_column(RATIO)
    beta: Mapped[Decimal | None] = mapped_column(RATIO)
    max_drawdown_1y: Mapped[Decimal | None] = mapped_column(RATIO)
    momentum_12_1: Mapped[Decimal | None] = mapped_column(RATIO)
    relative_strength: Mapped[Decimal | None] = mapped_column(RATIO)
    distance_from_52w_high: Mapped[Decimal | None] = mapped_column(RATIO)
    distance_from_52w_low: Mapped[Decimal | None] = mapped_column(RATIO)
    volume_ratio_20: Mapped[Decimal | None] = mapped_column(RATIO)

    extra: Mapped[dict | None] = mapped_column(JSONB)

    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_technical_indicator_date", "date"),)


class FxRate(Base):
    """Tipos de cambio diarios, siempre en el mismo sentido: base -> divisa.

    En un solo sentido y se invierten al leer, para que no haya dos convenios
    circulando por el codigo. Un tipo invertido en la mitad de los sitios es un
    error que no rompe nada: solo da rentabilidades ligeramente equivocadas.
    """

    __tablename__ = "fx_rate"

    base_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    quote_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        CheckConstraint("rate > 0", name="tasa_positiva"),
        Index("ix_fx_rate_date", "date"),
    )


class CorporateAction(Base, Marcas):
    """Splits, dividendos, cambios de ticker, fusiones y bajas."""

    __tablename__ = "corporate_action"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(24), nullable=False)
    effective_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # Un split 2:1 es ratio 2; un dividendo usa `amount`. Se separan porque
    # meterlos en un campo unico obliga a saber de memoria que significa el
    # numero segun el tipo.
    ratio: Mapped[Decimal | None] = mapped_column(RATIO)
    amount: Mapped[Decimal | None] = mapped_column(PRECIO)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "action_type",
            "effective_date",
            name="uq_corporate_action_security_id_action_type_effective_date",
        ),
        _check("action_type", CorporateActionType, "action_type_valido"),
    )
