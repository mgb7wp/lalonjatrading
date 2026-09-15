"""Trazabilidad del analisis: modelos, features, scores, predicciones y senales.

Es la parte del esquema que responde a la pregunta que importa seis meses
despues: **por que este valor puntuo 87 aquel dia**.

La respuesta exige tres cosas, y las tres son restricciones de la base de datos
y no buenas intenciones:

1. Un score no existe sin la version de modelo que lo produjo (FK NOT NULL). Es
   lo que hace imposible el "model drift sin control" que teme §8 del encargo.
2. Un score guarda su cohorte y su tamano, porque un percentil sobre cuatro
   empresas no significa lo mismo que sobre cuarenta.
3. Las features que alimentaron el modelo quedan apuntadas por hash a un fichero
   inmutable.
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
from .enums import Cohort, ModelKind, SignalType
from .reference import _check

#: Un score es un percentil: 0-100 con dos decimales sobra.
PUNTUACION = Numeric(6, 2)
RATIO = Numeric(16, 8)


class ModelVersion(Base, Marcas):
    """Una version concreta de un modelo, con todo lo necesario para repetirla.

    Los cinco perfiles de §18 —crecimiento, valor, equilibrado, momentum, bajo
    riesgo— no son codigo: son cinco filas de esta tabla con pesos distintos
    sobre los mismos pilares. Por eso `parameters` es JSONB y no una columna por
    peso: un perfil nuevo no puede exigir una migracion.
    """

    __tablename__ = "model_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    training_date: Mapped[dt.date | None] = mapped_column(Date)
    training_period_start: Mapped[dt.date | None] = mapped_column(Date)
    training_period_end: Mapped[dt.date | None] = mapped_column(Date)
    benchmark_symbol: Mapped[str | None] = mapped_column(String(32))

    features: Mapped[list | None] = mapped_column(JSONB)
    parameters: Mapped[dict | None] = mapped_column(JSONB)
    metrics: Mapped[dict | None] = mapped_column(JSONB)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_model_version_name_version"),
        _check("kind", ModelKind, "kind_valido"),
    )


class FeatureSnapshot(Base, Marcas):
    """Puntero a un fichero de features inmutable.

    Las features no viven en Postgres (decision D-10): con 2.000 valores, 80
    features y una decada son cientos de millones de celdas cuyo acceso natural
    es analitico, no transaccional. Viven en Parquet particionado y aqui queda
    el puntero con su hash, que es lo que convierte "estas son las features que
    uso el modelo" en una afirmacion verificable.
    """

    __tablename__ = "feature_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature_set_version: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="sha256")
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    feature_names: Mapped[list | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint(
            "feature_set_version",
            "as_of_date",
            name="uq_feature_snapshot_feature_set_version_as_of_date",
        ),
    )


class Score(Base):
    """Puntuacion de un valor en una fecha segun un modelo.

    **Los valores son percentiles dentro de una cohorte comparable**, no
    magnitudes absolutas (decision D-4). Un 87 significa "mejor que el 87 % de
    su cohorte ese dia". Un score absoluto sube con todo el mercado en un tramo
    alcista y deja de discriminar, ademas de comparar un banco con una
    tecnologica, que §14 prohibe.

    Los pilares agregan al total; los sub-scores lo descomponen y se publican
    pero NO suman aparte (decision D-3). `risk` va invertido a proposito:
    **100 = menor riesgo relativo**.

    Que un pilar sea NULL es informacion, no un hueco: significa que no habia
    datos fiables. En ese caso los pesos se renormalizan sobre los disponibles y
    `available_pillars` deja constancia. Lo que no se hace nunca es imputar un
    50 "neutro", porque eso inventa un dato que mueve el ranking.
    """

    __tablename__ = "score"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # El nucleo del requisito de §8: sin version de modelo no hay score. La FK
    # es NOT NULL para que ni una carga masiva ni un script de emergencia puedan
    # dejar una puntuacion huerfana de la que nadie sepa como salio.
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"), nullable=False)

    overall: Mapped[Decimal] = mapped_column(PUNTUACION, nullable=False)

    fundamental: Mapped[Decimal | None] = mapped_column(PUNTUACION)
    technical: Mapped[Decimal | None] = mapped_column(PUNTUACION)
    sentiment: Mapped[Decimal | None] = mapped_column(PUNTUACION)
    risk: Mapped[Decimal | None] = mapped_column(PUNTUACION, comment="100 = menor riesgo")

    growth: Mapped[Decimal | None] = mapped_column(PUNTUACION)
    quality: Mapped[Decimal | None] = mapped_column(PUNTUACION)
    valuation: Mapped[Decimal | None] = mapped_column(PUNTUACION)
    momentum: Mapped[Decimal | None] = mapped_column(PUNTUACION)
    trend: Mapped[Decimal | None] = mapped_column(PUNTUACION)
    volatility: Mapped[Decimal | None] = mapped_column(PUNTUACION)

    cohort_used: Mapped[str] = mapped_column(String(24), nullable=False)
    n_cohort: Mapped[int] = mapped_column(Integer, nullable=False)
    available_pillars: Mapped[list | None] = mapped_column(JSONB)

    feature_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("feature_snapshot.id"))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    model_version: Mapped[ModelVersion] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "date",
            "model_version_id",
            name="uq_score_security_id_date_model_version_id",
        ),
        _check("cohort_used", Cohort, "cohort_used_valido"),
        CheckConstraint("overall BETWEEN 0 AND 100", name="overall_en_rango"),
        CheckConstraint("n_cohort >= 0", name="n_cohort_no_negativo"),
        # El historico de scores (§24) se lee por valor y fecha: "como ha
        # evolucionado esta oportunidad".
        Index("ix_score_security_id_date", "security_id", "date"),
        # Los rankings se leen por fecha y modelo, ordenando por puntuacion.
        Index("ix_score_date_model_version_id_overall", "date", "model_version_id", "overall"),
    )


class ModelPrediction(Base):
    """Probabilidad de batir al benchmark en un horizonte."""

    __tablename__ = "model_prediction"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"), nullable=False
    )
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"), nullable=False)
    prediction_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)

    probability: Mapped[Decimal | None] = mapped_column(RATIO)
    expected_return: Mapped[Decimal | None] = mapped_column(RATIO)
    confidence: Mapped[Decimal | None] = mapped_column(RATIO)
    benchmark_symbol: Mapped[str | None] = mapped_column(String(32))

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "model_version_id",
            "prediction_date",
            "horizon_days",
            name="uq_model_prediction_valor_modelo_fecha_horizonte",
        ),
        CheckConstraint(
            "probability IS NULL OR probability BETWEEN 0 AND 1",
            name="probabilidad_en_rango",
        ),
        CheckConstraint("horizon_days > 0", name="horizonte_positivo"),
    )


class Signal(Base):
    """Interpretacion del score, con los metadatos que exige publicarla.

    La senal NO sale solo del score (§25): entran la variacion del score, la
    probabilidad del modelo, el momentum, el riesgo, la valoracion y el regimen
    de mercado. `reason` es un codigo de un vocabulario cerrado y `reason_detail`
    guarda los numeros que lo justifican; el informe se construye contando, y
    con texto libre no se puede responder a "por que no hubo compras esta
    semana".

    Los campos de autoria y metodologia no son adorno. En la UE una
    recomendacion de inversion general —y `strong_buy` lo es— obliga a
    identificar al autor, describir el metodo y fechar la recomendacion
    (Reglamento de Abuso de Mercado, art. 20 y Reg. Delegado 2016/958). Se
    guardan desde el primer dia porque anadirlos despues significa que todo lo
    publicado hasta entonces no los tiene.
    """

    __tablename__ = "signal"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_version.id"), nullable=False)

    signal: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(RATIO)
    horizon_days: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_detail: Mapped[dict | None] = mapped_column(JSONB)
    market_regime: Mapped[str | None] = mapped_column(String(24))

    produced_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    author: Mapped[str] = mapped_column(String(120), nullable=False, default="sistema")
    methodology_ref: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "date",
            "model_version_id",
            name="uq_signal_security_id_date_model_version_id",
        ),
        _check("signal", SignalType, "signal_valida"),
        Index("ix_signal_date_signal", "date", "signal"),
    )


class Explanation(Base):
    """Explicacion redactada por el LLM, cacheada.

    La clave incluye el hash del score: **un score que no cambia no se vuelve a
    explicar**. Sin eso el coste de la IA crece con el trafico en lugar de con
    los datos, que es la diferencia entre un gasto acotado y uno que no lo esta.

    El LLM nunca produce un numero; recibe los scores ya calculados y los
    redacta (§29).
    """

    __tablename__ = "explanation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("security.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    score_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="es")

    summary: Mapped[str | None] = mapped_column(Text)
    positives: Mapped[list | None] = mapped_column(JSONB)
    negatives: Mapped[list | None] = mapped_column(JSONB)
    recent_changes: Mapped[list | None] = mapped_column(JSONB)
    questions: Mapped[list | None] = mapped_column(JSONB)

    llm_model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "date",
            "score_hash",
            "language",
            name="uq_explanation_security_id_date_score_hash_language",
        ),
    )
