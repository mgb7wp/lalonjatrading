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
from functools import lru_cache
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from ...config import settings
from ...db import session as db
from ...db.models import DataFreshness, Score, Security, Signal
from ...db.models.enums import AssetType
from ...db.models.market_data import FxRate
from ...db.session import sesion

router = APIRouter(prefix="/health", tags=["health"])

BD = Annotated[Session, Depends(sesion)]

Estado = Literal["ok", "degradado", "caido"]

#: Dias hacia atras en que se buscan scores, senales y tipos de cambio. Acota la
#: consulta al indice por fecha para no recorrer el historico entero en cada
#: llamada. Lo que lleve mas que esto sin actualizarse sale sin fecha y rancio.
VENTANA_DIAS = 30

#: Dias hacia atras en que se busca el ultimo dia que tuvo que haber scores. Ni
#: la Semana Santa con un fin de semana deja tantos dias seguidos sin sesion en
#: los cinco mercados a la vez.
DIAS_BUSQUEDA_SESION = 15


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
    #: None en las divisas, que no son de ningun mercado: van por `currency`.
    market_id: str | None
    currency: str | None = None
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
    hoy = _hoy()
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
    datasets += _frescura_calculada(db, hoy)

    rancios = [f"{d.dataset}/{d.market_id or d.currency}" for d in datasets if d.is_stale]
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


def _hoy() -> dt.date:
    """El dia de la comprobacion. Aparte para que los tests lo fijen."""
    return dt.date.today()


@lru_cache(maxsize=8)
def dia_esperado_scores(calendarios: tuple[tuple[str, str], ...], hoy: dt.date) -> dt.date:
    """El ultimo dia ANTERIOR a hoy que tuvo que dejar scores y senales.

    La tarea `scores` corre de lunes a viernes tras el ultimo cierre, y solo si
    ha negociado algun mercado (`workers/runner.py`): un Viernes Santo o un 25
    de diciembre, con los cinco cerrados, no puntua y no es un fallo. Se mira
    hasta ayer y no hoy porque la de hoy corre por la noche; si ya ha corrido,
    la fecha sale posterior a la esperada y cuenta como fresca.

    `calendarios` va como tupla para poder cachearse: construir los calendarios
    de `exchange_calendars` cuesta mas que toda la consulta a la base de datos.
    """
    import exchange_calendars as xc

    inicio = hoy - dt.timedelta(days=DIAS_BUSQUEDA_SESION)
    sesiones: set[dt.date] = set()
    for _, codigo in calendarios:
        cal = xc.get_calendar(codigo, start=str(inicio), end=str(hoy))
        sesiones |= {s.date() for s in cal.sessions}
    candidatos = [d for d in sesiones if d < hoy and d.weekday() < 5]
    # Sin ninguna sesion en quince dias no hay nada que esperar: vale el inicio.
    return max(candidatos, default=inicio)


def festivos_target(ano: int) -> set[dt.date]:
    """Dias sin tipos de referencia del BCE, aparte de los fines de semana.

    Son los festivos del sistema TARGET, fijos desde 2002: Ano Nuevo, Viernes
    Santo, Lunes de Pascua, 1 de mayo, 25 y 26 de diciembre.
    """
    pascua = (pd.Timestamp(ano, 1, 1) + pd.offsets.Easter()).date()
    return {
        dt.date(ano, 1, 1),
        pascua - dt.timedelta(days=2),
        pascua + dt.timedelta(days=1),
        dt.date(ano, 5, 1),
        dt.date(ano, 12, 25),
        dt.date(ano, 12, 26),
    }


def dia_esperado_divisas(hoy: dt.date) -> dt.date:
    """El ultimo dia ANTERIOR a hoy con tipos de referencia del BCE.

    La fuente de divisas es el BCE (`reglas.yaml`), que publica los dias habiles
    TARGET a media tarde; la tarea de divisas lo recoge a las 16:45 de Madrid.
    Hasta ayer y no hoy, por lo mismo que en `dia_esperado_scores`.
    """
    dia = hoy - dt.timedelta(days=1)
    while dia.weekday() >= 5 or dia in festivos_target(dia.year):
        dia -= dt.timedelta(days=1)
    return dia


def _frescura_calculada(db: Session, hoy: dt.date) -> list[Frescura]:
    """Scores y senales por mercado, y divisas por moneda. Ver el encabezado."""
    from estrategia import config as core_config

    cfg = core_config.cargar()
    calendarios = tuple(sorted(cfg.implementacion.calendarios.items()))
    desde = hoy - dt.timedelta(days=VENTANA_DIAS)
    analizable = (Security.active.is_(True), Security.asset_type != AssetType.INDEX.value)

    esperados = dict(
        db.execute(
            select(Security.market_id, func.count()).where(*analizable).group_by(Security.market_id)
        ).all()
    )

    salida: list[Frescura] = []
    esperado = dia_esperado_scores(calendarios, hoy)
    for conjunto, tabla in (("scores", Score), ("senales", Signal)):
        # Cuantos valores de cada mercado tienen dato cada dia de la ventana.
        filas = db.execute(
            select(Security.market_id, tabla.date, func.count(distinct(tabla.security_id)))
            .join(Security, Security.id == tabla.security_id)
            .where(tabla.date >= desde, tabla.date <= hoy, *analizable)
            .group_by(Security.market_id, tabla.date)
        ).all()
        ultimo: dict[str, tuple[dt.date, int]] = {}
        for mercado, fecha, n in filas:
            if mercado not in ultimo or fecha > ultimo[mercado][0]:
                ultimo[mercado] = (fecha, n)
        for mercado, n_esperados in sorted(esperados.items()):
            fecha, cubiertos = ultimo.get(mercado, (None, 0))
            salida.append(
                Frescura(
                    dataset=conjunto,
                    market_id=mercado,
                    last_data_date=fecha,
                    last_success_at=None,
                    source=None,
                    securities_covered=cubiertos,
                    securities_expected=n_esperados,
                    coverage=round(cubiertos / n_esperados, 4) if n_esperados else None,
                    days_behind=(hoy - fecha).days if fecha else None,
                    is_stale=fecha is None or fecha < esperado,
                )
            )

    base = cfg.reglas.cartera.divisa_base
    divisas = sorted({m.divisa for m in cfg.reglas.universo.mercados} - {base})
    ultimas = dict(
        db.execute(
            select(FxRate.quote_currency, func.max(FxRate.date))
            .where(FxRate.base_currency == base, FxRate.date >= desde, FxRate.date <= hoy)
            .group_by(FxRate.quote_currency)
        ).all()
    )
    esperado = dia_esperado_divisas(hoy)
    for divisa in divisas:
        fecha = ultimas.get(divisa)
        salida.append(
            Frescura(
                dataset="divisas",
                market_id=None,
                currency=divisa,
                last_data_date=fecha,
                last_success_at=None,
                source=None,
                securities_covered=None,
                securities_expected=None,
                coverage=None,
                days_behind=(hoy - fecha).days if fecha else None,
                is_stale=fecha is None or fecha < esperado,
            )
        )
    return salida


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("lalonja")
    except PackageNotFoundError:
        return "desconocida"
