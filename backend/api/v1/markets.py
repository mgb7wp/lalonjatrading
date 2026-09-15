"""Mercados y sus calendarios.

Desde la FASE 2 los mercados salen de la tabla `market`, poblada desde
`config/*.yaml` por `backend.db.seed`. El contrato de salida es el mismo que
cuando se leia la configuracion en caliente, que era la promesa.

Lo que no cambia es la exigencia de §3 del encargo: ningun mercado esta escrito
en el codigo. Anadir Francia sigue siendo configuracion mas una recarga de
referencia, no un despliegue.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db.models import Market as MarketRow
from ...db.models import Security
from ...db.session import sesion

router = APIRouter(prefix="/markets", tags=["markets"])

#: Una sesion por peticion, inyectada por FastAPI.
BD = Annotated[Session, Depends(sesion)]


class Market(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    country_code: str
    currency: str
    classification: str
    ticker_suffix: str
    trading_calendar: str
    timezone: str
    benchmark: str | None
    # Que el benchmark incluya dividendos o no decide si el target de un modelo
    # esta sesgado (decision D-5), asi que se publica en lugar de esconderse en
    # una tabla de configuracion.
    benchmark_is_total_return: bool
    securities: int


def _consulta():
    """Mercados con el numero de valores activos de cada uno.

    LEFT JOIN y no una subconsulta por fila: son cinco mercados hoy, pero el
    patron de N+1 consultas se hereda a los sitios que se copian de aqui.
    """
    return (
        select(
            MarketRow,
            func.count(Security.id).filter(Security.active.is_(True)).label("securities"),
        )
        .outerjoin(Security, Security.market_id == MarketRow.id)
        .group_by(MarketRow.id)
        .order_by(MarketRow.id)
    )


def _a_esquema(fila: MarketRow, valores: int) -> Market:
    return Market(
        id=fila.id,
        name=fila.name,
        country_code=fila.country_code,
        currency=fila.currency_code,
        classification=fila.classification,
        ticker_suffix=fila.ticker_suffix,
        trading_calendar=fila.trading_calendar,
        timezone=fila.timezone,
        benchmark=fila.benchmark_symbol,
        benchmark_is_total_return=fila.benchmark_is_total_return,
        securities=valores,
    )


@router.get("", response_model=list[Market], summary="Mercados configurados")
def listar(db: BD) -> list[Market]:
    return [_a_esquema(m, n) for m, n in db.execute(_consulta()).all()]


@router.get("/{market_id}", response_model=Market, summary="Un mercado")
def obtener(market_id: str, db: BD) -> Market:
    fila = db.execute(_consulta().where(MarketRow.id == market_id)).first()
    if fila is None:
        raise HTTPException(status_code=404, detail=f"mercado desconocido: {market_id}")
    return _a_esquema(*fila)
