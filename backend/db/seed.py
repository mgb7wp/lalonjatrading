"""Carga de los datos de referencia: paises, divisas, mercados, bolsas y valores.

Idempotente por UPSERT sobre la clave natural (decision D-9): ejecutarlo dos
veces no duplica nada y no cambia nada. Es la unica forma de que forme parte del
arranque de un despliegue sin miedo.

Las fuentes son la configuracion del motor (`config/reglas.yaml`,
`universo.yaml`, `implementacion.yaml`) y `config/referencia.yaml`. Ningun dato
sale de este fichero: si hace falta uno nuevo, va al YAML.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .models import Country, Currency, Exchange, Market, Security
from .models.enums import AssetType, MarketClassification

RAIZ = Path(__file__).resolve().parents[2]
REFERENCIA = RAIZ / "config" / "referencia.yaml"

#: Traduce la clasificacion del motor al vocabulario del esquema.
CLASIFICACION = {
    "desarrollado": MarketClassification.DEVELOPED.value,
    "emergente": MarketClassification.EMERGING.value,
}


@dataclass
class Resumen:
    """Que hizo la carga. Se imprime y se comprueba en los tests."""

    paises: int = 0
    divisas: int = 0
    mercados: int = 0
    bolsas: int = 0
    valores: int = 0

    def __str__(self) -> str:
        return (
            f"{self.paises} paises, {self.divisas} divisas, {self.mercados} mercados, "
            f"{self.bolsas} bolsas, {self.valores} valores"
        )


class ReferenciaIncompleta(RuntimeError):
    """Falta metadato de algo que la configuracion del motor si declara."""


def _upsert(sesion: Session, modelo, filas: list[dict[str, Any]], clave: list[str]) -> int:
    """INSERT ... ON CONFLICT DO UPDATE sobre la clave natural.

    Se actualizan todas las columnas menos la clave y `created_at`: un cambio de
    nombre o de sector en el YAML tiene que llegar a la base de datos, pero la
    fecha de alta de una fila no se reescribe cada vez que se recarga.
    """
    if not filas:
        return 0
    sentencia = insert(modelo).values(filas)
    actualizables = {
        c: sentencia.excluded[c] for c in filas[0] if c not in clave and c != "created_at"
    }
    if actualizables:
        sentencia = sentencia.on_conflict_do_update(index_elements=clave, set_=actualizables)
    else:
        sentencia = sentencia.on_conflict_do_nothing(index_elements=clave)
    sesion.execute(sentencia)
    return len(filas)


def _huso(codigo_calendario: str) -> str:
    """Huso horario del mercado, tomado del calendario de negociacion.

    Del calendario y no de un YAML: es la fuente autoritativa y ya esta en el
    proyecto. Dos sitios donde escribir el huso es un sitio donde equivocarse.
    """
    import exchange_calendars as xc

    return str(xc.get_calendar(codigo_calendario).tz)


def cargar(sesion: Session, cfg=None, referencia: dict | None = None) -> Resumen:
    if cfg is None:
        from estrategia import config as core_config

        cfg = core_config.cargar()
    if referencia is None:
        referencia = yaml.safe_load(REFERENCIA.read_text(encoding="utf-8"))

    resumen = Resumen()

    # Un mercado declarado en reglas.yaml sin metadatos aqui produciria valores
    # sin pais ni divisa. Se comprueba antes de escribir nada, y con la lista
    # entera: al dar de alta un mercado interesa saber todo lo que falta de una
    # pasada, no descubrirlo de uno en uno.
    ids_motor = {m.id for m in cfg.reglas.universo.mercados}
    faltan = sorted(ids_motor - set(referencia["mercados"]))
    if faltan:
        raise ReferenciaIncompleta(
            f"mercados en reglas.yaml sin entrada en config/referencia.yaml: {faltan}"
        )

    resumen.paises = _upsert(
        sesion,
        Country,
        [{"code": c, "name": n} for c, n in referencia["paises"].items()],
        ["code"],
    )
    resumen.divisas = _upsert(
        sesion,
        Currency,
        [
            {"code": c, "name": d["nombre"], "minor_units": d["decimales"]}
            for c, d in referencia["divisas"].items()
        ],
        ["code"],
    )

    indices = cfg.reglas.tecnico.indices_regimen
    filas_mercado = []
    for m in cfg.reglas.universo.mercados:
        meta = referencia["mercados"][m.id]
        calendario = cfg.implementacion.calendarios[m.id]
        filas_mercado.append(
            {
                "id": m.id,
                "name": meta["nombre"],
                "country_code": meta["pais"],
                "currency_code": m.divisa,
                "timezone": _huso(calendario),
                "trading_calendar": calendario,
                "classification": CLASIFICACION[m.clasificacion],
                "ticker_suffix": m.sufijo,
                "benchmark_symbol": indices.get(m.id),
                "benchmark_is_total_return": bool(meta.get("benchmark_total_return", False)),
                "active": True,
            }
        )
    resumen.mercados = _upsert(sesion, Market, filas_mercado, ["id"])

    resumen.bolsas = _upsert(
        sesion,
        Exchange,
        [
            {
                "code": b["codigo"],
                "name": b["nombre"],
                "mic": b["mic"],
                "country_code": b["pais"],
                "market_id": b["mercado"],
            }
            for b in referencia["bolsas"]
            if b["mercado"] in ids_motor
        ],
        ["code"],
    )
    sesion.flush()

    bolsa_por_mercado = {
        mercado: id_
        for id_, mercado in sesion.execute(select(Exchange.id, Exchange.market_id)).all()
    }
    divisa_por_mercado = {m.id: m.divisa for m in cfg.reglas.universo.mercados}

    filas_valor = []
    for mercado_id, valores in cfg.universo.mercados.items():
        for v in valores:
            filas_valor.append(
                {
                    "ticker": v.ticker,
                    "name": v.nombre,
                    "market_id": mercado_id,
                    "exchange_id": bolsa_por_mercado.get(mercado_id),
                    "currency_code": divisa_por_mercado[mercado_id],
                    "asset_type": AssetType.COMMON_STOCK.value,
                    # El sector que manda es el del proveedor; el de universo.yaml
                    # es solo un respaldo, y se marca como tal para que nadie lo
                    # confunda con un dato verificado.
                    "sector": v.sector_declarado,
                    "is_primary_listing": True,
                    "active": True,
                }
            )
    resumen.valores = _upsert(sesion, Security, filas_valor, ["market_id", "ticker"])

    return resumen


def main() -> int:
    from .session import _fabrica

    with _fabrica()() as sesion:
        resumen = cargar(sesion)
        sesion.commit()
    print(f"[{dt.date.today()}] referencia cargada: {resumen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
