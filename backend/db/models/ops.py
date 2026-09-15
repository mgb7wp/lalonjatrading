"""Operacion del pipeline: ejecuciones y comprobaciones de calidad.

`PipelineRun` es lo que convierte "el pipeline es idempotente" en algo que se
puede comprobar en lugar de afirmar. La clave unica (pipeline, etapa, fecha) es
la que permite reanudar saltando lo ya hecho en vez de repetirlo, que es la
mitad de la decision D-9; la otra mitad son los UPSERT de cada tabla de datos.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .enums import CheckStatus, RunStatus, Severity
from .reference import _check


class PipelineRun(Base):
    __tablename__ = "pipeline_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pipeline: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    run_date: Mapped[dt.date] = mapped_column(
        Date, nullable=False, comment="dia logico, no el instante de ejecucion"
    )
    market_id: Mapped[str | None] = mapped_column(
        ForeignKey("market.id"),
        comment="cada mercado se procesa tras SU cierre; no hay cierre global",
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rows_affected: Mapped[int | None] = mapped_column(BigInteger)
    # La instantanea que se uso. Es lo que permite reproducir un score de hace
    # tres meses aunque el proveedor haya revisado el pasado desde entonces.
    snapshot_downloaded_at: Mapped[dt.date | None] = mapped_column(Date)
    error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint(
            "pipeline",
            "stage",
            "run_date",
            "market_id",
            name="uq_pipeline_run_pipeline_stage_run_date_market_id",
        ),
        _check("status", RunStatus, "status_valido"),
        Index("ix_pipeline_run_run_date_status", "run_date", "status"),
    )


class DataQualityCheck(Base):
    """Resultado de una comprobacion de calidad sobre un lote de datos.

    Se persisten y no solo se registran en el log porque la degradacion de una
    fuente se ve como tendencia —"lleva tres semanas faltando el 12 % de los
    fundamentales de Brasil"— y un log rotado no permite esa lectura.
    """

    __tablename__ = "data_quality_check"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_run.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    dataset: Mapped[str] = mapped_column(String(32), nullable=False)
    market_id: Mapped[str | None] = mapped_column(ForeignKey("market.id"))
    check_name: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict | None] = mapped_column(JSONB)
    checked_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        _check("status", CheckStatus, "status_valido"),
        _check("severity", Severity, "severity_valida"),
        Index("ix_data_quality_check_source_dataset_checked_at", "source", "dataset", "checked_at"),
    )


class DataFreshness(Base):
    """Ultimo dato conocido por mercado y tipo de dato.

    Es lo que sirve `/health/data`. Podria calcularse con un MAX() sobre las
    series, pero ese MAX sobre decenas de millones de filas particionadas no es
    una consulta para un health check que se llama cada quince segundos.
    """

    __tablename__ = "data_freshness"

    dataset: Mapped[str] = mapped_column(String(32), primary_key=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("market.id"), primary_key=True)

    last_data_date: Mapped[dt.date | None] = mapped_column(Date)
    last_success_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(32))
    securities_covered: Mapped[int | None] = mapped_column(Integer)
    securities_expected: Mapped[int | None] = mapped_column(Integer)
    is_stale: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
