"""Entidades de referencia: paises, divisas, mercados, bolsas y valores.

La exigencia de §3 del encargo —que los mercados no esten incrustados en el
codigo— se cumple aqui: un mercado es una fila. Anadir Francia son dos filas y
un calendario, no un despliegue.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Marcas
from .enums import AssetType, MarketClassification


def _check(columna: str, enumeracion, nombre: str) -> CheckConstraint:
    """CHECK que limita una columna de texto a los valores de una enumeracion."""
    valores = ", ".join(f"'{v.value}'" for v in enumeracion)
    return CheckConstraint(f"{columna} IN ({valores})", name=nombre)


class Country(Base, Marcas):
    __tablename__ = "country"

    code: Mapped[str] = mapped_column(String(2), primary_key=True, comment="ISO 3166-1 alfa-2")
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class Currency(Base, Marcas):
    __tablename__ = "currency"

    code: Mapped[str] = mapped_column(String(3), primary_key=True, comment="ISO 4217")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    minor_units: Mapped[int] = mapped_column(Integer, nullable=False, default=2)


class Market(Base, Marcas):
    __tablename__ = "market"

    # La clave es el codigo corto que usa el motor ('es', 'us', 'de', 'in',
    # 'br'), no un entero: es lo que aparece en la configuracion, en la API y en
    # las URL, y un id sintetico solo anadiria una traduccion mas.
    id: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    country_code: Mapped[str] = mapped_column(ForeignKey("country.code"), nullable=False)
    currency_code: Mapped[str] = mapped_column(ForeignKey("currency.code"), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    trading_calendar: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="codigo de exchange_calendars, p. ej. XMAD"
    )
    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    ticker_suffix: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    benchmark_symbol: Mapped[str | None] = mapped_column(String(32))
    # El benchmark del target de un modelo debe ser de RETORNO TOTAL; el de
    # precio sirve para detectar el regimen pero sesga la etiqueta. Decision D-5.
    benchmark_is_total_return: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    exchanges: Mapped[list[Exchange]] = relationship(back_populates="market")

    __table_args__ = (_check("classification", MarketClassification, "classification_valida"),)


class Exchange(Base, Marcas):
    __tablename__ = "exchange"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    mic: Mapped[str | None] = mapped_column(String(4), comment="ISO 10383")
    country_code: Mapped[str] = mapped_column(ForeignKey("country.code"), nullable=False)
    market_id: Mapped[str] = mapped_column(ForeignKey("market.id"), nullable=False)

    market: Mapped[Market] = relationship(back_populates="exchanges")


class Security(Base, Marcas):
    __tablename__ = "security"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    ticker: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="simbolo canonico del motor, p. ej. ITX.MC"
    )
    isin: Mapped[str | None] = mapped_column(String(12))
    # Deliberadamente NO unico. Una misma empresa cotiza en varias plazas con el
    # mismo ISIN, y ese es justo el caso que hay que poder representar para
    # deduplicar ADRs (decision D-12) en lugar de el que hay que prohibir.
    company_id: Mapped[str | None] = mapped_column(
        String(32),
        comment="agrupa las lineas de cotizacion de una misma empresa (ADR + local)",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    market_id: Mapped[str] = mapped_column(ForeignKey("market.id"), nullable=False)
    exchange_id: Mapped[int | None] = mapped_column(ForeignKey("exchange.id"))
    currency_code: Mapped[str] = mapped_column(ForeignKey("currency.code"), nullable=False)

    asset_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AssetType.COMMON_STOCK.value
    )
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(120))

    # Alta y baja: el universo se evalua A FECHA. Sin esto, aplicar el universo
    # de hoy a 2018 es elegir con informacion del futuro —se backtestea sobre
    # las empresas que sobrevivieron— y ese es el sesgo de supervivencia, el mas
    # grande que arrastra el sistema. Decision D-13.
    listed_from: Mapped[dt.date | None] = mapped_column(Date)
    listed_to: Mapped[dt.date | None] = mapped_column(Date)
    is_primary_listing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    notes: Mapped[str | None] = mapped_column(Text)

    market: Mapped[Market] = relationship()

    __table_args__ = (
        UniqueConstraint("market_id", "ticker", name="uq_security_market_id_ticker"),
        _check("asset_type", AssetType, "asset_type_valido"),
        CheckConstraint(
            "listed_to IS NULL OR listed_from IS NULL OR listed_to >= listed_from",
            name="alta_antes_que_baja",
        ),
        Index("ix_security_isin", "isin"),
        Index("ix_security_company_id", "company_id"),
        Index("ix_security_market_id_active", "market_id", "active"),
    )


class IndexComposition(Base, Marcas):
    """Pertenencia historica a un indice.

    Existe por la misma razon que `listed_from`/`listed_to`: construir el
    universo de una fecha pasada con la composicion de hoy es seleccionar con
    informacion del futuro. Sin esta tabla, "las 35 del IBEX" significa siempre
    "las 35 de hoy", que en 2018 no eran esas.
    """

    __tablename__ = "index_composition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_code: Mapped[str] = mapped_column(String(32), nullable=False)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"), nullable=False
    )
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[dt.date | None] = mapped_column(Date)

    __table_args__ = (
        UniqueConstraint(
            "index_code",
            "security_id",
            "valid_from",
            name="uq_index_composition_index_code_security_id_valid_from",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="rango_coherente",
        ),
        Index("ix_index_composition_index_code_valid_from", "index_code", "valid_from"),
    )
