"""Constructores de datos a medida para los tests.

Viven aparte de `conftest.py` porque los tests los importan por nombre, y un
`conftest` es un modulo especial de pytest que no esta pensado para eso.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from estrategia.datos.almacen import Instantanea

FIN = dt.date(2024, 12, 31)


def instantanea_de(
    cfg,
    precios: pd.DataFrame,
    fundamentales: pd.DataFrame | None = None,
    fx: pd.DataFrame | None = None,
    sectores: dict | None = None,
) -> Instantanea:
    """Construye una instantanea a medida para un test concreto."""
    vacio_fund = pd.DataFrame(
        columns=[
            "ticker", "fin_periodo", "periodo", "fecha_publicacion",
            "origen_fecha_publicacion", "origen_pit", "fecha_descarga", "roe",
            "margen_operativo", "ventas", "flujo_caja_libre", "deuda_neta",
            "ebitda", "ebit", "ev", "patrimonio_neto",
        ]
    )
    inst = Instantanea(
        precios=precios,
        fundamentales=fundamentales if fundamentales is not None else vacio_fund,
        fx=fx if fx is not None else pd.DataFrame(columns=["fecha", "divisa", "tasa"]),
        sectores=sectores or {},
        fecha_descarga=FIN,
        origen="test",
    )
    return inst.preparar(cfg)


def serie_precios(
    ticker: str, fechas: list[dt.date], cierres: list[float], **columnas
) -> pd.DataFrame:
    """Serie OHLCV sencilla y coherente a partir de una lista de cierres."""
    n = len(cierres)
    df = pd.DataFrame(
        {
            "fecha": fechas,
            "ticker": ticker,
            "apertura": columnas.get("apertura", cierres),
            "maximo": columnas.get("maximo", [c * 1.01 for c in cierres]),
            "minimo": columnas.get("minimo", [c * 0.99 for c in cierres]),
            "cierre": cierres,
            "cierre_bruto": columnas.get("cierre_bruto", cierres),
            "volumen": columnas.get("volumen", [1_000_000.0] * n),
        }
    )
    # Coherencia OHLC: el minimo nunca por encima de apertura/cierre, ni el
    # maximo por debajo. Un fixture incoherente hace que la logica de stops
    # produzca disparates que parecen fallos del motor.
    df["minimo"] = df[["minimo", "apertura", "cierre"]].min(axis=1)
    df["maximo"] = df[["maximo", "apertura", "cierre"]].max(axis=1)
    return df
