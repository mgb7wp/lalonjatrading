"""Usuarios, carteras, watchlists y alertas.

La decision de fondo esta en `Transaction`: **el valor y el P&L de una cartera
se derivan de sus transacciones, no se guardan**. Denormalizarlos es comodo
hasta el dia que alguien corrige una compra de hace ocho meses y hay que
recalcular a mano todo lo que colgaba de ella.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Marcas
from .enums import (
    AlertChannel,
    AlertType,
    InvestmentHorizon,
    RiskProfile,
    SubscriptionPlan,
    TransactionType,
)
from .reference import _check

PRECIO = Numeric(20, 6)
CANTIDAD = Numeric(24, 8)


class User(Base, Marcas):
    __tablename__ = "user_account"  # `user` es palabra reservada en Postgres

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    # Nulo cuando el alta es por proveedor externo. Nunca guarda la contrasena:
    # guarda su hash Argon2.
    password_hash: Mapped[str | None] = mapped_column(Text)
    auth_provider: Mapped[str | None] = mapped_column(String(32))

    subscription_plan: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SubscriptionPlan.FREE.value
    )
    risk_profile: Mapped[str | None] = mapped_column(String(16))
    investment_horizon: Mapped[str | None] = mapped_column(String(16))
    preferred_markets: Mapped[list | None] = mapped_column(JSONB)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    portfolios: Mapped[list[Portfolio]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Unico sobre el correo en minusculas: sin esto, Ana@x.com y ana@x.com
        # son dos cuentas y la segunda no puede recuperar la contrasena.
        Index("uq_user_account_email_lower", func.lower(email), unique=True),
        _check("subscription_plan", SubscriptionPlan, "subscription_plan_valido"),
        _check("risk_profile", RiskProfile, "risk_profile_valido"),
        _check("investment_horizon", InvestmentHorizon, "investment_horizon_valido"),
    )


class Portfolio(Base, Marcas):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_currency: Mapped[str] = mapped_column(
        ForeignKey("currency.code"), nullable=False, default="EUR"
    )

    user: Mapped[User] = relationship(back_populates="portfolios")
    positions: Mapped[list[PortfolioPosition]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_portfolio_user_id_name"),)


class PortfolioPosition(Base, Marcas):
    """Posicion actual. Es una vista materializada de las transacciones.

    Se guarda porque leerla en cada peticion recalculando ocho meses de
    operaciones no escala, pero la fuente de verdad son las transacciones: esta
    fila se reconstruye a partir de ellas y nunca se edita a mano.
    """

    __tablename__ = "portfolio_position"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(ForeignKey("security.id"), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(CANTIDAD, nullable=False)
    average_price: Mapped[Decimal | None] = mapped_column(PRECIO)
    entry_date: Mapped[dt.date | None] = mapped_column(Date)
    target_weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))

    portfolio: Mapped[Portfolio] = relationship(back_populates="positions")

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "security_id",
            name="uq_portfolio_position_portfolio_id_security_id",
        ),
    )


class Transaction(Base, Marcas):
    """La fuente de verdad de una cartera."""

    __tablename__ = "portfolio_transaction"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(ForeignKey("security.id"), nullable=False)

    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(CANTIDAD, nullable=False)
    price: Mapped[Decimal] = mapped_column(PRECIO, nullable=False)
    fees: Mapped[Decimal] = mapped_column(PRECIO, nullable=False, default=0)
    taxes: Mapped[Decimal] = mapped_column(PRECIO, nullable=False, default=0)
    currency_code: Mapped[str] = mapped_column(ForeignKey("currency.code"), nullable=False)
    # El tipo de cambio del dia de la operacion, congelado. Recalcularlo despues
    # con el tipo de hoy reescribe la historia de la cartera cada manana.
    fx_rate_to_base: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    executed_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")

    __table_args__ = (
        _check("transaction_type", TransactionType, "transaction_type_valido"),
        CheckConstraint("quantity >= 0", name="cantidad_no_negativa"),
        CheckConstraint("price >= 0", name="precio_no_negativo"),
        CheckConstraint("fees >= 0", name="comisiones_no_negativas"),
        Index(
            "ix_portfolio_transaction_portfolio_id_executed_on",
            "portfolio_id",
            "executed_on",
        ),
    )


class Watchlist(Base, Marcas):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="Seguimiento")

    items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_id_name"),)


class WatchlistItem(Base, Marcas):
    __tablename__ = "watchlist_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist.id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(ForeignKey("security.id"), nullable=False)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint(
            "watchlist_id", "security_id", name="uq_watchlist_item_watchlist_id_security_id"
        ),
    )


class Alert(Base, Marcas):
    """Regla de alerta definida por el usuario."""

    __tablename__ = "alert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"),
        comment="nulo = la alerta aplica a toda la cartera o watchlist",
    )
    alert_type: Mapped[str] = mapped_column(String(48), nullable=False)
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(16, 6))
    parameters: Mapped[dict | None] = mapped_column(JSONB)
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AlertChannel.EMAIL.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    events: Mapped[list[AlertEvent]] = relationship(
        back_populates="alert", cascade="all, delete-orphan"
    )

    __table_args__ = (
        _check("alert_type", AlertType, "alert_type_valido"),
        _check("channel", AlertChannel, "channel_valido"),
    )


class AlertEvent(Base):
    """Un disparo concreto de una alerta.

    `dedupe_key` con unico es lo que impide que la misma alerta se mande dos
    veces por el mismo hecho cuando el pipeline se reejecuta. Sin ella, la
    idempotencia del pipeline (decision D-9) acaba en el buzon del usuario.
    """

    __tablename__ = "alert_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alert.id", ondelete="CASCADE"), nullable=False
    )
    triggered_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    delivered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    alert: Mapped[Alert] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("alert_id", "dedupe_key", name="uq_alert_event_alert_id_dedupe_key"),
    )


class SavedScreener(Base, Marcas):
    __tablename__ = "saved_screener"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_screener_user_id_name"),)
