"""Robustez estadistica del backtest (tarea V1): intervalo del Sharpe y tramos.

Lo que se comprueba:

- el Sharpe del que se da el intervalo es exactamente el del informe;
- con la misma semilla sale siempre el mismo intervalo;
- una curva que sube con constancia tiene el intervalo por encima de cero, y
  una sin tendencia lo tiene a los dos lados;
- el remuestreo por bloques conserva las rachas, que es para lo que existe;
- los tramos cubren el periodo entero, sin huecos ni solapes, y encadenados dan
  la rentabilidad total;
- el informe lo pinta, y avisa cuando el intervalo incluye el cero.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from estrategia import backtest as backtest_mod
from estrategia import informe as informe_mod
from estrategia import metricas as metricas_mod
from estrategia import validacion as validacion_mod
from estrategia.informe_html import a_html


def _curva(retornos_semanales: np.ndarray, inicio=dt.date(2015, 1, 5)) -> pd.DataFrame:
    """Curva diaria de lunes a viernes cuyas semanas rinden lo que se pide.

    Empieza en lunes para que cada semana pedida sea una semana del calendario,
    que es como la corta `metricas.serie_periodica`.
    """
    fechas, valores = [], []
    valor = 10_000.0
    dia = inicio
    for r in retornos_semanales:
        diario = (1.0 + r) ** (1 / 5) - 1.0
        for _ in range(5):
            while dia.weekday() >= 5:
                dia += dt.timedelta(days=1)
            valor *= 1.0 + diario
            fechas.append(dia)
            valores.append(valor)
            dia += dt.timedelta(days=1)
    n = len(fechas)
    return pd.DataFrame(
        {
            "fecha": fechas,
            "valor": valores,
            "efectivo": [0.0] * n,
            "n_posiciones": [1] * n,
            "exposicion": [1.0] * n,
        }
    )


def _con(cfg, **validacion):
    val = cfg.reglas.validacion.model_copy(update=validacion)
    return cfg.model_copy(update={"reglas": cfg.reglas.model_copy(update={"validacion": val})})


def _ruido(media: float, desviacion: float, n: int, semilla: int = 7) -> np.ndarray:
    return np.random.default_rng(semilla).normal(media, desviacion, n)


SIN_OPERACIONES = pd.DataFrame()


def test_el_sharpe_es_el_mismo_que_el_del_informe(cfg):
    curva = _curva(_ruido(0.002, 0.02, 200))
    rob = validacion_mod.robustez(curva, SIN_OPERACIONES, cfg)
    assert rob.motivo is None
    assert rob.sharpe == metricas_mod.resumir(curva, SIN_OPERACIONES, cfg).sharpe

    retornos, rf, por_ano = metricas_mod.rentabilidades_periodicas(
        curva,
        cfg.reglas.metricas.tasa_libre_riesgo_anual,
        cfg.reglas.metricas.periodicidad_sharpe,
    )
    assert validacion_mod._sharpe_muestra(retornos.to_numpy(), rf, por_ano) == pytest.approx(
        rob.sharpe, rel=1e-12
    )


def test_con_la_misma_semilla_sale_el_mismo_intervalo(cfg):
    curva = _curva(_ruido(0.001, 0.02, 200))
    a = validacion_mod.robustez(curva, SIN_OPERACIONES, cfg)
    b = validacion_mod.robustez(curva, SIN_OPERACIONES, cfg)
    assert (a.sharpe_inferior, a.sharpe_superior) == (b.sharpe_inferior, b.sharpe_superior)

    otra = validacion_mod.robustez(curva, SIN_OPERACIONES, _con(cfg, semilla=1))
    assert (otra.sharpe_inferior, otra.sharpe_superior) != (a.sharpe_inferior, a.sharpe_superior)


def test_una_curva_que_sube_con_constancia_tiene_el_intervalo_sobre_cero(cfg):
    rob = validacion_mod.robustez(_curva(_ruido(0.006, 0.01, 260)), SIN_OPERACIONES, cfg)
    assert rob.sharpe_inferior > 0
    assert rob.prob_sharpe_positivo > 0.99
    assert not rob.intervalo_incluye_cero
    assert rob.sharpe_inferior <= rob.sharpe <= rob.sharpe_superior


def test_una_curva_sin_tendencia_tiene_el_intervalo_a_los_dos_lados(cfg):
    """Rentabilidad media igual a la del activo sin riesgo: Sharpe cero, mas o
    menos el ruido. El intervalo tiene que decir que no se sabe."""
    rf = (1.0 + cfg.reglas.metricas.tasa_libre_riesgo_anual) ** (1 / 52) - 1.0
    ruido = _ruido(0.0, 0.02, 150)
    rob = validacion_mod.robustez(_curva(rf + ruido - ruido.mean()), SIN_OPERACIONES, cfg)
    assert rob.intervalo_incluye_cero
    assert 0.2 < rob.prob_sharpe_positivo < 0.8


def test_el_remuestreo_por_bloques_coge_semanas_seguidas():
    rng = np.random.default_rng(0)
    indices = validacion_mod.remuestreo_por_bloques(rng, 23, 4)
    assert len(indices) == 23
    assert indices.min() >= 0 and indices.max() <= 22
    for bloque in np.split(indices[:20], 5):
        assert list(bloque) == list(range(bloque[0], bloque[0] + 4))
    # Un bloque mas largo que la serie se queda en la serie entera.
    assert list(validacion_mod.remuestreo_por_bloques(rng, 3, 10)) == [0, 1, 2]


def test_con_rachas_los_bloques_ensanchan_el_intervalo(cfg):
    """Remuestrear semanas sueltas en una serie con rachas da un intervalo mas
    estrecho de lo que la serie justifica: para eso estan los bloques."""
    rng = np.random.default_rng(3)
    ruido = rng.normal(0.0, 0.01, 300)
    rachas = np.empty_like(ruido)
    rachas[0] = ruido[0]
    for i in range(1, ruido.size):
        rachas[i] = 0.8 * rachas[i - 1] + ruido[i]
    curva = _curva(0.001 + rachas)

    sueltas = validacion_mod.robustez(
        curva, SIN_OPERACIONES, _con(cfg, bootstrap_bloque_periodos=1)
    )
    bloques = validacion_mod.robustez(
        curva, SIN_OPERACIONES, _con(cfg, bootstrap_bloque_periodos=8)
    )
    ancho = lambda r: r.sharpe_superior - r.sharpe_inferior  # noqa: E731
    assert ancho(bloques) > ancho(sueltas)


def test_los_tramos_cubren_el_periodo_y_encadenados_dan_el_total(cfg):
    curva = _curva(_ruido(0.002, 0.02, 200))
    rob = validacion_mod.robustez(curva, SIN_OPERACIONES, cfg)
    tramos = rob.tramos

    assert len(tramos) == cfg.reglas.validacion.walk_forward_tramos
    assert tramos["desde"].iloc[0] == curva["fecha"].iloc[0]
    assert tramos["hasta"].iloc[-1] == curva["fecha"].iloc[-1]
    assert list(tramos["desde"].iloc[1:]) == list(tramos["hasta"].iloc[:-1])

    total = curva["valor"].iloc[-1] / curva["valor"].iloc[0] - 1.0
    assert float(np.prod(1.0 + tramos["rentabilidad"]) - 1.0) == pytest.approx(total)


def test_cada_operacion_cuenta_en_un_solo_tramo(cfg):
    curva = _curva(_ruido(0.002, 0.02, 200))
    fechas = list(curva["fecha"])
    operaciones = pd.DataFrame({"fecha_entrada": fechas[::7]})
    rob = validacion_mod.robustez(curva, operaciones, cfg)
    assert int(rob.tramos["operaciones"].sum()) == len(operaciones)


def test_sin_datos_suficientes_lo_dice_en_vez_de_inventar(cfg):
    rob = validacion_mod.robustez(_curva(_ruido(0.002, 0.02, 3)), SIN_OPERACIONES, cfg)
    assert rob.motivo is not None
    assert not rob.intervalo_incluye_cero
    assert rob.tramos.empty


def test_los_parametros_viven_en_la_configuracion(cfg_real):
    val = cfg_real.reglas.validacion
    assert val.bootstrap_muestras > 0
    assert 0 < val.bootstrap_confianza < 1
    assert val.bootstrap_bloque_periodos > 0
    assert val.walk_forward_tramos > 1


def test_el_informe_pinta_la_robustez_y_avisa_si_el_sharpe_puede_ser_suerte(cfg, instantanea):
    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2021, 1, 1), dt.date(2022, 12, 31))
    rob = validacion_mod.robustez(r.curva, r.operaciones_df, cfg)
    inf = informe_mod.construir(r, cfg, instantanea, robustez=rob)

    texto = informe_mod.a_markdown(inf)
    assert "## Robustez (periodo de diseño)" in texto
    assert "Tramos con rentabilidad positiva" in texto
    assert "Robustez (periodo de diseño)" in a_html(inf)

    avisa = any(a.clave == "sharpe_incierto" for a in inf.avisos)
    assert avisa == rob.intervalo_incluye_cero


def test_sin_robustez_el_informe_no_cambia(cfg, instantanea):
    """El informe semanal no la calcula: solo `estrategia validar`."""
    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2021, 1, 1), dt.date(2022, 12, 31))
    inf = informe_mod.construir(r, cfg, instantanea)
    assert "Robustez" not in informe_mod.a_markdown(inf)
    assert not any(a.clave == "sharpe_incierto" for a in inf.avisos)
