"""Etapa de senales: interpreta los scores ya calculados y los persiste.

Va DESPUES de `scores.py` y lee de la tabla `score`, no recalcula nada. Separar
las dos etapas no es ceremonia: un score es una medicion y una senal es una
recomendacion. Cambiar los umbrales de senal —que es lo que uno toca a
menudo— tiene que poder rehacerse sin volver a puntuar el universo entero, y
sobre todo sin que los scores publicados cambien por el camino.

El regimen se calcula una vez por mercado, no una por valor: es una propiedad
del mercado y calcularlo 33 veces daria el mismo numero 33 veces.
"""

from __future__ import annotations

import datetime as dt
import logging

from estrategia import senales as motor
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.adapters.desde_bd import instantanea_desde_bd
from backend.db.models import ModelVersion, Score, Security, Signal
from backend.db.models.enums import AssetType

log = logging.getLogger("pipeline.senales")

#: Quien firma la recomendacion. El Reglamento de Abuso de Mercado exige
#: identificar al autor de una recomendacion de inversion general, y
#: `strong_buy` lo es. Va aqui y no en la base para que cambie con el codigo que
#: de verdad la produjo.
AUTOR = "La Lonja - motor de reglas"
METODOLOGIA = "docs/ARCHITECTURE.md#9-motor-de-senales"

#: Dias hacia atras para medir la variacion del score. Un mes natural es lo que
#: pide §25 y lo que entiende quien lo lee.
DIAS_VARIACION = 30


def _scores(sesion: Session, modelo_id: int, fecha: dt.date) -> dict[int, Score]:
    filas = sesion.scalars(
        select(Score).where(Score.model_version_id == modelo_id, Score.date == fecha)
    ).all()
    return {f.security_id: f for f in filas}


def ejecutar(
    sesion: Session,
    cfg,
    fecha: dt.date | None = None,
    mercados: list[str] | None = None,
    modelo: str = "equilibrado",
) -> dict[str, int]:
    """Emite y persiste las senales del dia. Devuelve el recuento por motivo."""
    fecha = fecha or dt.date.today()

    # Se elige la version que DE VERDAD tiene scores de esa fecha, no la ultima
    # con ese nombre. `cargar_modelos` da de alta una fila por (nombre, version),
    # asi que conviven varias: coger la de id mas alto emitiria senales contra
    # una version sin puntuar y devolveria cero sin explicar por que.
    version = sesion.scalars(
        select(ModelVersion)
        .join(Score, Score.model_version_id == ModelVersion.id)
        .where(ModelVersion.name == modelo, Score.date == fecha)
        .order_by(ModelVersion.id.desc())
        .limit(1)
    ).first()
    if version is None:
        log.warning(
            "no hay scores del %s para el modelo %s; ejecuta antes calculate_scores.py",
            fecha,
            modelo,
        )
        return {}

    actuales = _scores(sesion, version.id, fecha)

    previos = _scores(sesion, version.id, fecha - dt.timedelta(days=DIAS_VARIACION))

    consulta = select(Security).where(
        Security.active.is_(True), Security.asset_type != AssetType.INDEX.value
    )
    if mercados:
        consulta = consulta.where(Security.market_id.in_(mercados))
    valores = {v.id: v for v in sesion.scalars(consulta).all()}
    if not valores:
        return {}

    # El regimen necesita las series de los indices, que el adaptador trae de la
    # base igual que el backtest. Una sola instantanea para todos los mercados.
    instantanea = instantanea_desde_bd(sesion, hasta=fecha)
    instantanea.preparar(cfg)
    vista = instantanea.vista(fecha)
    regimenes: dict[str, motor.Regimen] = {}
    for mercado_id in {v.market_id for v in valores.values()}:
        regimen, detalle = motor.regimen_de_mercado(mercado_id, fecha, vista, cfg)
        regimenes[mercado_id] = regimen
        log.info("regimen de %s: %s (%s)", mercado_id, regimen, detalle)

    filas = []
    recuento: dict[str, int] = {}
    for security_id, score in actuales.items():
        valor = valores.get(security_id)
        if valor is None or score.overall is None:
            continue
        previo = previos.get(security_id)
        variacion = (
            float(score.overall) - float(previo.overall)
            if previo is not None and previo.overall is not None
            else None
        )
        senal = motor.evaluar(
            score=float(score.overall),
            variacion_score=variacion,
            momentum=float(score.momentum) if score.momentum is not None else None,
            riesgo=float(score.risk) if score.risk is not None else None,
            valoracion=float(score.valuation) if score.valuation is not None else None,
            regimen=regimenes.get(valor.market_id, motor.Regimen.DESCONOCIDO),
            cfg=cfg,
        )
        recuento[str(senal.motivo)] = recuento.get(str(senal.motivo), 0) + 1
        filas.append(
            {
                "security_id": security_id,
                "date": fecha,
                "model_version_id": version.id,
                "signal": str(senal.tipo),
                "confidence": senal.confianza,
                "horizon_days": senal.horizonte_dias,
                "reason": str(senal.motivo),
                "reason_detail": senal.detalle,
                "market_regime": str(senal.regimen),
                "author": AUTOR,
                "methodology_ref": METODOLOGIA,
            }
        )

    if filas:
        sentencia = insert(Signal).values(filas)
        sesion.execute(
            sentencia.on_conflict_do_update(
                index_elements=["security_id", "date", "model_version_id"],
                set_={
                    c: sentencia.excluded[c]
                    for c in (
                        "signal",
                        "confidence",
                        "horizon_days",
                        "reason",
                        "reason_detail",
                        "market_regime",
                        "author",
                        "methodology_ref",
                    )
                },
            )
        )
    return recuento
