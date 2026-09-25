"""Rankings (§32): las diez vistas ordenadas del universo.

## Que es configuracion y que no

Los umbrales de decision viven en `reglas.yaml` porque una senal es una
recomendacion publicada. Un ranking no: es una vista ordenada, y su definicion
—"por score descendente", "por caida del score"— es su identidad, no un
parametro que alguien vaya a ajustar. Por eso el catalogo esta aqui, en una
enumeracion cerrada, y no en el YAML: moverlo alli daria a entender que cambiar
lo que significa "most improved" es una operacion rutinaria.

## La deduplicacion no es un adorno (D-12)

Si el universo tiene a la vez `VALE3.SA` y su ADR `VALE`, la misma empresa
aparece dos veces en el top 20 y quien construya una cartera con eso se
concentra sin darse cuenta. Se agrupa por `company_id` y se conserva una sola
linea: la principal, y si hay empate, la de mas volumen.

## El corte temporal

Igual que en `/stocks/{ticker}/analysis`: nada posterior a `fecha` entra. Un
ranking que mira el futuro es la forma mas facil de que un backtest salga
precioso, y §32 se consulta tambien sobre fechas pasadas.
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from ...db.models import ModelVersion, Price, Score, Security
from ...db.models.enums import AssetType
from ...db.session import sesion

router = APIRouter(prefix="/rankings", tags=["rankings"])

BD = Annotated[Session, Depends(sesion)]

#: Dias hacia atras para los rankings de variacion, igual que en senales y en
#: el endpoint de analisis. Un solo numero para "lo que ha cambiado ultimamente".
DIAS_VARIACION = 30

TOPE_MAXIMO = 100


class Ranking(enum.StrEnum):
    """Las diez vistas de §32."""

    MEJOR_SCORE = "mejor_score"
    PEOR_SCORE = "peor_score"
    MAS_MEJORADO = "mas_mejorado"
    MAYOR_CAIDA = "mayor_caida"
    MEJOR_FUNDAMENTAL = "mejor_fundamental"
    MEJOR_TECNICO = "mejor_tecnico"
    MEJOR_MOMENTUM = "mejor_momentum"
    MENOR_RIESGO = "menor_riesgo"
    MEJOR_VALORACION = "mejor_valoracion"
    MEJOR_CALIDAD = "mejor_calidad"


#: Que columna ordena cada ranking y en que sentido. Las de variacion no tienen
#: columna: se calculan comparando dos fechas y llevan su propio camino.
COLUMNA = {
    Ranking.MEJOR_SCORE: (Score.overall, True),
    Ranking.PEOR_SCORE: (Score.overall, False),
    Ranking.MEJOR_FUNDAMENTAL: (Score.fundamental, True),
    Ranking.MEJOR_TECNICO: (Score.technical, True),
    Ranking.MEJOR_MOMENTUM: (Score.momentum, True),
    Ranking.MENOR_RIESGO: (Score.risk, True),
    Ranking.MEJOR_VALORACION: (Score.valuation, True),
    Ranking.MEJOR_CALIDAD: (Score.quality, True),
}

VARIACION = {Ranking.MAS_MEJORADO: True, Ranking.MAYOR_CAIDA: False}


class Puesto(BaseModel):
    posicion: int
    ticker: str
    nombre: str
    mercado: str
    sector: str | None = None
    valor: float
    overall: float | None = None
    #: Solo en los rankings de variacion: de donde venia.
    anterior: float | None = None


class RespuestaRanking(BaseModel):
    ranking: str
    fecha: dt.date
    #: La fecha del score que se ha usado, que puede ser anterior a `fecha` si
    #: ese dia no se puntuo. Sin esto, un ranking de hace tres semanas se lee
    #: como si fuera de hoy.
    fecha_datos: dt.date | None
    modelo: str
    mercado: str | None
    n: int
    puestos: list[Puesto]


def _version(bd: Session, modelo: str) -> ModelVersion | None:
    return bd.scalars(
        select(ModelVersion).where(ModelVersion.name == modelo).order_by(ModelVersion.id.desc())
    ).first()


def _fecha_datos(bd: Session, version_id: int, corte: dt.date) -> dt.date | None:
    """Ultima fecha con scores en o antes del corte. Nunca posterior."""
    return bd.scalars(
        select(Score.date)
        .where(Score.model_version_id == version_id, Score.date <= corte)
        .order_by(Score.date.desc())
        .limit(1)
    ).first()


def _base(version_id: int, fecha: dt.date, mercado: str | None) -> Select:
    """Scores de esa fecha unidos a su valor, ya sin indices ni bajas."""
    consulta = (
        select(Score, Security)
        .join(Security, Security.id == Score.security_id)
        .where(
            Score.model_version_id == version_id,
            Score.date == fecha,
            Security.active.is_(True),
            Security.asset_type != AssetType.INDEX.value,
        )
    )
    if mercado:
        consulta = consulta.where(Security.market_id == mercado)
    return consulta


def _volumenes(bd: Session, fecha: dt.date) -> dict[int, float]:
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


def _deduplicar(filas: list, volumenes: dict[int, float]) -> list:
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


def _puesto(i: int, score: Score, valor: Security, valor_ordenado, anterior=None) -> Puesto:
    return Puesto(
        posicion=i,
        ticker=valor.ticker,
        nombre=valor.name,
        mercado=valor.market_id,
        sector=valor.sector,
        valor=round(float(valor_ordenado), 2),
        overall=None if score.overall is None else float(score.overall),
        anterior=None if anterior is None else round(float(anterior), 2),
    )


@router.get("", response_model=RespuestaRanking, summary="Un ranking del universo (§32)")
def ranking(
    bd: BD,
    tipo: Annotated[Ranking, Query(description="Cual de las diez vistas")] = Ranking.MEJOR_SCORE,
    mercado: Annotated[str | None, Query(description="Acota a un mercado")] = None,
    n: Annotated[int, Query(ge=1, le=TOPE_MAXIMO, description="Cuantos puestos")] = 20,
    fecha: Annotated[dt.date | None, Query(description="Corte temporal")] = None,
    modelo: Annotated[str, Query(description="Perfil de pesos de §18")] = "equilibrado",
) -> RespuestaRanking:
    corte = fecha or dt.date.today()
    vacio = RespuestaRanking(
        ranking=str(tipo),
        fecha=corte,
        fecha_datos=None,
        modelo=modelo,
        mercado=mercado,
        n=0,
        puestos=[],
    )

    version = _version(bd, modelo)
    if version is None:
        raise HTTPException(status_code=404, detail=f"no existe el modelo '{modelo}'")

    dia = _fecha_datos(bd, version.id, corte)
    if dia is None:
        return vacio

    filas = [(s, v) for s, v in bd.execute(_base(version.id, dia, mercado)).all()]
    if not filas:
        return vacio

    volumenes = _volumenes(bd, dia)
    filas = _deduplicar(filas, volumenes)

    if tipo in VARIACION:
        previo_dia = _fecha_datos(bd, version.id, dia - dt.timedelta(days=DIAS_VARIACION))
        if previo_dia is None or previo_dia == dia:
            # Sin dos fotos no hay variacion. Devolver el ranking por score seria
            # responder otra pregunta sin avisar.
            return RespuestaRanking(
                ranking=str(tipo),
                fecha=corte,
                fecha_datos=dia,
                modelo=modelo,
                mercado=mercado,
                n=0,
                puestos=[],
            )
        previos = {
            s.security_id: s.overall
            for s, _ in bd.execute(_base(version.id, previo_dia, mercado)).all()
        }
        con_variacion = []
        for score, valor in filas:
            antes = previos.get(score.security_id)
            if antes is None or score.overall is None:
                continue
            con_variacion.append((float(score.overall) - float(antes), score, valor, antes))
        con_variacion.sort(key=lambda x: -x[0] if VARIACION[tipo] else x[0])
        puestos = [
            _puesto(i, score, valor, delta, antes)
            for i, (delta, score, valor, antes) in enumerate(con_variacion[:n], start=1)
        ]
        return RespuestaRanking(
            ranking=str(tipo),
            fecha=corte,
            fecha_datos=dia,
            modelo=modelo,
            mercado=mercado,
            n=len(puestos),
            puestos=puestos,
        )

    columna, descendente = COLUMNA[tipo]
    nombre = columna.key
    ordenadas = [(s, v) for s, v in filas if getattr(s, nombre) is not None]
    ordenadas.sort(key=lambda x: float(getattr(x[0], nombre)), reverse=descendente)
    puestos = [
        _puesto(i, score, valor, getattr(score, nombre))
        for i, (score, valor) in enumerate(ordenadas[:n], start=1)
    ]
    return RespuestaRanking(
        ranking=str(tipo),
        fecha=corte,
        fecha_datos=dia,
        modelo=modelo,
        mercado=mercado,
        n=len(puestos),
        puestos=puestos,
    )


@router.get("/catalogo", response_model=list[str], summary="Los rankings disponibles")
def catalogo() -> list[str]:
    """Para que un cliente no tenga que llevar la lista escrita a mano."""
    return [str(r) for r in Ranking]
