"""Consultas que comparten varios endpoints.

Antes vivian repartidas: el screener importaba funciones privadas de rankings,
la busqueda de un valor por ticker estaba copiada en carteras y en listas, y el
"hace 30 dias" de las variaciones estaba escrito en tres sitios. Aqui estan una
sola vez, para que un arreglo en una (como el de R4 en `version_puntuada`)
llegue a todos los que la usan.
"""

from __future__ import annotations

import datetime as dt

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..db.models import ModelVersion, Price, Score, Security

#: Dias hacia atras para "lo que ha cambiado ultimamente": las variaciones de
#: los rankings, de las listas y de la ficha de un valor. Un solo numero.
DIAS_VARIACION = 30


def perfil(bd: Session, modelo: str) -> ModelVersion | None:
    """Si el perfil existe, en cualquier version. Solo decide el 404."""
    return bd.scalars(
        select(ModelVersion).where(ModelVersion.name == modelo).order_by(ModelVersion.id.desc())
    ).first()


def version_puntuada(
    bd: Session, modelo: str, corte: dt.date
) -> tuple[ModelVersion | None, dt.date | None]:
    """La version del perfil con los scores mas recientes en o antes del corte, y su fecha.

    No vale "la version mas nueva". `cargar_modelos` da de alta una fila por
    (nombre, version), asi que conviven varias, y la nueva solo tiene scores
    desde el dia en que entro: con ella, cualquier consulta de una fecha
    anterior salia vacia aunque ese dia se hubiera publicado un ranking. Si un
    mismo dia tiene scores de dos versiones, manda la mas reciente. Es el mismo
    criterio con el que `workers/pipeline/senales.py` elige version al emitir.
    """
    fila = bd.execute(
        select(ModelVersion, Score.date)
        .join(Score, Score.model_version_id == ModelVersion.id)
        .where(ModelVersion.name == modelo, Score.date <= corte)
        .order_by(Score.date.desc(), ModelVersion.id.desc())
        .limit(1)
    ).first()
    return (None, None) if fila is None else (fila[0], fila[1])


def ultima_fecha_puntuada(bd: Session, version_id: int, corte: dt.date) -> dt.date | None:
    """Ultima fecha con scores de esa version en o antes del corte. Nunca posterior."""
    return bd.scalars(
        select(Score.date)
        .where(Score.model_version_id == version_id, Score.date <= corte)
        .order_by(Score.date.desc())
        .limit(1)
    ).first()


def volumenes(bd: Session, fecha: dt.date) -> dict[int, float]:
    """Ultimo volumen conocido de cada valor, para desempatar en la dedup."""
    ultimo = (
        select(Price.security_id, func.max(Price.date).label("fecha"))
        .where(Price.date <= fecha)
        .group_by(Price.security_id)
        .subquery()
    )
    filas = bd.execute(
        select(Price.security_id, Price.volume).join(
            ultimo,
            and_(Price.security_id == ultimo.c.security_id, Price.date == ultimo.c.fecha),
        )
    ).all()
    return {sid: float(vol or 0) for sid, vol in filas}


def deduplicar(filas: list, volumenes: dict[int, float]) -> list:
    """Una linea por empresa (D-12).

    Se agrupa por `company_id`. Los valores sin `company_id` no se agrupan entre
    si: sin identificador comun, meterlos en el mismo saco uniria empresas
    distintas, que es peor que dejar un duplicado.
    """
    mejor: dict[object, tuple] = {}
    for score, valor in filas:
        clave = valor.company_id or f"_sin_empresa_{valor.id}"
        candidato = (
            1 if valor.is_primary_listing else 0,
            volumenes.get(valor.id, 0.0),
        )
        actual = mejor.get(clave)
        if actual is None or candidato > actual[0]:
            mejor[clave] = (candidato, (score, valor))
    return [v[1] for v in mejor.values()]


def valor_por_ticker(bd: Session, ticker: str) -> Security:
    """El valor de ese ticker, sin distinguir mayusculas. Si no existe, 422."""
    valor = bd.scalars(
        select(Security).where(func.upper(Security.ticker) == ticker.upper()).limit(1)
    ).first()
    if valor is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"no conozco el valor {ticker!r}",
        )
    return valor
