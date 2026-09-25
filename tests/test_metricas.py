"""Tests de las metricas de la FASE 7.

Cada test esta escrito para caer con la implementacion ingenua de la metrica que
comprueba, no solo para pasar con la correcta. Un test de una metrica que solo
verifica "devuelve un float" no protege de nada.
"""

from __future__ import annotations

import datetime as dt
import re

import numpy as np
import pandas as pd
import pytest
from estrategia import metricas as metricas_mod


def _curva(valores: list[float]) -> pd.DataFrame:
    """Curva de capital semanal, para que `serie_periodica` no agrupe nada."""
    fechas = [dt.date(2020, 1, 6) + dt.timedelta(weeks=i) for i in range(len(valores))]
    return pd.DataFrame({"fecha": fechas, "valor": valores, "exposicion": [1.0] * len(valores)})


def _operaciones(resultados: list[float], dias: list[int] | None = None) -> pd.DataFrame:
    dias = dias if dias is not None else [10] * len(resultados)
    return pd.DataFrame(
        {
            "resultado_base": resultados,
            "ganadora": [r > 0 for r in resultados],
            "dias": dias,
            "acciones": [100.0] * len(resultados),
            "precio_entrada_base": [10.0] * len(resultados),
            "precio_salida_base": [10.0] * len(resultados),
        }
    )


# --- Sortino ---------------------------------------------------------------


def test_sortino_ignora_la_volatilidad_al_alza():
    """Dos curvas con la misma media y la misma desviacion total.

    Una sube a saltos; la otra baja igual de fuerte. El Sharpe las puntua
    parecido porque mide la desviacion completa. El Sortino tiene que separarlas:
    penalizar la volatilidad de arriba es justo lo que no queremos.
    """
    # Sube siempre, a ritmos distintos: volatilidad alta, ninguna caida.
    solo_arriba = _curva([100, 101, 108, 109, 118, 119, 130])
    # Mismo destino aproximado, pero pasando por caidas.
    con_caidas = _curva([100, 92, 108, 96, 118, 104, 130])

    s_arriba = metricas_mod.sortino(solo_arriba, 0.0, "semanal")
    s_caidas = metricas_mod.sortino(con_caidas, 0.0, "semanal")

    assert np.isnan(s_arriba), "sin una sola semana en negativo no esta definido"
    assert np.isfinite(s_caidas)
    assert s_caidas > 0, "termina muy por encima de donde empezo"


def test_sortino_penaliza_mas_una_caida_grande_que_muchas_pequenas():
    """La desviacion a la baja es cuadratica: una caida gorda pesa mas.

    Con la implementacion que solo cuenta CUANTAS semanas son negativas —en vez
    de cuanto caen— las dos curvas darian lo mismo.
    """
    muchas_pequenas = _curva([100, 99, 101, 100, 102, 101, 103])
    una_grande = _curva([100, 101, 102, 103, 104, 105, 80])

    assert metricas_mod.sortino(una_grande, 0.0, "semanal") < metricas_mod.sortino(
        muchas_pequenas, 0.0, "semanal"
    )


def test_sortino_sin_caidas_no_es_cero():
    """El caso que motiva el `nan`.

    Una estrategia que nunca pierde tiene el mejor Sortino posible. Devolver 0.0
    la pondria a la cola de cualquier ranking, que es exactamente lo contrario
    de lo que ha pasado.
    """
    resultado = metricas_mod.sortino(_curva([100, 101, 102, 103, 104]), 0.0, "semanal")
    assert np.isnan(resultado)
    assert resultado != 0.0


# --- Profit factor ---------------------------------------------------------


def test_profit_factor_distingue_dos_estrategias_con_el_mismo_pct_de_aciertos():
    """Las dos aciertan 3 de 4. Una gana dinero y la otra lo pierde.

    Es el motivo de existir de esta metrica: el porcentaje de ganadoras por si
    solo no distingue entre ganar y arruinarse.
    """
    buena = _operaciones([10.0, 10.0, 10.0, -5.0])
    mala = _operaciones([10.0, 10.0, 10.0, -90.0])

    assert metricas_mod.profit_factor(buena) == 6.0
    assert metricas_mod.profit_factor(mala) < 1.0

    # Y el porcentaje de ganadoras, que es lo que ya habia, las da por iguales.
    assert buena["ganadora"].mean() == mala["ganadora"].mean()


def test_profit_factor_sin_perdedoras_no_es_cero():
    resultado = metricas_mod.profit_factor(_operaciones([10.0, 20.0]))
    assert np.isnan(resultado)


def test_profit_factor_sin_operaciones_no_es_cero():
    """Cero operaciones no es 'profit factor cero': es que no hay dato."""
    assert np.isnan(metricas_mod.profit_factor(pd.DataFrame()))


# --- Rotacion --------------------------------------------------------------


def test_rotacion_de_una_cartera_entera_en_un_ano_es_una_vez():
    """La comprobacion de la division entre dos.

    Un ano, patrimonio 1.000, y se compra y se vende una cartera completa de
    1.000. Eso es rotar la cartera UNA vez. Sin dividir entre dos saldria 2.
    """
    fechas = [dt.date(2020, 1, 1), dt.date(2020, 12, 31)]
    curva = pd.DataFrame({"fecha": fechas, "valor": [1000.0, 1000.0], "exposicion": [1.0, 1.0]})
    ops = pd.DataFrame(
        {
            "resultado_base": [0.0],
            "ganadora": [False],
            "dias": [100],
            "acciones": [100.0],
            "precio_entrada_base": [10.0],
            "precio_salida_base": [10.0],
        }
    )
    # `approx` y no `==`: del 1 de enero al 31 de diciembre hay 365 dias y el
    # ano del motor son 365.25, asi que el resultado exacto es 1.0007. Exigir
    # el 1.0 clavado seria exigir que el motor se equivoque de calendario.
    assert metricas_mod.rotacion_anual(curva, ops) == pytest.approx(1.0, abs=1e-3)


def test_rotacion_se_anualiza():
    """La misma actividad en medio ano es el doble de rotacion anual."""
    medio = pd.DataFrame(
        {
            "fecha": [dt.date(2020, 1, 1), dt.date(2020, 7, 1)],
            "valor": [1000.0, 1000.0],
            "exposicion": [1.0, 1.0],
        }
    )
    ops = pd.DataFrame(
        {
            "resultado_base": [0.0],
            "ganadora": [False],
            "dias": [50],
            "acciones": [100.0],
            "precio_entrada_base": [10.0],
            "precio_salida_base": [10.0],
        }
    )
    assert metricas_mod.rotacion_anual(medio, ops) > 1.9


# --- Dias en cartera -------------------------------------------------------


def test_dias_medios_en_cartera():
    assert metricas_mod.dias_medios_en_cartera(_operaciones([1.0, 1.0], [10, 20])) == 15.0


def test_dias_medios_sin_operaciones():
    assert metricas_mod.dias_medios_en_cartera(pd.DataFrame()) == 0.0


# --- Presentacion ----------------------------------------------------------


def test_una_metrica_no_disponible_nunca_se_imprime_como_nan():
    """Un informe que dice 'nan' donde deberia decir 'no disponible' es peor que
    uno que no dice nada: parece un numero."""
    assert metricas_mod.como_texto(float("nan")) == metricas_mod.NO_DISPONIBLE
    assert metricas_mod.como_texto(float("inf")) == metricas_mod.NO_DISPONIBLE
    assert metricas_mod.como_texto(1.234) == "1.23"


# --- Que lleguen al informe ------------------------------------------------


def test_las_metricas_nuevas_llegan_al_informe(cfg, instantanea):
    """El guardarrail de la FASE 6, aplicado aqui.

    En la FASE 5 nueve magnitudes se calculaban y se tiraban al escribir en la
    base de datos, y nada fallaba porque nadie comprobaba el otro extremo del
    camino. Una metrica que `resumir` calcula pero el informe no imprime tiene
    exactamente la misma forma: trabajo hecho que no llega a nadie.
    """
    import datetime as dt2

    from estrategia import backtest as backtest_mod
    from estrategia.informe import a_markdown, construir

    r = backtest_mod.ejecutar(instantanea, cfg, dt2.date(2019, 1, 1), dt2.date(2022, 12, 31))
    texto = a_markdown(construir(r, cfg, instantanea))

    for etiqueta in ("Sortino", "Profit factor", "Días medios en cartera", "Rotación anual"):
        assert etiqueta in texto, f"'{etiqueta}' se calcula pero no aparece en el informe"

    # Con limites de palabra: "financiero", "financiera" y "finanzas" contienen
    # la secuencia "nan", asi que un `in` a pelo daria falsos positivos en el
    # aviso legal, que aparece en todos los informes.
    assert not re.search(r"\bnan\b", texto, re.IGNORECASE), (
        "una metrica no disponible tiene que decirlo con palabras, no imprimir nan"
    )


# --- Comparacion contra la referencia --------------------------------------


def _ref(valores: list[float], desde: int = 0) -> pd.Series:
    """Referencia semanal alineada con `_curva`."""
    fechas = [dt.date(2020, 1, 6) + dt.timedelta(weeks=i + desde) for i in range(len(valores))]
    return pd.Series(valores, index=pd.Index(fechas))


def test_batir_a_la_referencia_da_exceso_positivo(cfg):
    curva = _curva([100, 104, 108, 112, 116, 120, 124])
    ref = _ref([100, 101, 102, 103, 104, 105, 106])

    c = metricas_mod.comparar_con_referencia("prueba", curva, ref, cfg)

    assert c is not None
    assert c.exceso_anualizado > 0
    assert c.anualizada_estrategia > c.anualizada_referencia


def test_el_alfa_descuenta_el_riesgo_asumido(cfg):
    """El test que justifica calcular alfa y no solo el exceso.

    La estrategia hace exactamente el DOBLE que el mercado cada semana: sube el
    doble y baja el doble. Su exceso es positivo porque el mercado subio, pero
    no ha aportado nada propio: solo ha ido apalancada. La beta tiene que salir
    2 y el alfa pegada a cero.

    Con la implementacion que solo resta rentabilidades, esto pasaria por un
    hallazgo.
    """
    mercado = [100.0]
    for r in (0.02, -0.01, 0.03, 0.01, -0.02, 0.02):
        mercado.append(mercado[-1] * (1 + r))

    estrategia = [100.0]
    for r in (0.04, -0.02, 0.06, 0.02, -0.04, 0.04):
        estrategia.append(estrategia[-1] * (1 + r))

    c = metricas_mod.comparar_con_referencia("doble", _curva(estrategia), _ref(mercado), cfg)

    assert c is not None
    assert c.exceso_anualizado > 0, "gana mas que el mercado, en bruto"
    assert c.beta == pytest.approx(2.0, abs=0.05), "se mueve el doble"
    assert abs(c.alfa_jensen) < 0.02, f"no aporta merito propio, y el alfa {c.alfa_jensen} lo dice"


def test_la_comparacion_no_usa_el_relleno_anterior_al_lanzamiento(cfg):
    """El fallo que motiva `inicio_real_referencia`.

    `curva_referencia` rellena hacia atras para poder pintar la linea entera. Si
    la comparacion midiera sobre ese relleno, el tramo anterior al ETF aparece
    como una referencia plana al 0% y la estrategia se lleva gratis todo lo que
    ganara ahi.
    """
    curva = _curva([100, 130, 140, 141, 142, 143, 144])
    # La referencia "existe" desde la semana 3; antes es relleno plano.
    ref = _ref([100.0, 100.0, 100.0, 100.0, 120.0, 130.0, 140.0])
    real_desde = dt.date(2020, 1, 6) + dt.timedelta(weeks=3)

    ingenua = metricas_mod.comparar_con_referencia("r", curva, ref, cfg)
    honesta = metricas_mod.comparar_con_referencia("r", curva, ref, cfg, desde=real_desde)

    assert ingenua is not None and honesta is not None
    assert honesta.recortada is True
    assert ingenua.recortada is False
    assert honesta.desde == real_desde
    assert honesta.exceso_anualizado < ingenua.exceso_anualizado, (
        "medir contra el relleno infla el exceso; es justo el sesgo que se evita"
    )


def test_una_referencia_plana_no_produce_un_alfa_inventado(cfg):
    """Sin varianza en el mercado no hay beta, y sin beta no hay alfa de Jensen.

    Devolver 0.0 aqui seria afirmar algo que no se ha medido.
    """
    c = metricas_mod.comparar_con_referencia(
        "plana", _curva([100, 110, 120, 130, 140]), _ref([100.0] * 5), cfg
    )
    assert c is not None
    assert np.isnan(c.beta)
    assert np.isnan(c.alfa_jensen)


def test_sin_tramo_comun_no_hay_comparacion(cfg):
    """Mejor nada que un numero calculado sobre tres puntos sueltos."""
    curva = _curva([100, 101, 102, 103])
    lejos = _ref([100.0, 101.0, 102.0], desde=500)
    assert metricas_mod.comparar_con_referencia("lejana", curva, lejos, cfg) is None
