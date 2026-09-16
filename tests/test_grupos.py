"""Tests de los cinco grupos fundamentales de §14 (FASE 5)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from estrategia.grupos import (
    DIRECCION,
    GRUPOS,
    METRICAS,
    POR_GRUPO,
    magnitudes_de,
    puntuar,
)
from estrategia.tipos import CohorteUsada


def _historico(**series) -> pd.DataFrame:
    n = len(next(iter(series.values())))
    base = {
        "periodo": ["anual"] * n,
        "fin_periodo": [dt.date(2020 + i, 12, 31) for i in range(n)],
    }
    return pd.DataFrame({**base, **series})


# ---------------------------------------------------------------------------
# Catalogo
# ---------------------------------------------------------------------------


def test_el_catalogo_cubre_los_cinco_grupos_de_la_seccion_14():
    assert set(GRUPOS) == {
        "crecimiento",
        "rentabilidad",
        "salud_financiera",
        "calidad",
        "valoracion",
    }
    assert all(POR_GRUPO[g] for g in GRUPOS), "ningun grupo puede quedarse vacio"
    assert len(METRICAS) == sum(len(POR_GRUPO[g]) for g in GRUPOS)


def test_toda_metrica_declara_hacia_donde_puntua():
    """Sin direccion, media docena puntuarian del reves y pareceria razonable.

    Un ROE alto es bueno y un PER alto es malo. Es la clase de error que no
    rompe nada: solo ordena el ranking al contrario.
    """
    assert set(DIRECCION.values()) <= {"alto", "bajo"}
    assert DIRECCION["roe"] == "alto"
    assert DIRECCION["per"] == "bajo"
    assert DIRECCION["deuda_patrimonio"] == "bajo"
    assert DIRECCION["variacion_beneficios"] == "bajo"
    assert DIRECCION["rentabilidad_fcl"] == "alto"


# ---------------------------------------------------------------------------
# Metricas de una empresa
# ---------------------------------------------------------------------------


def test_el_crecimiento_se_mide_entre_extremos_a_tres_anos():
    h = _historico(ventas=[100.0, 110.0, 120.0, 133.1])
    assert magnitudes_de(h)["crecimiento_ventas"] == pytest.approx(0.10, abs=1e-6)


def test_no_hay_crecimiento_desde_una_base_negativa():
    """Pasar de perder 10 a perder 5 no es «crecer un 50 %»."""
    h = _historico(flujo_caja_libre=[-10.0, -8.0, -6.0, -5.0])
    assert magnitudes_de(h)["crecimiento_fcl"] is None


def test_caer_en_perdidas_es_el_peor_crecimiento_posible():
    h = _historico(beneficio_neto=[100.0, 90.0, 50.0, -20.0], bpa=[1.0, 0.9, 0.5, -0.2])
    assert magnitudes_de(h)["crecimiento_bpa"] == -1.0


def test_un_patrimonio_negativo_no_produce_un_roe_positivo():
    """La trampa de signo clasica: perdidas partido por patrimonio negativo."""
    h = _historico(beneficio_neto=[-50.0], patrimonio_neto=[-100.0])
    assert magnitudes_de(h)["roe"] is None


def test_un_ebitda_negativo_no_abarata_la_empresa():
    h = _historico(ebitda=[-40.0], ventas=[100.0])
    assert magnitudes_de(h, capitalizacion=1000.0, ev=1200.0)["ev_ebitda"] is None


def test_un_beneficio_negativo_no_produce_un_per():
    h = _historico(beneficio_neto=[-40.0], ventas=[100.0])
    m = magnitudes_de(h, capitalizacion=1000.0)
    assert m["per"] is None
    assert m["precio_ventas"] == pytest.approx(10.0), "el de ventas si se puede"


def test_la_variabilidad_de_una_empresa_en_perdidas_no_sale_negativa():
    """Con media negativa, dividir sin valor absoluto la haria la mas estable."""
    h = _historico(beneficio_neto=[-100.0, -50.0, -150.0, -80.0])
    v = magnitudes_de(h)["variacion_beneficios"]
    assert v is not None and v > 0


def test_un_infinito_nunca_sale_del_calculo():
    """Un infinito envenena cualquier media o percentil posterior sin avisar."""
    h = _historico(beneficio_neto=[10.0], patrimonio_neto=[0.0], ventas=[0.0])
    for valor in magnitudes_de(h, capitalizacion=100.0).values():
        assert valor is None or np.isfinite(valor)


# ---------------------------------------------------------------------------
# Puntuacion por cohorte
# ---------------------------------------------------------------------------


def _cohorte(n: int, **variando) -> tuple[dict, dict]:
    mags, cohortes = {}, {}
    for i in range(n):
        t = f"T{i}"
        mags[t] = dict.fromkeys(DIRECCION)
        for metrica, valores in variando.items():
            mags[t][metrica] = valores[i]
        cohortes[t] = "x"
    return mags, cohortes


def test_cuando_menos_es_mejor_el_percentil_se_invierte():
    """Un PER bajo tiene que puntuar ALTO."""
    mags, cohortes = _cohorte(10, per=[float(i) for i in range(1, 11)])
    notas = puntuar(mags, cohortes, min_cohorte=5)
    assert notas["T0"].grupos["valoracion"] > notas["T9"].grupos["valoracion"]


def test_una_metrica_sin_dato_no_puntua_cincuenta():
    """Se descarta y el grupo promedia sobre las que si lo tienen (D-8).

    Imputar un valor medio no es conservador: inventa un dato que mueve el
    ranking sin que nadie lo haya medido.
    """
    mags, cohortes = _cohorte(
        10,
        roe=[float(i) for i in range(10)],
        roa=[None] * 10,
        margen_bruto=[None] * 10,
        margen_operativo=[None] * 10,
        margen_neto=[None] * 10,
    )
    notas = puntuar(mags, cohortes, min_cohorte=5)
    assert notas["T9"].metricas_usadas["rentabilidad"] == 1
    # Con una sola metrica, la nota del grupo es su percentil, no una media
    # diluida con cuatro cincuentas.
    assert notas["T9"].grupos["rentabilidad"] > 90


def test_un_grupo_sin_ninguna_metrica_se_queda_sin_nota():
    mags, cohortes = _cohorte(10, roe=[float(i) for i in range(10)])
    notas = puntuar(mags, cohortes, min_cohorte=5)
    assert notas["T0"].grupos["valoracion"] is None
    assert notas["T0"].grupos["rentabilidad"] is not None
    assert notas["T0"].fundamental is not None, "el pilar promedia lo que hay"


def test_una_cohorte_pequena_se_refunde_y_queda_marcado():
    """Un percentil sobre tres empresas reparte un 0 y un 100 por aritmetica.

    Quien lea el score tiene derecho a saber que su cohorte no significaba nada.
    """
    mags = {f"T{i}": dict.fromkeys(DIRECCION, float(i)) for i in range(4)}
    cohortes = {"T0": "a", "T1": "a", "T2": "b", "T3": "b"}
    notas = puntuar(mags, cohortes, min_cohorte=8)
    assert all(n.cohorte_usada == CohorteUsada.BLOQUE for n in notas.values())
    assert all(n.n_cohorte == 4 for n in notas.values())


def test_una_cohorte_suficiente_se_respeta():
    mags, cohortes = _cohorte(10, roe=[float(i) for i in range(10)])
    notas = puntuar(mags, cohortes, min_cohorte=8)
    assert notas["T0"].cohorte_usada == CohorteUsada.MERCADO
    assert notas["T0"].n_cohorte == 10


def test_los_pesos_se_renormalizan_sobre_los_grupos_con_nota():
    """Un grupo ausente no debe arrastrar el pilar hacia abajo."""
    mags, cohortes = _cohorte(10, roe=[float(i) for i in range(10)])
    notas = puntuar(mags, cohortes, min_cohorte=5)
    nota = notas["T9"]
    assert nota.grupos["rentabilidad"] is not None
    assert nota.fundamental == pytest.approx(nota.grupos["rentabilidad"])
