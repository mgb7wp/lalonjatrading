"""Puntuacion fundamental (tarea B5).

Cuatro fallos que movian la nota de las empresas sin que nada lo dijera:

- Los percentiles contaban los huecos (NaN) en el tamano de la muestra: con la
  mitad de huecos, la mejor del mercado sacaba un 43 en vez de un 87.
- El EV se calculaba con el precio ajustado por dividendos, que rebaja los
  precios pasados: la capitalizacion de hace anos salia menor que la real.
- La deuda neta que faltaba se tomaba como cero: una empresa endeudada parecia
  barata solo porque al proveedor le faltaba el dato.
- El recurso de percentilar contra el bloque no llegaba a actuar, y el informe
  no decia cuantas compras se habian puntuado asi.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from estrategia import backtest as backtest_mod
from estrategia import fundamental as fundamental_mod
from estrategia import informe as informe_mod
from estrategia.datos.almacen import Instantanea
from estrategia.fundamental import Ratios, percentiles_hazen, puntuar, valor_empresa
from estrategia.tipos import CohorteUsada

# --------------------------------------------------------------------------
# Percentiles con huecos
# --------------------------------------------------------------------------


def test_los_huecos_no_cuentan_en_el_tamano_de_la_muestra():
    p = percentiles_hazen(pd.Series([1.0, 2.0, np.nan, np.nan]))
    # Dos datos: Hazen da 25 y 75. Con el fallo salian 12,5 y 37,5.
    assert p.iloc[0] == pytest.approx(25.0)
    assert p.iloc[1] == pytest.approx(75.0)
    assert p.iloc[2:].isna().all()


def test_una_serie_toda_huecos_da_huecos():
    p = percentiles_hazen(pd.Series([np.nan, np.nan]))
    assert len(p) == 2 and p.isna().all()


def _ratios(ticker, roe=0.20, margen=0.15, ev_ebit=None):
    return Ratios(
        ticker=ticker,
        roe=roe,
        margen_operativo=margen,
        crecimiento_ventas_3a=0.05,
        flujo_caja_libre=1.0,
        deuda_neta_ebitda=1.0,
        ev_ebit=ev_ebit,
        fin_periodo=dt.date(2023, 12, 31),
        fecha_publicacion=dt.date(2024, 4, 30),
        origen_pit="reconstruido",
    )


def test_la_mas_barata_saca_la_nota_alta_aunque_falte_el_ev_de_otras(cfg):
    """Ocho empresas en un mercado, solo cuatro con EV/EBIT. La mas barata de
    las cuatro tiene que quedar arriba en valoracion (87,5), no en la mitad."""
    cohorte = {}
    for i, ev in enumerate([8.0, 10.0, 12.0, 14.0, None, None, None, None]):
        cohorte[f"T{i}"] = (_ratios(f"T{i}", ev_ebit=ev), "es", "industrial")
    notas = puntuar(cohorte, cfg)
    assert notas["T0"].valoracion == pytest.approx(87.5)
    assert notas["T3"].valoracion == pytest.approx(12.5)
    # Sin EV/EBIT sigue yendo al peor percentil: no saber no es estar barata.
    assert notas["T4"].valoracion == 0.0


# --------------------------------------------------------------------------
# EV: deuda neta que falta y precio sin ajustar
# --------------------------------------------------------------------------


def _ultimo(**kw):
    base = {
        "ev": None,
        "acciones_en_circulacion": 1_000.0,
        "deuda_neta": 500.0,
        "divisa_reporte": "EUR",
        "divisa_cotizacion": "EUR",
    }
    base.update(kw)
    return pd.Series(base)


def test_sin_deuda_neta_no_hay_ev():
    ev, motivo = valor_empresa(_ultimo(deuda_neta=None), 10.0)
    assert ev is None
    assert motivo == "sin_deuda_neta"

    ev, motivo = valor_empresa(_ultimo(deuda_neta=np.nan), 10.0)
    assert ev is None and motivo == "sin_deuda_neta"


def test_una_deuda_neta_cero_es_un_dato_y_si_da_ev():
    ev, motivo = valor_empresa(_ultimo(deuda_neta=0.0), 10.0)
    assert ev == pytest.approx(10_000.0)
    assert motivo is None


def test_el_ev_usa_el_precio_sin_ajustar(cfg, instantanea, monkeypatch):
    """Se fabrican precios con dividendos (bruto un 30 % por encima del
    ajustado) y se mira con que precio se pide el EV en cada revision."""
    precios = instantanea.precios.copy()
    precios["cierre_bruto"] = precios["cierre"] * 1.3
    con_dividendos = Instantanea(
        precios=precios,
        fundamentales=instantanea.fundamentales,
        fx=instantanea.fx,
        sectores=instantanea.sectores,
        fecha_descarga=instantanea.fecha_descarga,
        origen=instantanea.origen,
    ).preparar(cfg)

    llamadas: list[tuple[str, dt.date, float | None]] = []
    original = fundamental_mod.ratios_de

    def espia(ticker, fundamentales, cfg_, fecha, precio_local=None):
        llamadas.append((ticker, fecha, precio_local))
        return original(ticker, fundamentales, cfg_, fecha, precio_local)

    monkeypatch.setattr(fundamental_mod, "ratios_de", espia)
    backtest_mod.ejecutar(con_dividendos, cfg, dt.date(2023, 1, 1), dt.date(2023, 3, 31))

    con_precio = [c for c in llamadas if c[2] is not None]
    assert len(con_precio) > 20
    for ticker, fecha, precio in con_precio[:200]:
        vista = con_dividendos.vista(fecha)
        serie = vista.serie(ticker)
        i = vista.posicion_hasta(ticker)
        assert precio == pytest.approx(float(serie.cierre_bruto[i]))
        assert precio == pytest.approx(float(serie.cierre[i]) * 1.3)


# --------------------------------------------------------------------------
# Recurso al bloque, y que el informe lo cuente
# --------------------------------------------------------------------------


def test_un_mercado_pequeno_se_puntua_contra_su_bloque(cfg):
    """Con la cohorte de todos los mercados a la vez (tarea B2), un mercado con
    pocas empresas se compara con su bloque en vez de quedar insuficiente."""
    minimo = cfg.reglas.fundamental.min_empresas_percentil
    cohorte = {}
    for i in range(minimo):
        cohorte[f"ES{i}"] = (_ratios(f"ES{i}", ev_ebit=10.0 + i), "es", "industrial")
    cohorte["DE0"] = (_ratios("DE0", ev_ebit=9.0), "de", "industrial")
    notas = puntuar(cohorte, cfg)
    assert notas["DE0"].cohorte_usada == CohorteUsada.BLOQUE
    assert notas["DE0"].n_cohorte == minimo + 1
    assert notas["ES0"].cohorte_usada == CohorteUsada.MERCADO


def _eventos(cohortes):
    return pd.DataFrame(
        [
            {
                "fecha": dt.date(2024, 1, 5),
                "tipo": "orden",
                "mercado": m,
                "ticker": f"T{i}",
                "motivo": "",
                "cohorte": c,
                "n_cohorte": 3,
            }
            for i, (m, c) in enumerate(cohortes)
        ]
    )


def test_el_informe_cuenta_las_compras_puntuadas_contra_el_bloque(cfg):
    ev = _eventos([("es", "mercado"), ("de", "bloque"), ("de", "bloque"), ("br", "insuficiente")])
    avisos = informe_mod._aviso_cohortes(ev, cfg)
    assert len(avisos) == 1
    texto = avisos[0].texto
    assert "3 de 4 compras" in texto
    assert "de: 2 contra el bloque" in texto
    assert "br: 1 con cohorte insuficiente" in texto
    assert avisos[0].gravedad == "importante"


def test_sin_compras_fuera_de_mercado_no_hay_aviso(cfg):
    assert informe_mod._aviso_cohortes(_eventos([("es", "mercado")]), cfg) == []


def test_las_ordenes_del_backtest_llevan_su_cohorte(cfg, instantanea):
    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2022, 1, 1), dt.date(2024, 12, 31))
    ev = r.eventos_df
    ordenes = ev[ev["tipo"] == "orden"]
    assert not ordenes.empty
    assert set(ordenes["cohorte"]) <= {"mercado", "bloque", "insuficiente"}
    assert (ordenes["n_cohorte"] > 0).all()
