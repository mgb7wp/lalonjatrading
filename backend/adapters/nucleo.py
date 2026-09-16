"""Traduccion entre el vocabulario del motor (espanol) y el del esquema (ingles).

Es la costura de la decision D-14, y esta en un solo sitio a proposito. Mientras
las traducciones vivan aqui, cambiar un nombre de columna es cambiar una linea;
repartidas por el codigo, es una caceria.

Ninguna de estas funciones toca la base de datos ni la red: transforman
DataFrames. Eso las hace probables sin levantar nada.
"""

from __future__ import annotations

import pandas as pd

#: El motor habla de periodos en espanol; el esquema, en ingles.
PERIODOS = {"anual": "annual", "trimestral": "quarterly", "semestral": "semiannual"}

#: `capturado` es una foto tomada en su momento; `reconstruido`, una deduccion
#: posterior. La distincion es la que decide cuanto vale un backtest, asi que se
#: traduce pero no se pierde.
ORIGENES_PIT = {"capturado": "captured", "reconstruido": "reconstructed"}

PRECIOS = {
    "fecha": "date",
    "apertura": "open",
    "maximo": "high",
    "minimo": "low",
    "cierre": "close",
    "cierre_bruto": "close_raw",
    "volumen": "volume",
    "fuente": "source",
}

FUNDAMENTALES = {
    "fin_periodo": "period_end",
    "fecha_publicacion": "publication_date",
    "origen_fecha_publicacion": "publication_date_origin",
    "fecha_descarga": "downloaded_at",
    "margen_operativo": "operating_margin",
    "ventas": "revenue",
    "flujo_caja_libre": "free_cash_flow",
    "deuda_neta": "net_debt",
    "ev": "enterprise_value",
    "patrimonio_neto": "equity",
    "acciones_en_circulacion": "shares_outstanding",
    "divisa_reporte": "reporting_currency",
    "divisa_cotizacion": "listing_currency",
    "fuente": "source",
    "roe": "roe",
    "ebit": "ebit",
    "ebitda": "ebitda",
}

#: Columnas de cada tabla, en el orden en que se copian. El orden importa:
#: `COPY` va por posicion, no por nombre.
COLUMNAS_PRECIO = [
    "security_id",
    "date",
    "open",
    "high",
    "low",
    "close",
    "close_raw",
    "volume",
    "source",
    "downloaded_at",
]

COLUMNAS_FUNDAMENTAL = [
    "security_id",
    "period_end",
    "period",
    "publication_date",
    "publication_date_origin",
    "pit_origin",
    "revenue",
    "ebit",
    "ebitda",
    "free_cash_flow",
    "net_debt",
    "equity",
    "shares_outstanding",
    "enterprise_value",
    "roe",
    "operating_margin",
    "reporting_currency",
    "listing_currency",
    "source",
    "downloaded_at",
]

COLUMNAS_FX = ["base_currency", "quote_currency", "date", "rate", "source"]


def _sin_nan(df: pd.DataFrame) -> pd.DataFrame:
    """`NaN` de pandas a `None`, que es lo que Postgres entiende por nulo.

    Sin esto, un hueco legitimo llega a la base de datos como la cadena 'nan' o
    como un flotante NaN, y un NaN en una columna Numeric es un error en el
    mejor caso y un valor imposible de comparar en el peor.
    """
    return df.astype(object).where(pd.notna(df), None)


def precios_a_filas(df: pd.DataFrame, id_por_ticker: dict[str, int], descargado) -> list[tuple]:
    """DataFrame de precios del motor -> filas listas para `COPY`.

    Los tickers que no estan dados de alta se descartan aqui en silencio: el
    recuento de descartes lo lleva quien llama, que es el unico que puede
    distinguir "este valor no existe" de "este valor aun no se ha sembrado".
    """
    if df.empty:
        return []
    d = df.rename(columns=PRECIOS)
    d = d[d["ticker"].isin(id_por_ticker)]
    if d.empty:
        return []
    d = _sin_nan(d)
    return [
        (
            id_por_ticker[fila["ticker"]],
            fila["date"],
            fila.get("open"),
            fila.get("high"),
            fila.get("low"),
            fila["close"],
            fila.get("close_raw"),
            None if fila.get("volume") is None else int(fila["volume"]),
            fila.get("source") or "desconocida",
            descargado,
        )
        for _, fila in d.iterrows()
    ]


def fundamentales_a_filas(
    df: pd.DataFrame, id_por_ticker: dict[str, int], descargado
) -> list[tuple]:
    if df.empty:
        return []
    d = df.rename(columns=FUNDAMENTALES)
    d = d[d["ticker"].isin(id_por_ticker)]
    if d.empty:
        return []
    d = _sin_nan(d)

    filas = []
    for _, fila in d.iterrows():
        periodo = PERIODOS.get(fila.get("periodo"), fila.get("periodo"))
        origen = ORIGENES_PIT.get(fila.get("origen_pit"), fila.get("origen_pit"))
        filas.append(
            (
                id_por_ticker[fila["ticker"]],
                fila["period_end"],
                periodo,
                fila["publication_date"],
                fila.get("publication_date_origin") or "desconocido",
                origen,
                fila.get("revenue"),
                fila.get("ebit"),
                fila.get("ebitda"),
                fila.get("free_cash_flow"),
                fila.get("net_debt"),
                fila.get("equity"),
                fila.get("shares_outstanding"),
                fila.get("enterprise_value"),
                fila.get("roe"),
                fila.get("operating_margin"),
                fila.get("reporting_currency"),
                fila.get("listing_currency"),
                fila.get("source") or "desconocida",
                fila.get("downloaded_at") or descargado,
            )
        )
    return filas


def fx_a_filas(df: pd.DataFrame, base: str = "EUR") -> list[tuple]:
    """Tipos del motor -> filas de `fx_rate`.

    El motor guarda los tipos en un solo sentido, base -> divisa, y los invierte
    al leer. Aqui se respeta ese convenio: dos convenios circulando por el codigo
    producen carteras mal valoradas que nadie detecta porque el numero parece
    razonable.
    """
    if df.empty:
        return []
    d = _sin_nan(df)
    return [
        (base, fila["divisa"], fila["fecha"], fila["tasa"], fila.get("fuente") or "desconocida")
        for _, fila in d.iterrows()
    ]


#: Del nombre del catalogo a la columna de `technical_indicator`.
#:
#: Los que no aparecen aqui no se pierden: van a la columna `extra` en JSONB.
#: Esa valvula es lo que permite registrar un indicador nuevo sin una migracion,
#: que es lo que pide §13. Cuando uno de `extra` se empieza a consultar de
#: verdad, se le da columna propia y un indice; hasta entonces, guardarlo
#: cuesta menos que decidir si merece una.
INDICADORES = {
    "sma_20": "sma_20",
    "sma_50": "sma_50",
    "sma_100": "sma_100",
    "sma_200": "sma_200",
    "ema_20": "ema_20",
    "rsi_14": "rsi_14",
    "macd": "macd",
    "macd_signal": "macd_signal",
    "atr_14": "atr_14",
    "adx_14": "adx_14",
    "estocastico_k": "stochastic_k",
    "bollinger_posicion": "bollinger_position",
    "volatilidad_60": "volatility_annualized",
    "beta_252": "beta",
    "drawdown_maximo_1a": "max_drawdown_1y",
    "momentum_12_1": "momentum_12_1",
    "fuerza_relativa_126": "relative_strength",
    "distancia_maximo_52s": "distance_from_52w_high",
    "distancia_minimo_52s": "distance_from_52w_low",
    "ratio_volumen_20": "volume_ratio_20",
}

COLUMNAS_INDICADOR = [
    "security_id",
    "date",
    *INDICADORES.values(),
    "extra",
    "computed_at",
]


def indicadores_a_filas(
    security_id: int,
    fechas,
    valores: dict,
    calculado_en,
) -> list[tuple]:
    """Vectores del catalogo -> filas de `technical_indicator`.

    Las sesiones sin ni un solo indicador calculable se descartan. Al principio
    de cada serie hay doscientas y pico asi —ningun indicador de ventana larga
    tiene aun historico— y guardarlas seria guardar filas enteras de nulos que
    solo sirven para engordar la tabla y ensuciar cualquier consulta.
    """
    import json
    import math

    extras = {n: v for n, v in valores.items() if n not in INDICADORES}
    filas: list[tuple] = []

    for i, fecha in enumerate(fechas):
        columnas = []
        hay_dato = False
        for nombre in INDICADORES:
            vector = valores.get(nombre)
            crudo = None if vector is None else float(vector[i])
            if crudo is None or math.isnan(crudo) or math.isinf(crudo):
                columnas.append(None)
            else:
                columnas.append(crudo)
                hay_dato = True

        sobrantes = {}
        for nombre, vector in extras.items():
            crudo = float(vector[i])
            if not math.isnan(crudo) and not math.isinf(crudo):
                sobrantes[nombre] = crudo
                hay_dato = True

        if not hay_dato:
            continue
        filas.append(
            (
                security_id,
                fecha,
                *columnas,
                json.dumps(sobrantes) if sobrantes else None,
                calculado_en,
            )
        )
    return filas
