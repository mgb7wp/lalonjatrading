"""Mercados y sus calendarios.

Es el endpoint mas pequeno que demuestra la regla que sostiene el resto: los
mercados **no estan en el codigo**. Salen de `config/*.yaml` a traves del
nucleo, de modo que anadir Francia es una fila de YAML y no un despliegue. §3
del encargo lo exige y aqui se comprueba de verdad.

En la FASE 2 esta lectura pasara a venir de la tabla `market`, poblada desde el
mismo YAML. El contrato de salida no cambiara.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/markets", tags=["markets"])


class Market(BaseModel):
    id: str
    currency: str
    classification: str
    ticker_suffix: str
    trading_calendar: str
    benchmark: str | None
    securities: int


def _mercados() -> list[Market]:
    from estrategia import config as core_config

    cfg = core_config.cargar()
    indices = cfg.reglas.tecnico.indices_regimen
    return [
        Market(
            id=m.id,
            currency=m.divisa,
            classification=m.clasificacion,
            ticker_suffix=m.sufijo,
            trading_calendar=cfg.implementacion.calendarios[m.id],
            benchmark=indices.get(m.id),
            securities=len(cfg.universo.tickers(m.id)),
        )
        for m in cfg.reglas.universo.mercados
    ]


@router.get("", response_model=list[Market], summary="Mercados configurados")
def listar() -> list[Market]:
    return _mercados()


@router.get("/{market_id}", response_model=Market, summary="Un mercado")
def obtener(market_id: str) -> Market:
    for m in _mercados():
        if m.id == market_id:
            return m
    raise HTTPException(status_code=404, detail=f"mercado desconocido: {market_id}")
