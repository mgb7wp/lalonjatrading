"""Adaptador de yfinance: lo que se puede probar sin red (tarea B7).

Yahoo no es accesible desde donde se desarrolla la app, asi que todo lo que
decide algo esta en funciones puras: el ajuste de precios, los reintentos, la
fecha de publicacion estimada y la deuda neta. Aqui se fijan.
"""

from __future__ import annotations

import datetime as dt
import sys
import types

import estrategia.datos.yfinance_proveedor as yfp
import numpy as np
import pandas as pd
import pytest
from estrategia.datos.yfinance_proveedor import (
    ProveedorYFinance,
    ajustar_ohlc,
    con_reintentos,
    deuda_neta_de,
    estimar_fecha_publicacion,
)
from estrategia.errores import ErrorDatos

# --------------------------------------------------------------------------
# ajustar_ohlc
# --------------------------------------------------------------------------


def _yahoo(open_, high, low, close, adj, volume=1_000.0):
    return pd.DataFrame(
        {
            "Open": [open_],
            "High": [high],
            "Low": [low],
            "Close": [close],
            "Adj Close": [adj],
            "Volume": [volume],
        },
        index=pd.to_datetime(["2024-03-01"]),
    )


def test_el_ajuste_se_aplica_a_los_cuatro_precios():
    """Un dividendo del 2 %: el factor 0,98 se aplica tambien a apertura,
    maximo y minimo. Ajustar solo el cierre inventaria un hueco en cada
    dividendo y dejaria el ATR sin sentido."""
    df = ajustar_ohlc(_yahoo(99.0, 102.0, 97.0, 100.0, 98.0, volume=5_000.0))
    fila = df.iloc[0]
    assert fila["apertura"] == pytest.approx(99.0 * 0.98)
    assert fila["maximo"] == pytest.approx(102.0 * 0.98)
    assert fila["minimo"] == pytest.approx(97.0 * 0.98)
    assert fila["cierre"] == pytest.approx(98.0)
    # El bruto y el volumen se quedan sin ajustar: con ellos se mide la
    # liquidez y se calcula el EV.
    assert fila["cierre_bruto"] == pytest.approx(100.0)
    assert fila["volumen"] == pytest.approx(5_000.0)
    # Y el OHLC ajustado sigue siendo coherente.
    assert fila["minimo"] <= min(fila["apertura"], fila["cierre"])
    assert fila["maximo"] >= max(fila["apertura"], fila["cierre"])


def test_sin_dividendos_el_ajuste_no_cambia_nada():
    df = ajustar_ohlc(_yahoo(99.0, 102.0, 97.0, 100.0, 100.0))
    fila = df.iloc[0]
    assert fila[["apertura", "maximo", "minimo", "cierre"]].tolist() == [99.0, 102.0, 97.0, 100.0]


def test_un_cierre_cero_no_divide_por_cero():
    """Con cierre 0 no hay factor: se deja sin ajustar en lugar de dar infinito.
    La fila se aparta despues por precio cero (tarea B6)."""
    df = ajustar_ohlc(_yahoo(1.0, 1.0, 1.0, 0.0, 0.0))
    assert np.isfinite(df[["apertura", "maximo", "minimo"]].to_numpy()).all()


def test_si_faltan_columnas_de_yahoo_es_un_error_claro():
    bruto = _yahoo(99.0, 102.0, 97.0, 100.0, 98.0).drop(columns=["Adj Close"])
    with pytest.raises(ErrorDatos, match="Adj Close"):
        ajustar_ohlc(bruto)


# --------------------------------------------------------------------------
# con_reintentos
# --------------------------------------------------------------------------


@pytest.fixture
def esperas(monkeypatch):
    """Las esperas se anotan en vez de dormir."""
    anotadas: list[float] = []
    monkeypatch.setattr(yfp.time, "sleep", lambda s: anotadas.append(s))
    return anotadas


def _falla_n_veces(n, resultado="ok"):
    llamadas = {"n": 0}

    def fn():
        llamadas["n"] += 1
        if llamadas["n"] <= n:
            raise ConnectionError(f"429 intento {llamadas['n']}")
        return resultado

    return fn, llamadas


def test_reintenta_con_espera_creciente_hasta_que_sale(esperas):
    fn, llamadas = _falla_n_veces(2)
    assert con_reintentos(fn, intentos=4, espera_inicial=2.0) == "ok"
    assert llamadas["n"] == 3
    assert esperas == [2.0, 4.0]


def test_a_la_primera_no_espera(esperas):
    fn, _ = _falla_n_veces(0)
    assert con_reintentos(fn, intentos=4, espera_inicial=2.0) == "ok"
    assert esperas == []


def test_agotados_los_intentos_da_un_error_con_la_causa(esperas):
    fn, llamadas = _falla_n_veces(10)
    with pytest.raises(ErrorDatos, match="fallo tras 3 intentos.*429 intento 3") as exc:
        con_reintentos(fn, intentos=3, espera_inicial=1.0)
    assert llamadas["n"] == 3
    # No se espera despues del ultimo intento: no sirve para nada.
    assert esperas == [1.0, 2.0]
    assert isinstance(exc.value.__cause__, ConnectionError)


# --------------------------------------------------------------------------
# estimar_fecha_publicacion
# --------------------------------------------------------------------------


def test_la_publicacion_anual_se_estima_con_el_retraso_anual(cfg):
    fin = dt.date(2023, 12, 31)
    dias = cfg.reglas.datos.retraso_anual_dias
    assert estimar_fecha_publicacion(fin, "es", cfg, "anual") == fin + dt.timedelta(days=dias)


def test_la_publicacion_trimestral_se_estima_con_el_retraso_trimestral(cfg):
    fin = dt.date(2024, 3, 31)
    dias = cfg.reglas.datos.retraso_trimestral_dias
    assert estimar_fecha_publicacion(fin, "us", cfg, "trimestral") == fin + dt.timedelta(days=dias)


def test_el_retraso_del_mercado_manda_sobre_el_general(cfg):
    """`retraso_por_mercado` es el valor especifico del mercado y gana."""
    fin = dt.date(2023, 12, 31)
    for mercado, dias in cfg.reglas.datos.retraso_por_mercado.items():
        assert estimar_fecha_publicacion(fin, mercado, cfg, "anual") == fin + dt.timedelta(
            days=dias
        )
    assert cfg.reglas.datos.retraso_por_mercado, "el caso no se ejercita"


def test_la_publicacion_nunca_es_anterior_al_cierre_del_periodo(cfg):
    fin = dt.date(2023, 12, 31)
    for mercado in cfg.reglas.mercados_por_id:
        for periodo in ("anual", "trimestral"):
            assert estimar_fecha_publicacion(fin, mercado, cfg, periodo) > fin


# --------------------------------------------------------------------------
# Deuda neta: la caja se resta una sola vez
# --------------------------------------------------------------------------

A2023, A2022 = pd.Timestamp("2023-12-31"), pd.Timestamp("2022-12-31")


def _balance(filas: dict[str, list]):
    return pd.DataFrame(filas, index=[A2023, A2022]).T


def test_con_deuda_total_se_resta_la_caja():
    b = _balance({"Total Debt": [500.0, 400.0], "Cash And Cash Equivalents": [120.0, 100.0]})
    assert deuda_neta_de(b, A2023) == pytest.approx(380.0)


def test_con_solo_deuda_neta_no_se_vuelve_a_restar_la_caja():
    """El fallo: la deuda neta ya lleva la caja restada. Antes salia 380 - 120."""
    b = _balance({"Net Debt": [380.0, 300.0], "Cash And Cash Equivalents": [120.0, 100.0]})
    assert deuda_neta_de(b, A2023) == pytest.approx(380.0)


def test_se_decide_ejercicio_a_ejercicio():
    """Un ano con deuda total y otro que solo trae la neta."""
    b = _balance(
        {
            "Total Debt": [500.0, np.nan],
            "Net Debt": [380.0, 300.0],
            "Cash And Cash Equivalents": [120.0, 100.0],
        }
    )
    assert deuda_neta_de(b, A2023) == pytest.approx(380.0)
    assert deuda_neta_de(b, A2022) == pytest.approx(300.0)


def test_sin_caja_se_toma_la_deuda_total():
    b = _balance({"Total Debt": [500.0, 400.0]})
    assert deuda_neta_de(b, A2023) == pytest.approx(500.0)


def test_sin_deuda_no_hay_deuda_neta():
    """Y sin deuda neta no hay EV (tarea B5): no se inventa un cero."""
    b = _balance({"Cash And Cash Equivalents": [120.0, 100.0]})
    assert deuda_neta_de(b, A2023) is None
    assert deuda_neta_de(None, A2023) is None


def test_el_proveedor_guarda_la_deuda_neta_sin_restar_dos_veces(cfg, monkeypatch):
    columnas = [pd.Timestamp(f"{2023 - i}-12-31") for i in range(4)]
    resultados = pd.DataFrame(
        {c: [1000.0, 150.0, 200.0, 100.0] for c in columnas},
        index=["Total Revenue", "EBIT", "EBITDA", "Net Income"],
    )
    # Solo deuda neta, y caja: el caso que restaba dos veces.
    balance = pd.DataFrame(
        {c: [800.0, 380.0, 120.0, 50.0] for c in columnas},
        index=[
            "Stockholders Equity",
            "Net Debt",
            "Cash And Cash Equivalents",
            "Ordinary Shares Number",
        ],
    )
    caja = pd.DataFrame({c: [90.0] for c in columnas}, index=["Free Cash Flow"])

    class Ticker:
        def __init__(self, ticker):
            self.info = {"financialCurrency": "EUR", "currency": "EUR"}
            self.income_stmt, self.balance_sheet, self.cashflow = resultados, balance, caja

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Ticker))
    monkeypatch.setattr(yfp.time, "sleep", lambda s: None)

    ticker = cfg.universo.tickers()[0]
    df = ProveedorYFinance(cfg).fundamentales([ticker], dt.date(2020, 1, 1), dt.date(2024, 12, 31))
    assert len(df) == 4
    assert (df["deuda_neta"] == 380.0).all()
