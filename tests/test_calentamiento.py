"""Calentamiento, rentabilidad por ano y cierre de la curva (tarea B4).

Tres fallos que no cambian que se compra, pero si lo que el informe dice:

- El calentamiento de unos 13 meses se contaba desde el inicio del backtest
  aunque hubiera historico anterior. El periodo de validacion, que empieza
  donde acaba el de diseno, pasaba mas de un ano en liquidez esperando unos
  indicadores que ya tenia.
- La rentabilidad por ano media cada ano desde su primera sesion: lo que se
  movia entre el cierre de diciembre y la primera sesion de enero no caia en
  ningun ano.
- La curva terminaba antes de liquidar lo que seguia abierto, sin los costes
  de esa ultima venta.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from estrategia import backtest as backtest_mod
from estrategia import metricas as metricas_mod


def _dias_de_revision(instantanea, cfg, inicio, fin, monkeypatch):
    """Sesiones en que el motor llego a revisar algun mercado."""
    dias: list[dt.date] = []
    original = backtest_mod._revisar

    def espia(dia, *args, **kwargs):
        dias.append(dia)
        return original(dia, *args, **kwargs)

    monkeypatch.setattr(backtest_mod, "_revisar", espia)
    r = backtest_mod.ejecutar(instantanea, cfg, inicio, fin)
    return sorted(set(dias)), r


def test_con_historico_previo_se_decide_desde_el_primer_dia(cfg, instantanea, monkeypatch):
    inicio = dt.date(2022, 6, 1)
    dias, _ = _dias_de_revision(
        instantanea, cfg, inicio, dt.date(2023, 6, 30), monkeypatch
    )
    assert dias
    # La primera revision es la de la primera semana, no la de dentro de un ano.
    assert dias[0] - inicio < dt.timedelta(days=10)


def test_sin_historico_previo_se_sigue_esperando_el_calentamiento(
    cfg, instantanea, monkeypatch
):
    rango_ini, _ = instantanea.rango_precios
    dias, _ = _dias_de_revision(
        instantanea, cfg, rango_ini, dt.date(2021, 12, 31), monkeypatch
    )
    assert dias
    assert dias[0] >= backtest_mod._inicio_con_calentamiento(rango_ini, cfg)


# --------------------------------------------------------------------------
# Rentabilidad por ano
# --------------------------------------------------------------------------


def _curva(puntos):
    return pd.DataFrame(
        [
            {"fecha": f, "valor": v, "efectivo": v, "n_posiciones": 0, "exposicion": 0.0}
            for f, v in puntos
        ]
    )


def test_los_anos_encadenados_dan_la_rentabilidad_total():
    """Un salto entre el 31 de diciembre y el 2 de enero tiene que caer en el
    ano nuevo. Antes se perdia: 2023 salia plano aunque ganara un 10 %."""
    curva = _curva(
        [
            (dt.date(2022, 1, 3), 100.0),
            (dt.date(2022, 12, 30), 120.0),
            (dt.date(2023, 1, 2), 132.0),
            (dt.date(2023, 12, 29), 132.0),
        ]
    )
    tabla = metricas_mod.por_ano(curva, pd.DataFrame())
    r = dict(zip(tabla["ano"], tabla["rentabilidad"]))
    assert r[2022] == pytest.approx(0.20)
    assert r[2023] == pytest.approx(0.10)

    encadenada = float(np.prod([1 + x for x in tabla["rentabilidad"]]) - 1)
    total = metricas_mod.resumir(curva, pd.DataFrame(), _cfg_minima()).rentabilidad_total
    assert encadenada == pytest.approx(total)


def _cfg_minima():
    from types import SimpleNamespace

    return SimpleNamespace(
        reglas=SimpleNamespace(
            metricas=SimpleNamespace(
                periodicidad_sharpe="semanal", tasa_libre_riesgo_anual=0.0
            )
        )
    )


def test_en_el_backtest_los_anos_encadenados_dan_el_total(cfg, instantanea):
    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2020, 1, 1), dt.date(2024, 12, 31))
    tabla = metricas_mod.por_ano(r.curva, r.operaciones_df)
    encadenada = float(np.prod([1 + x for x in tabla["rentabilidad"]]) - 1)
    total = metricas_mod.resumir(r.curva, r.operaciones_df, cfg).rentabilidad_total
    assert encadenada == pytest.approx(total, abs=1e-12)


# --------------------------------------------------------------------------
# Liquidacion final
# --------------------------------------------------------------------------


def test_la_curva_termina_despues_de_liquidar(cfg, instantanea):
    """El ultimo punto de la curva es el efectivo tras vender lo que quedaba,
    con los costes pagados: el capital final cuadra con las operaciones."""
    fin = dt.date(2024, 12, 31)
    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2020, 1, 1), fin)
    assert r.posiciones_finales > 0, "el caso no se ejercita sin posiciones abiertas"

    ultima = r.curva.iloc[-1]
    assert ultima["fecha"] <= fin
    assert ultima["n_posiciones"] == 0
    assert ultima["exposicion"] == 0.0
    assert ultima["valor"] == pytest.approx(ultima["efectivo"])

    suma = sum(o.resultado_base for o in r.operaciones)
    assert ultima["valor"] == pytest.approx(r.capital_inicial + suma, abs=1e-6)
    # Una sola fila por fecha: la liquidacion no duplica el ultimo dia.
    assert r.curva["fecha"].is_unique
