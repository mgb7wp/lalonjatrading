"""Etapa de indicadores: de los precios de Postgres a `technical_indicator`.

Se ejecuta siempre **junto a la ingesta y despues de ella**, no como un proceso
suelto. Un indicador es una derivacion determinista de los precios, asi que si
los precios se actualizan y los indicadores no, lo que sirve la API deja de
corresponderse con lo que hay en la base de datos, y no hay nada que avise: los
numeros siguen pareciendo razonables, solo que son los de ayer.

Como todo lo demas del pipeline, es idempotente: recalcular sobre los mismos
precios da los mismos numeros y entra por UPSERT sobre `(valor, fecha)`.
"""

from __future__ import annotations

import datetime as dt
import logging

import numpy as np
from estrategia.catalogo import Ventana, calcular
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.adapters.nucleo import indicadores_a_filas
from backend.db import ingest
from backend.db.models import Market, Security
from backend.db.models.enums import AssetType

log = logging.getLogger("pipeline.indicadores")


def _serie(sesion: Session, security_id: int) -> dict[str, np.ndarray] | None:
    """Precios de un valor, ordenados y como vectores."""
    filas = sesion.execute(
        text(
            "SELECT date, open, high, low, close, close_raw, volume "
            "FROM price WHERE security_id = :id ORDER BY date"
        ),
        {"id": security_id},
    ).all()
    if not filas:
        return None

    def columna(i: int) -> np.ndarray:
        return np.array([float(f[i]) if f[i] is not None else np.nan for f in filas])

    return {
        "fechas": np.array([f[0] for f in filas]),
        "apertura": columna(1),
        "maximo": columna(2),
        "minimo": columna(3),
        "cierre": columna(4),
        "cierre_bruto": columna(5),
        "volumen": columna(6),
    }


def alinear_referencia(
    fechas_valor: np.ndarray, fechas_indice: np.ndarray, cierres_indice: np.ndarray
) -> np.ndarray:
    """El cierre del indice en cada sesion del valor, o el ultimo conocido.

    Dos series de mercados distintos no comparten calendario, y ni siquiera
    dentro del mismo mercado coinciden siempre: un valor puede no cotizar un dia
    en que el indice si.

    Se toma **el ultimo cierre del indice en o antes de la fecha del valor**, no
    el mas cercano. Esa distincion es la que impide que un festivo del valor
    acabe leyendo el indice del dia siguiente, que seria mirar hacia delante por
    una puerta que nadie vigila.
    """
    if len(fechas_indice) == 0:
        return np.full(len(fechas_valor), np.nan)

    orden_valor = np.array([f.toordinal() for f in fechas_valor])
    orden_indice = np.array([f.toordinal() for f in fechas_indice])
    posiciones = np.searchsorted(orden_indice, orden_valor, side="right") - 1
    salida = np.full(len(fechas_valor), np.nan)
    validas = posiciones >= 0
    salida[validas] = cierres_indice[posiciones[validas]]
    return salida


def calcular_mercado(sesion: Session, mercado_id: str, calculado_en: dt.datetime) -> int:
    """Calcula y persiste el catalogo de todos los valores de un mercado."""
    mercado = sesion.get(Market, mercado_id)
    if mercado is None:
        return 0

    referencia = None
    if mercado.benchmark_symbol:
        indice = sesion.scalars(
            select(Security).where(
                Security.market_id == mercado_id,
                Security.ticker == mercado.benchmark_symbol,
            )
        ).first()
        if indice is not None:
            referencia = _serie(sesion, indice.id)
    if referencia is None:
        # Sin indice no hay beta ni fuerza relativa. Se sigue con el resto en
        # lugar de abortar: perder veinte indicadores por no tener dos es peor.
        log.warning("mercado %s sin precios del indice %s", mercado_id, mercado.benchmark_symbol)

    valores = sesion.scalars(
        select(Security).where(
            Security.market_id == mercado_id,
            Security.active.is_(True),
            Security.asset_type != AssetType.INDEX.value,
        )
    ).all()

    total = 0
    for valor in valores:
        serie = _serie(sesion, valor.id)
        if serie is None:
            continue

        cierres_indice = None
        if referencia is not None:
            cierres_indice = alinear_referencia(
                serie["fechas"], referencia["fechas"], referencia["cierre"]
            )

        resultado = calcular(Ventana(**serie, referencia=cierres_indice))
        if not resultado.valores:
            continue

        filas = indicadores_a_filas(valor.id, serie["fechas"], resultado.valores, calculado_en)
        total += ingest.escribir_indicadores(sesion, filas).filas

    return total


def ejecutar(sesion: Session, cfg, mercados: list[str] | None = None) -> dict[str, int]:
    """Recalcula los indicadores de los mercados indicados."""
    ids = mercados or [m.id for m in cfg.reglas.universo.mercados]
    calculado_en = dt.datetime.now(dt.UTC)
    resultado: dict[str, int] = {}
    for mercado_id in ids:
        resultado[mercado_id] = calcular_mercado(sesion, mercado_id, calculado_en)
        sesion.commit()
    return resultado
