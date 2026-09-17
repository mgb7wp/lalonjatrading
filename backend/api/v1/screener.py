"""Screener (§31): filtros combinados sobre el universo puntuado.

## Por que hay una lista blanca de campos y no `getattr`

El cliente manda nombres de campo. Resolverlos con `getattr(Score, campo)` o
interpolarlos en SQL convierte una peticion en acceso arbitrario al esquema:
`created_at`, columnas de otras tablas por relacion, o directamente inyeccion.
`CAMPOS` es un diccionario explicito de nombre publico -> columna, y lo que no
esta en el se rechaza con un 400 que dice cuales valen. Es mas verboso y es la
diferencia entre un filtro y un agujero.

Los valores siempre viajan como parametros ligados, nunca concatenados.

## Deduplicacion y corte

Igual que en los rankings: una linea por empresa (D-12) y nada posterior a la
fecha de corte. Un screener que devuelve dos veces la misma empresa infla el
resultado, y uno que mira el futuro no sirve para estudiar el pasado.
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import ModelVersion, Score, Security, Signal
from ...db.models.enums import AssetType
from ...db.session import sesion
from .rankings import _deduplicar, _fecha_datos, _volumenes

router = APIRouter(prefix="/screener", tags=["screener"])

BD = Annotated[Session, Depends(sesion)]

TOPE_MAXIMO = 200

#: Nombre publico -> columna. Lista blanca: lo que no este aqui se rechaza.
CAMPOS: dict[str, Any] = {
    "overall": Score.overall,
    "fundamental": Score.fundamental,
    "tecnico": Score.technical,
    "sentimiento": Score.sentiment,
    "riesgo": Score.risk,
    "crecimiento": Score.growth,
    "rentabilidad": Score.profitability,
    "salud_financiera": Score.financial_health,
    "calidad": Score.quality,
    "valoracion": Score.valuation,
    "momentum": Score.momentum,
    "tendencia": Score.trend,
    "volatilidad": Score.volatility,
    "volumen": Score.volume,
    "n_cohorte": Score.n_cohort,
}

#: Campos de texto del valor, que se filtran por igualdad o pertenencia.
CAMPOS_TEXTO: dict[str, Any] = {
    "mercado": Security.market_id,
    "sector": Security.sector,
    "divisa": Security.currency_code,
}


class Operador(enum.StrEnum):
    MAYOR = "gt"
    MAYOR_IGUAL = "gte"
    MENOR = "lt"
    MENOR_IGUAL = "lte"
    IGUAL = "eq"
    DISTINTO = "ne"
    ENTRE = "between"
    EN = "in"


class Filtro(BaseModel):
    campo: str
    operador: Operador
    #: Un numero, un texto, o una lista para `between` e `in`.
    valor: Any


class Peticion(BaseModel):
    filtros: list[Filtro] = Field(default_factory=list)
    orden: str = "overall"
    descendente: bool = True
    n: int = Field(default=50, ge=1, le=TOPE_MAXIMO)
    fecha: dt.date | None = None
    modelo: str = "equilibrado"
    #: Se puede pedir sin deduplicar para auditar el propio universo, pero el
    #: valor por defecto es el correcto (D-12).
    deduplicar: bool = True


class Fila(BaseModel):
    ticker: str
    nombre: str
    mercado: str
    sector: str | None = None
    overall: float | None = None
    senal: str | None = None
    campos: dict[str, float | None]


class Respuesta(BaseModel):
    fecha: dt.date
    fecha_datos: dt.date | None
    modelo: str
    n: int
    #: Cuantos cumplian antes de recortar a `n`. Sin esto, "20 resultados" no
    #: distingue "solo hay 20" de "hay 400 y te enseno los primeros".
    total: int
    filas: list[Fila]


def _condicion(f: Filtro):
    columna = CAMPOS.get(f.campo) or CAMPOS_TEXTO.get(f.campo)
    if columna is None:
        validos = ", ".join(sorted([*CAMPOS, *CAMPOS_TEXTO]))
        raise HTTPException(
            status_code=400, detail=f"campo desconocido '{f.campo}'. Validos: {validos}"
        )

    if f.operador is Operador.ENTRE:
        if not isinstance(f.valor, list | tuple) or len(f.valor) != 2:
            raise HTTPException(
                status_code=400, detail=f"'between' sobre '{f.campo}' necesita [minimo, maximo]"
            )
        return columna.between(f.valor[0], f.valor[1])
    if f.operador is Operador.EN:
        if not isinstance(f.valor, list | tuple) or not f.valor:
            raise HTTPException(
                status_code=400, detail=f"'in' sobre '{f.campo}' necesita una lista no vacia"
            )
        return columna.in_(list(f.valor))

    comparadores = {
        Operador.MAYOR: columna.__gt__,
        Operador.MAYOR_IGUAL: columna.__ge__,
        Operador.MENOR: columna.__lt__,
        Operador.MENOR_IGUAL: columna.__le__,
        Operador.IGUAL: columna.__eq__,
        Operador.DISTINTO: columna.__ne__,
    }
    return comparadores[f.operador](f.valor)


@router.post("", response_model=Respuesta, summary="Filtros combinados sobre el universo (§31)")
def filtrar(peticion: Peticion, bd: BD) -> Respuesta:
    corte = peticion.fecha or dt.date.today()

    version = bd.scalars(
        select(ModelVersion)
        .where(ModelVersion.name == peticion.modelo)
        .order_by(ModelVersion.id.desc())
    ).first()
    if version is None:
        raise HTTPException(status_code=404, detail=f"no existe el modelo '{peticion.modelo}'")

    if peticion.orden not in CAMPOS:
        raise HTTPException(
            status_code=400,
            detail=f"no se puede ordenar por '{peticion.orden}'. Validos: "
            f"{', '.join(sorted(CAMPOS))}",
        )

    dia = _fecha_datos(bd, version.id, corte)
    if dia is None:
        return Respuesta(
            fecha=corte, fecha_datos=None, modelo=peticion.modelo, n=0, total=0, filas=[]
        )

    consulta = (
        select(Score, Security)
        .join(Security, Security.id == Score.security_id)
        .where(
            Score.model_version_id == version.id,
            Score.date == dia,
            Security.active.is_(True),
            Security.asset_type != AssetType.INDEX.value,
        )
    )
    for f in peticion.filtros:
        consulta = consulta.where(_condicion(f))

    filas = [(s, v) for s, v in bd.execute(consulta).all()]
    if peticion.deduplicar:
        filas = _deduplicar(filas, _volumenes(bd, dia))

    columna = CAMPOS[peticion.orden].key
    conocidos = [(s, v) for s, v in filas if getattr(s, columna) is not None]
    conocidos.sort(key=lambda x: float(getattr(x[0], columna)), reverse=peticion.descendente)
    total = len(conocidos)
    recorte = conocidos[: peticion.n]

    senales = {
        s.security_id: s.signal
        for s in bd.scalars(
            select(Signal).where(
                Signal.model_version_id == version.id,
                Signal.date == dia,
                Signal.security_id.in_([v.id for _, v in recorte]) if recorte else False,
            )
        ).all()
    }

    return Respuesta(
        fecha=corte,
        fecha_datos=dia,
        modelo=peticion.modelo,
        n=len(recorte),
        total=total,
        filas=[
            Fila(
                ticker=v.ticker,
                nombre=v.name,
                mercado=v.market_id,
                sector=v.sector,
                overall=None if s.overall is None else float(s.overall),
                senal=senales.get(v.id),
                campos={
                    nombre: (None if getattr(s, col.key) is None else float(getattr(s, col.key)))
                    for nombre, col in CAMPOS.items()
                },
            )
            for s, v in recorte
        ],
    )


@router.get("/campos", response_model=dict[str, list[str]], summary="Campos y operadores")
def campos() -> dict[str, list[str]]:
    """Para que un cliente descubra que se puede filtrar sin leer el codigo."""
    return {
        "numericos": sorted(CAMPOS),
        "texto": sorted(CAMPOS_TEXTO),
        "operadores": [str(o) for o in Operador],
    }
