"""Explicación con IA de un valor (FASE 16, §12).

`GET /stocks/{ticker}/explanation` devuelve la explicación redactada por el LLM
como un bloque más de la ficha: con su disponibilidad, su motivo cuando no la
hay y su frescura. Lo que la IA recibió viaja en la respuesta (`entrada`), para
que cualquiera pueda comprobar que cada cifra del texto sale de ahí.

El orden de las comprobaciones es el del coste, de lo gratis a lo caro:

1. plan (FREE no tiene explicaciones: SECURITY.md, límites de plan);
2. ¿hay score? Sin score no hay nada que explicar y no se llama a nadie;
3. caché por `(valor, fecha del score, hash de la entrada)`: si está, se sirve
   y no gasta cupo;
4. ¿hay modelo configurado?;
5. cupo diario, que se descuenta antes de llamar;
6. la llamada, y el validador. Lo que no pasa no se guarda ni se publica.
"""

from __future__ import annotations

import datetime as dt
import logging
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ... import explicaciones as ia
from ...config import settings
from ...db.models import Explanation, Security
from ...db.session import sesion
from ...limites import gastar_explicacion_ia
from ..deps import Actual, MisLimites
from .stocks import (
    DIAS_CAMBIO,
    Bloque,
    Valor,
    _bloque_explicacion,
    _bloque_score,
    _bloque_senal,
    _score_en,
)

log = logging.getLogger("explicaciones")

router = APIRouter(prefix="/stocks", tags=["ia"])

BD = Annotated[Session, Depends(sesion)]


@lru_cache
def _redactor_configurado() -> ia.Redactor | None:
    cfg = settings()
    if not cfg.anthropic_api_key:
        return None
    return ia.RedactorClaude(cfg.anthropic_api_key, cfg.llm_modelo, cfg.llm_timeout_segundos)


def redactor() -> ia.Redactor | None:
    """Dependencia: el LLM, o `None` si este despliegue no tiene clave."""
    return _redactor_configurado()


Redactor = Annotated[ia.Redactor | None, Depends(redactor)]


class ExplicacionIA(BaseModel):
    """La explicación publicada. Sin una sola cifra que no esté en `entrada`."""

    resumen: str
    a_favor: list[str]
    en_contra: list[str]
    cambios: list[str]
    preguntas: list[str]
    fecha_score: dt.date
    modelo_llm: str | None
    generada: dt.datetime
    desde_cache: bool
    #: Exactamente lo que recibió el LLM. Publicarlo es lo que convierte "la IA
    #: no inventa" en algo que el lector puede comprobar por sí mismo.
    entrada: dict[str, Any]


class RespuestaExplicacion(BaseModel):
    ticker: str
    fecha_corte: dt.date
    explicacion: Bloque[ExplicacionIA]


def _publicar(fila: Explanation, entrada: dict[str, Any], desde_cache: bool) -> ExplicacionIA:
    return ExplicacionIA(
        resumen=fila.summary or "",
        a_favor=list(fila.positives or []),
        en_contra=list(fila.negatives or []),
        cambios=list(fila.recent_changes or []),
        preguntas=list(fila.questions or []),
        fecha_score=fila.date,
        modelo_llm=fila.llm_model,
        generada=fila.created_at,
        desde_cache=desde_cache,
        entrada=entrada,
    )


def _en_cache(bd: Session, valor_id: int, fecha: dt.date, clave: str) -> Explanation | None:
    return bd.scalars(
        select(Explanation).where(
            Explanation.security_id == valor_id,
            Explanation.date == fecha,
            Explanation.score_hash == clave,
            Explanation.language == ia.IDIOMA,
        )
    ).first()


@router.get(
    "/{ticker}/explanation",
    response_model=RespuestaExplicacion,
    summary="Explicación con IA del score de un valor (§12)",
)
def explicacion(
    ticker: str,
    bd: BD,
    usuario: Actual,
    limites: MisLimites,
    llm: Redactor,
    fecha: Annotated[
        dt.date | None,
        Query(description="Corte temporal: nada posterior a esta fecha entra en la explicación"),
    ] = None,
    modelo: Annotated[str, Query(description="Perfil de pesos de §18")] = "equilibrado",
) -> RespuestaExplicacion:
    if limites.explicaciones_ia_al_dia <= 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="las explicaciones con IA necesitan el plan pro o superior",
        )

    corte = fecha or dt.date.today()
    valor = bd.scalars(select(Security).where(Security.ticker == ticker.upper())).first()
    if valor is None:
        raise HTTPException(status_code=404, detail=f"no existe el valor {ticker}")

    def respuesta(bloque: Bloque[ExplicacionIA]) -> RespuestaExplicacion:
        return RespuestaExplicacion(ticker=valor.ticker, fecha_corte=corte, explicacion=bloque)

    puntuacion = _score_en(bd, valor, modelo, corte)
    score = _bloque_score(puntuacion, modelo, corte)
    if puntuacion is None or score.datos is None:
        return respuesta(Bloque.falta("sin score no hay nada que explicar"))

    senal = _bloque_senal(bd, valor, modelo, corte)
    exp = _bloque_explicacion(bd, valor, puntuacion, modelo, corte)
    entrada = ia.construir_entrada(
        valor=Valor.model_validate(valor).model_dump(),
        score=score.datos.model_dump(),
        explicacion=exp.datos.model_dump() if exp.datos else None,
        senal=senal.datos.model_dump() if senal.datos else None,
        motivo_sin_senal=senal.motivo,
        dias_cambio=DIAS_CAMBIO,
    )
    clave = ia.hash_entrada(entrada)

    guardada = _en_cache(bd, valor.id, puntuacion.date, clave)
    if guardada is not None:
        return respuesta(Bloque.con(_publicar(guardada, entrada, True), puntuacion.date, corte))

    if llm is None:
        return respuesta(Bloque.falta("la capa de IA no está configurada en este despliegue"))

    gastar_explicacion_ia(usuario.id, limites.explicaciones_ia_al_dia)

    try:
        redaccion = ia.redactar(llm, entrada)
    except ia.ExplicacionRechazada as exc:
        # No se guarda: la próxima petición lo vuelve a intentar. Guardar el
        # rechazo ahorraría dinero a costa de dejar el valor sin explicación
        # para siempre por un mal intento.
        log.warning("%s: explicacion rechazada: %s", valor.ticker, exc)
        return respuesta(
            Bloque.falta(
                "la explicación generada no superó la validación (una cifra que no estaba "
                "en el análisis o un dato ausente sin declarar) y se ha descartado; no se "
                "publica un texto que no se pueda comprobar"
            )
        )
    except ia.ErrorRedactor as exc:
        log.error("%s: sin explicacion: %s", valor.ticker, exc)
        return respuesta(
            Bloque.falta("el servicio de IA no ha respondido; inténtalo en un momento")
        )

    fila = Explanation(
        security_id=valor.id,
        date=puntuacion.date,
        score_hash=clave,
        language=ia.IDIOMA,
        summary=redaccion.resumen,
        positives=redaccion.a_favor,
        negatives=redaccion.en_contra,
        recent_changes=redaccion.cambios,
        questions=redaccion.preguntas,
        llm_model=redaccion.modelo_llm,
    )
    bd.add(fila)
    try:
        bd.commit()
    except IntegrityError:
        # Dos peticiones a la vez para el mismo valor: la otra llegó antes. Se
        # sirve la suya, que ha pasado el mismo validador.
        bd.rollback()
        fila = _en_cache(bd, valor.id, puntuacion.date, clave)
        if fila is None:
            raise
        return respuesta(Bloque.con(_publicar(fila, entrada, True), puntuacion.date, corte))
    bd.refresh(fila)
    return respuesta(Bloque.con(_publicar(fila, entrada, False), puntuacion.date, corte))
