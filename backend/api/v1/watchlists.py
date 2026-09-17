"""Listas de seguimiento (FASE 14, §35).

Una watchlist responde a una sola pregunta: **que ha pasado con lo que estoy
mirando**. Por eso cada valor sale con score, variacion de score, variacion de
precio, senal y probabilidad, y no con el analisis completo: para eso ya esta
`/stocks/{ticker}/analysis`, y meter aqui ocho bloques por valor convertiria una
vista de vigilancia en un volcado que nadie lee.

## Una consulta por columna, no una por valor

La tentacion es reutilizar los ayudantes de `stocks.py` en un bucle. Con una
lista PREMIUM de 250 valores eso son mas de mil consultas para pintar una
pantalla. Aqui se hace al reves: **una consulta por columna**, con todos los
valores dentro, y el reparto se hace en memoria. Son cinco consultas tenga la
lista tres valores o doscientos cincuenta.

## Lo que no se puede calcular se declara

Una variacion sin foto anterior sale `None` con su motivo, y **no cero**: un cero
afirma "no se movio", que es una afirmacion sobre datos que no existen. Es la
misma regla de §27 y de las carteras.

La **probabilidad** de §35 viene del modelo estadistico, que D-7 mantiene
bloqueado hasta tener 1.000 valores y 15 anios. La columna existe en la respuesta
y viene con su motivo escrito, en lugar de omitirse: quien consuma la API tiene
que poder ver que ese dato esta previsto y por que esta vacio, no encontrarse un
hueco y suponer que se le olvido a alguien.

## Aqui NO se deduplica

En los rankings, tener a la vez la accion local y su ADR es un defecto (D-12):
la misma empresa ocupa dos puestos y quien construya una cartera se concentra sin
darse cuenta. En una watchlist es una eleccion: si alguien ha puesto las dos
lineas, es que quiere ver las dos. Quitarle una seria decidir por el.
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...db.models import (
    ModelVersion,
    Price,
    Score,
    Security,
    Signal,
    User,
    Watchlist,
    WatchlistItem,
)
from ..deps import BD, Actual, MisLimites, comprobar_cupo

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

MODELO_POR_DEFECTO = "equilibrado"

#: Dias hacia atras de las dos variaciones. El mismo numero que en rankings y en
#: `/stocks/{ticker}/analysis`: "lo que ha cambiado ultimamente" tiene que
#: significar lo mismo en toda la API o las tres pantallas no se pueden comparar.
DIAS_VARIACION = 30

#: Por que no hay probabilidad. Se escribe una vez y se devuelve en cada fila,
#: para que el motivo viaje con el dato que falta y no en la documentacion.
MOTIVO_SIN_PROBABILIDAD = (
    "el modelo estadistico esta bloqueado por la decision D-7 "
    "(hacen falta 1.000 valores y 15 anios de historico)"
)


class Orden(enum.StrEnum):
    """Como se ordena la lista. Vocabulario cerrado, no un nombre de columna.

    Si el cliente pudiera mandar el nombre de un campo, resolverlo acabaria en un
    `getattr` sobre el modelo, que es acceso libre al esquema. Es la misma
    decision que en el screener.
    """

    SCORE = "score"
    VARIACION_SCORE = "variacion_score"
    VARIACION_PRECIO = "variacion_precio"
    TICKER = "ticker"


class ListaNueva(BaseModel):
    nombre: str = Field(default="Seguimiento", min_length=1, max_length=120)


class ListaCambio(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)


class ListaResumen(BaseModel):
    id: int
    nombre: str
    valores: int


class ValorNuevo(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)


class Vigilado(BaseModel):
    """Una fila de §35."""

    ticker: str
    nombre: str
    mercado: str
    sector: str | None

    score: float | None = None
    fecha_score: dt.date | None = None
    #: `None` significa "no se puede calcular", nunca "no se movio". El motivo va
    #: en `motivos`.
    variacion_score: float | None = None
    precio: float | None = None
    fecha_precio: dt.date | None = None
    variacion_precio: float | None = None
    senal: str | None = None
    motivo_senal: str | None = None
    fecha_senal: dt.date | None = None
    probabilidad: float | None = None

    #: Por que falta cada cosa que falta. Un hueco sin explicacion obliga a
    #: adivinar si no hay datos o si algo se ha roto, y esas dos cosas se
    #: atienden distinto.
    motivos: dict[str, str] = Field(default_factory=dict)


class Lista(BaseModel):
    id: int
    nombre: str
    fecha: dt.date
    modelo: str
    dias_variacion: int
    n: int
    valores: list[Vigilado]


# ---------------------------------------------------------------------------
# Piezas compartidas
# ---------------------------------------------------------------------------


def _mia(bd: Session, usuario: User, lista_id: int) -> Watchlist:
    """La lista, si es de quien pregunta. Si no, 404 y no 403.

    Un 403 sobre la lista 41 confirma que la lista 41 existe.
    """
    lista = bd.scalars(
        select(Watchlist).where(Watchlist.id == lista_id, Watchlist.user_id == usuario.id)
    ).first()
    if lista is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lista no encontrada")
    return lista


def _valor_por_ticker(bd: Session, ticker: str) -> Security:
    valor = bd.scalars(
        select(Security).where(func.upper(Security.ticker) == ticker.upper()).limit(1)
    ).first()
    if valor is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"no conozco el valor {ticker!r}",
        )
    return valor


def _ultimos_precios(
    bd: Session, ids: list[int], corte: dt.date
) -> dict[int, tuple[float, dt.date]]:
    """Ultimo cierre de cada valor en o antes del corte, en UNA consulta."""
    if not ids:
        return {}
    ultimo = (
        select(Price.security_id, func.max(Price.date).label("fecha"))
        .where(Price.security_id.in_(ids), Price.date <= corte)
        .group_by(Price.security_id)
        .subquery()
    )
    filas = bd.execute(
        select(Price.security_id, Price.close, Price.date).join(
            ultimo,
            and_(Price.security_id == ultimo.c.security_id, Price.date == ultimo.c.fecha),
        )
    ).all()
    return {sid: (float(cierre), fecha) for sid, cierre, fecha in filas}


def _scores(bd: Session, ids: list[int], version_id: int, dia: dt.date) -> dict[int, Score]:
    if not ids:
        return {}
    filas = bd.scalars(
        select(Score).where(
            Score.model_version_id == version_id,
            Score.date == dia,
            Score.security_id.in_(ids),
        )
    ).all()
    return {s.security_id: s for s in filas}


def _fecha_con_scores(bd: Session, version_id: int, corte: dt.date) -> dt.date | None:
    """Ultima fecha puntuada en o antes del corte. Nunca posterior."""
    return bd.scalars(
        select(Score.date)
        .where(Score.model_version_id == version_id, Score.date <= corte)
        .order_by(Score.date.desc())
        .limit(1)
    ).first()


def _senales(bd: Session, ids: list[int], version_id: int, corte: dt.date) -> dict[int, Signal]:
    """Ultima senal de cada valor en o antes del corte, en UNA consulta."""
    if not ids:
        return {}
    ultima = (
        select(Signal.security_id, func.max(Signal.date).label("fecha"))
        .where(
            Signal.security_id.in_(ids),
            Signal.model_version_id == version_id,
            Signal.date <= corte,
        )
        .group_by(Signal.security_id)
        .subquery()
    )
    filas = bd.scalars(
        select(Signal)
        .join(
            ultima,
            and_(Signal.security_id == ultima.c.security_id, Signal.date == ultima.c.fecha),
        )
        .where(Signal.model_version_id == version_id)
    ).all()
    return {s.security_id: s for s in filas}


def _resumen(bd: Session, lista: Watchlist) -> ListaResumen:
    cuantos = bd.scalar(
        select(func.count())
        .select_from(WatchlistItem)
        .where(WatchlistItem.watchlist_id == lista.id)
    )
    return ListaResumen(id=lista.id, nombre=lista.name, valores=int(cuantos or 0))


# ---------------------------------------------------------------------------
# Listas
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ListaResumen,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una lista de seguimiento",
)
def crear(bd: BD, usuario: Actual, limites: MisLimites, cuerpo: ListaNueva) -> ListaResumen:
    cuantas = bd.scalar(
        select(func.count()).select_from(Watchlist).where(Watchlist.user_id == usuario.id)
    )
    comprobar_cupo(int(cuantas or 0), limites.watchlists, "listas de seguimiento")

    lista = Watchlist(user_id=usuario.id, name=cuerpo.nombre)
    bd.add(lista)
    try:
        bd.commit()
    except IntegrityError as exc:
        bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ya tienes una lista con ese nombre",
        ) from exc
    bd.refresh(lista)
    return ListaResumen(id=lista.id, nombre=lista.name, valores=0)


@router.get("", response_model=list[ListaResumen], summary="Mis listas")
def listar(bd: BD, usuario: Actual) -> list[ListaResumen]:
    cuentas = dict(
        bd.execute(
            select(WatchlistItem.watchlist_id, func.count())
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == usuario.id)
            .group_by(WatchlistItem.watchlist_id)
        ).all()
    )
    listas = bd.scalars(
        select(Watchlist).where(Watchlist.user_id == usuario.id).order_by(Watchlist.id)
    ).all()
    return [ListaResumen(id=w.id, nombre=w.name, valores=int(cuentas.get(w.id, 0))) for w in listas]


@router.patch("/{lista_id}", response_model=ListaResumen, summary="Renombrar una lista")
def modificar(
    bd: BD, usuario: Actual, lista_id: Annotated[int, Path()], cuerpo: ListaCambio
) -> ListaResumen:
    lista = _mia(bd, usuario, lista_id)
    lista.name = cuerpo.nombre
    try:
        bd.commit()
    except IntegrityError as exc:
        bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ya tienes una lista con ese nombre",
        ) from exc
    bd.refresh(lista)
    return _resumen(bd, lista)


@router.delete("/{lista_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Borrar una lista")
def borrar(bd: BD, usuario: Actual, lista_id: Annotated[int, Path()]) -> None:
    lista = _mia(bd, usuario, lista_id)
    bd.delete(lista)
    bd.commit()


# ---------------------------------------------------------------------------
# Valores de la lista
# ---------------------------------------------------------------------------


@router.post(
    "/{lista_id}/items",
    response_model=ListaResumen,
    status_code=status.HTTP_201_CREATED,
    summary="Anadir un valor a la lista",
)
def anadir(
    bd: BD,
    usuario: Actual,
    limites: MisLimites,
    lista_id: Annotated[int, Path()],
    cuerpo: ValorNuevo,
) -> ListaResumen:
    lista = _mia(bd, usuario, lista_id)
    valor = _valor_por_ticker(bd, cuerpo.ticker)

    cuantos = bd.scalar(
        select(func.count())
        .select_from(WatchlistItem)
        .where(WatchlistItem.watchlist_id == lista.id)
    )
    comprobar_cupo(int(cuantos or 0), limites.valores_por_watchlist, "valores por lista")

    bd.add(WatchlistItem(watchlist_id=lista.id, security_id=valor.id))
    try:
        bd.commit()
    except IntegrityError as exc:
        bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{valor.ticker} ya esta en esta lista",
        ) from exc
    return _resumen(bd, lista)


@router.delete(
    "/{lista_id}/items/{ticker}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar un valor de la lista",
)
def quitar(
    bd: BD, usuario: Actual, lista_id: Annotated[int, Path()], ticker: Annotated[str, Path()]
) -> None:
    lista = _mia(bd, usuario, lista_id)
    valor = _valor_por_ticker(bd, ticker)
    fila = bd.scalars(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == lista.id, WatchlistItem.security_id == valor.id
        )
    ).first()
    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{valor.ticker} no esta en esta lista"
        )
    bd.delete(fila)
    bd.commit()


# ---------------------------------------------------------------------------
# La vista de §35
# ---------------------------------------------------------------------------


@router.get("/{lista_id}", response_model=Lista, summary="La lista con score, variaciones y senal")
def ver(
    bd: BD,
    usuario: Actual,
    lista_id: Annotated[int, Path()],
    fecha: Annotated[dt.date | None, Query(description="Corte temporal")] = None,
    modelo: Annotated[str, Query(description="Perfil de pesos de §18")] = MODELO_POR_DEFECTO,
    orden: Annotated[Orden, Query(description="Como ordenar la lista")] = Orden.SCORE,
) -> Lista:
    lista = _mia(bd, usuario, lista_id)
    corte = fecha or dt.date.today()

    valores = bd.scalars(
        select(Security)
        .join(WatchlistItem, WatchlistItem.security_id == Security.id)
        .where(WatchlistItem.watchlist_id == lista.id)
    ).all()
    ids = [v.id for v in valores]

    version = bd.scalars(
        select(ModelVersion.id)
        .where(ModelVersion.name == modelo)
        .order_by(ModelVersion.id.desc())
        .limit(1)
    ).first()

    dia = _fecha_con_scores(bd, version, corte) if version else None
    # La foto anterior se busca desde `dia` y no desde `corte`: si el ultimo
    # calculo es de hace una semana, comparar contra hace 30 dias naturales
    # mediria 37 dias y no 30. La variacion tiene que significar lo mismo
    # siempre.
    dia_previo = (
        _fecha_con_scores(bd, version, dia - dt.timedelta(days=DIAS_VARIACION))
        if version and dia
        else None
    )

    ahora = _scores(bd, ids, version, dia) if version and dia else {}
    antes = (
        _scores(bd, ids, version, dia_previo)
        if version and dia_previo and dia_previo != dia
        else {}
    )
    precios = _ultimos_precios(bd, ids, corte)
    precios_previos = _ultimos_precios(bd, ids, corte - dt.timedelta(days=DIAS_VARIACION))
    senales = _senales(bd, ids, version, corte) if version else {}

    filas: list[Vigilado] = []
    for v in valores:
        motivos: dict[str, str] = {}
        fila = Vigilado(ticker=v.ticker, nombre=v.name, mercado=v.market_id, sector=v.sector)

        s = ahora.get(v.id)
        if s is None:
            motivos["score"] = f"no está puntuado por el modelo '{modelo}'"
        else:
            fila.score = float(s.overall)
            fila.fecha_score = s.date
            previo = antes.get(v.id)
            if previo is None:
                motivos["variacion_score"] = (
                    "no hay una puntuación anterior con la que comparar"
                    if dia_previo
                    else f"no hay puntuaciones de hace {DIAS_VARIACION} días"
                )
            else:
                fila.variacion_score = round(float(s.overall) - float(previo.overall), 2)

        p = precios.get(v.id)
        if p is None:
            motivos["precio"] = "no hay precios cargados para este valor"
        else:
            fila.precio, fila.fecha_precio = p
            pp = precios_previos.get(v.id)
            if pp is None or pp[1] == p[1] or pp[0] == 0:
                motivos["variacion_precio"] = (
                    f"no hay un cierre anterior con el que comparar a {DIAS_VARIACION} días"
                )
            else:
                fila.variacion_precio = round((p[0] - pp[0]) / pp[0] * 100, 2)

        sig = senales.get(v.id)
        if sig is None:
            motivos["senal"] = f"no hay señal emitida por el modelo '{modelo}'"
        else:
            fila.senal = sig.signal
            fila.motivo_senal = sig.reason
            fila.fecha_senal = sig.date

        # Siempre presente y siempre con motivo: la columna existe, el dato no.
        motivos["probabilidad"] = MOTIVO_SIN_PROBABILIDAD

        fila.motivos = motivos
        filas.append(fila)

    filas.sort(key=_clave(orden))

    return Lista(
        id=lista.id,
        nombre=lista.name,
        fecha=corte,
        modelo=modelo,
        dias_variacion=DIAS_VARIACION,
        n=len(filas),
        valores=filas,
    )


def _clave(orden: Orden):
    """Ordena, dejando SIEMPRE al final lo que no tiene el dato.

    Sin eso, un `None` tratado como cero coloca a los valores sin puntuar en
    medio de la tabla, como si hubieran sacado un 0 —que en un percentil
    significa "el peor de su cohorte"— en lugar de no tener nota.
    """
    if orden is Orden.TICKER:
        return lambda f: f.ticker

    campo = {
        Orden.SCORE: "score",
        Orden.VARIACION_SCORE: "variacion_score",
        Orden.VARIACION_PRECIO: "variacion_precio",
    }[orden]
    return lambda f: (getattr(f, campo) is None, -(getattr(f, campo) or 0), f.ticker)
