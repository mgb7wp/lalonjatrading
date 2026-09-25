"""Comprobaciones de salud (§46 del encargo).

`/health` responde a "esta el sistema en pie". `/health/data` responde a la
pregunta que de verdad importa en una plataforma de datos: **que datos hay, de
cuando, de que fuente y con que huecos**. Un servicio verde sirviendo scores
calculados con precios de hace tres semanas esta peor que uno caido, porque el
caido se nota.

Nota sobre el codigo de estado: `/health` devuelve 200 aunque una dependencia
este caida, y lo dice en el cuerpo. Un 503 haria que un balanceador sacara del
servicio a una API que todavia puede servir de cache, y ademas dejaria sin
respuesta a quien pregunta *que* esta caido.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import settings
from ...db import session as db
from ...db.models import DataFreshness
from ...db.session import sesion

router = APIRouter(prefix="/health", tags=["health"])

BD = Annotated[Session, Depends(sesion)]

Estado = Literal["ok", "degradado", "caido"]


class Dependencia(BaseModel):
    nombre: str
    estado: Estado
    detalle: str = ""


class Salud(BaseModel):
    estado: Estado
    version: str
    entorno: str
    dependencias: list[Dependencia]


class Frescura(BaseModel):
    dataset: str
    market_id: str
    last_data_date: dt.date | None
    last_success_at: dt.datetime | None
    source: str | None
    securities_covered: int | None
    securities_expected: int | None
    coverage: float | None
    days_behind: int | None
    is_stale: bool


class SaludDatos(BaseModel):
    estado: Estado
    checked_at: dt.datetime
    datasets: list[Frescura]
    stale: list[str]


@router.get("", response_model=Salud, summary="Estado del servicio")
def salud() -> Salud:
    cfg = settings()
    deps: list[Dependencia] = []

    ok_db, error_db = db.comprobar()
    deps.append(
        Dependencia(
            nombre="postgres",
            estado="ok" if ok_db else "caido",
            detalle="" if ok_db else error_db,
        )
    )

    # El nucleo cuantitativo tambien es una dependencia: si su configuracion no
    # valida, la API puede responder pero no puede analizar nada.
    try:
        from estrategia import config as core_config

        c = core_config.cargar()
        n = len(c.reglas.universo.mercados)
        deps.append(Dependencia(nombre="core", estado="ok", detalle=f"{n} mercados configurados"))
    except Exception as e:  # noqa: BLE001
        deps.append(Dependencia(nombre="core", estado="caido", detalle=f"{type(e).__name__}: {e}"))

    caidas = [d for d in deps if d.estado == "caido"]
    if not caidas:
        estado: Estado = "ok"
    elif len(caidas) == len(deps):
        estado = "caido"
    else:
        estado = "degradado"

    return Salud(estado=estado, version=_version(), entorno=cfg.entorno, dependencias=deps)


@router.get(
    "/data",
    response_model=SaludDatos,
    summary="Frescura y cobertura de los datos por mercado",
)
def salud_datos(db: BD) -> SaludDatos:
    """Que datos hay, de cuando y con que huecos.

    Lee `data_freshness`, que el pipeline materializa en cada ejecucion, en
    lugar de hacer un MAX() sobre las series: ese MAX sobre decenas de millones
    de filas particionadas no es una consulta para un endpoint que se llama cada
    quince segundos.

    **Sin datos cargados devuelve `caido`, no `ok`.** Una base de datos vacia no
    es un sistema sano: es uno que aun no ha ingerido nada, y decir lo contrario
    es el tipo de verde que hace que nadie mire.
    """
    hoy = dt.date.today()
    filas = db.scalars(
        select(DataFreshness).order_by(DataFreshness.dataset, DataFreshness.market_id)
    ).all()

    datasets = [
        Frescura(
            dataset=f.dataset,
            market_id=f.market_id,
            last_data_date=f.last_data_date,
            last_success_at=f.last_success_at,
            source=f.source,
            securities_covered=f.securities_covered,
            securities_expected=f.securities_expected,
            coverage=(
                round(f.securities_covered / f.securities_expected, 4)
                if f.securities_covered is not None and f.securities_expected
                else None
            ),
            days_behind=(hoy - f.last_data_date).days if f.last_data_date else None,
            is_stale=f.is_stale,
        )
        for f in filas
    ]

    rancios = [f"{d.dataset}/{d.market_id}" for d in datasets if d.is_stale]
    if not datasets:
        estado: Estado = "caido"
    elif rancios:
        estado = "degradado" if len(rancios) < len(datasets) else "caido"
    else:
        estado = "ok"

    return SaludDatos(
        estado=estado,
        checked_at=dt.datetime.now(dt.UTC),
        datasets=datasets,
        stale=rancios,
    )


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("lalonja")
    except PackageNotFoundError:
        return "desconocida"
