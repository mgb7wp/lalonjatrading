"""Backtest desde la base de datos: el ultimo punto de la FASE 7.

La prueba que importa es de ida y vuelta: se escriben datos del motor en
Postgres con el adaptador de escritura y se leen con el de lectura. Si los dos
sentidos no coinciden, la traduccion de D-14 tiene un agujero, y un agujero ahi
no se nota hasta que un backtest da otro numero sin que nadie haya tocado nada.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
import sqlalchemy as sa

from backend.adapters import nucleo
from backend.adapters.desde_bd import BaseContaminada, instantanea_desde_bd
from backend.db import ingest

TICKER = "AAPL"
HOY = dt.date(2026, 1, 5)


@pytest.fixture
def bd(bd_con_referencia):
    """Sesion limpia sobre la base ya sembrada, sin dejar rastro al terminar."""
    with sa.orm.Session(bd_con_referencia) as s:
        s.execute(sa.text("DELETE FROM price"))
        s.execute(sa.text("DELETE FROM fundamental_snapshot"))
        s.execute(sa.text("DELETE FROM fx_rate"))
        s.commit()
        yield s
        s.rollback()


def _precios(ticker: str = TICKER, n: int = 5) -> pd.DataFrame:
    base = dt.date(2024, 1, 2)
    return pd.DataFrame(
        {
            "ticker": [ticker] * n,
            "fecha": [base + dt.timedelta(days=i) for i in range(n)],
            "apertura": [100.0 + i for i in range(n)],
            "maximo": [101.0 + i for i in range(n)],
            "minimo": [99.0 + i for i in range(n)],
            "cierre": [100.5 + i for i in range(n)],
            "cierre_bruto": [100.5 + i for i in range(n)],
            "volumen": [1_000_000 + i for i in range(n)],
            "fuente": ["yfinance"] * n,
        }
    )


def _escribir_precios(sesion, df):
    mapa = ingest.id_por_ticker(sesion)
    sesion.execute(sa.text("SELECT 1"))  # fuerza la conexion antes del COPY, como hace el pipeline
    filas = nucleo.precios_a_filas(df, mapa, HOY)
    assert filas, "el ticker de prueba tiene que existir en la referencia"
    ingest.escribir_precios(sesion, filas)
    sesion.commit()


# --- Ida y vuelta ----------------------------------------------------------


def test_los_precios_vuelven_igual_que_entraron(bd):
    """Si un numero cambia por el camino, el backtest deja de ser reproducible."""
    original = _precios()
    _escribir_precios(bd, original)

    inst = instantanea_desde_bd(bd)
    leidos = inst.precios[inst.precios["ticker"] == TICKER].reset_index(drop=True)

    assert len(leidos) == len(original)
    for col in ("apertura", "maximo", "minimo", "cierre", "cierre_bruto"):
        assert leidos[col].tolist() == pytest.approx(original[col].tolist())
    assert leidos["fecha"].tolist() == original["fecha"].tolist()


def test_los_numeros_llegan_como_float_y_no_como_decimal(bd):
    """Postgres devuelve `Numeric` como `Decimal`.

    Un array de `Decimal` se convierte en `dtype=object`: numpy deja de vectorizar,
    el backtest se arrastra y algunas operaciones fallan con un error que no
    menciona el tipo por ningun lado. Es el fallo mas caro de diagnosticar de los
    que puede introducir este modulo.
    """
    _escribir_precios(bd, _precios())
    inst = instantanea_desde_bd(bd)

    for col in ("apertura", "maximo", "minimo", "cierre", "cierre_bruto"):
        assert inst.precios[col].dtype.kind == "f", f"{col} no es flotante"
    # El volumen es entero en el esquema y vuelve entero, que es lo correcto.
    # Lo que no puede ser, ni el, es `object`.
    assert inst.precios["volumen"].dtype.kind in "if"


def test_la_instantanea_sirve_para_construir_series(bd, cfg):
    """El motor tiene que poder consumirla sin adaptarse a nada.

    Es la comprobacion de que la flecha de dependencias sigue bien puesta: el
    motor no sabe que existe una base de datos, y aun asi esto funciona.
    """
    _escribir_precios(bd, _precios(n=30))
    inst = instantanea_desde_bd(bd)
    # `preparar` calcula los indicadores una sola vez; sin el, la instantanea se
    # niega a dar vistas, que es justo lo que uno quiere de un tipo que tiene
    # que ser inmutable durante todo el backtest.
    inst.preparar(cfg)

    corte = dt.date(2024, 1, 20)
    vista = inst.vista(corte)

    assert vista.serie(TICKER) is not None
    # `serie()` entrega la serie entera indexada: el corte NO se aplica
    # recortando arrays, sino al consultar. Por eso lo que hay que comprobar es
    # lo que devuelve una consulta, no lo que contiene la estructura.
    ventana = vista.precios(TICKER)
    assert not ventana.empty
    assert max(ventana["fecha"]) <= corte, "la vista no puede mirar mas alla del corte"


def test_la_procedencia_queda_anotada(bd):
    """El informe estampa el origen; si miente, un backtest sintetico pasa por real."""
    _escribir_precios(bd, _precios())
    inst = instantanea_desde_bd(bd)

    assert "base de datos" in inst.origen
    assert "yfinance" in inst.origen
    assert inst.fecha_descarga == HOY


# --- Lo que se niega a hacer -----------------------------------------------


def test_se_niega_a_leer_una_base_que_mezcla_sintetico_y_real(bd):
    """El guardarrail de la FASE 6, aplicado al otro extremo.

    La ingesta ya impide ESCRIBIR la mezcla. Esto impide CONSUMIRLA: una base que
    quedo contaminada antes de existir aquel guardarrail sigue en el disco de
    alguien, y un backtest sobre ella produce numeros que parecen normales.
    """
    _escribir_precios(bd, _precios())
    sinteticos = _precios(n=3)
    sinteticos["fecha"] = [dt.date(2024, 2, 1) + dt.timedelta(days=i) for i in range(3)]
    sinteticos["fuente"] = ["sintetico"] * 3
    _escribir_precios(bd, sinteticos)

    with pytest.raises(BaseContaminada, match="sinteticas"):
        instantanea_desde_bd(bd)


def test_una_base_vacia_no_revienta(bd):
    """Vale devolver una instantanea vacia; no vale morir con un KeyError."""
    inst = instantanea_desde_bd(bd)
    assert inst.precios.empty
    assert "vacia" in inst.origen
