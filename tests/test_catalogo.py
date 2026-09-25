"""Tests del catalogo de indicadores (FASE 4).

Los tres primeros recorren **todo el registro**. Esa es la razon de fondo para
tener un registro y no treinta funciones sueltas: un indicador nuevo queda
cubierto por ellos el dia que se escribe, sin que su autor tenga que acordarse
de nada.

El que mas vale es `test_ningun_indicador_mira_hacia_delante`. Si falla, el
indicador esta usando datos que ese dia no existian, y cualquier backtest que lo
incluya deja de valer por bueno que parezca.
"""

from __future__ import annotations

import numpy as np
import pytest
from estrategia.catalogo import (
    REGISTRO,
    SESIONES_ANO,
    Ventana,
    calcular,
    ema_vector,
    registrar,
)


def _ventana(n: int = 600, semilla: int = 3, referencia: bool = True) -> Ventana:
    """Serie sintetica y determinista, con OHLC coherente."""
    rng = np.random.default_rng(semilla)
    cierre = 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.012, n))
    ruido = np.abs(rng.normal(0.0, 0.004, n))
    indice = 100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.009, n))
    return Ventana(
        fechas=np.arange(n),
        apertura=cierre * (1.0 + rng.normal(0.0, 0.002, n)),
        maximo=cierre * (1.0 + ruido),
        minimo=cierre * (1.0 - ruido),
        cierre=cierre,
        cierre_bruto=cierre,
        volumen=rng.integers(100_000, 500_000, n).astype(float),
        referencia=indice if referencia else None,
    )


def _recortar(v: Ventana, hasta: int) -> Ventana:
    """La misma ventana como se veia el dia `hasta`, sin nada posterior."""
    return Ventana(
        fechas=v.fechas[: hasta + 1],
        apertura=v.apertura[: hasta + 1],
        maximo=v.maximo[: hasta + 1],
        minimo=v.minimo[: hasta + 1],
        cierre=v.cierre[: hasta + 1],
        cierre_bruto=v.cierre_bruto[: hasta + 1],
        volumen=v.volumen[: hasta + 1],
        referencia=None if v.referencia is None else v.referencia[: hasta + 1],
    )


@pytest.fixture(scope="module")
def ventana() -> Ventana:
    return _ventana()


# ---------------------------------------------------------------------------
# Los que recorren todo el registro
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nombre", sorted(REGISTRO))
def test_ningun_indicador_mira_hacia_delante(nombre, ventana):
    """Recortar la serie por el final no cambia nada de lo anterior al corte.

    Es la definicion operativa de "ventana hacia atras". Si el valor del dia D
    cambia segun lo que pase despues de D, el indicador esta usando informacion
    del futuro, que es el sesgo que invalida un backtest entero.

    Se compara el prefijo completo y no solo el ultimo punto: un indicador
    recursivo mal escrito puede acertar en el corte y fallar antes.
    """
    corte = 450
    indicador = REGISTRO[nombre]

    completo = indicador.calcular(ventana)[: corte + 1]
    recortado = indicador.calcular(_recortar(ventana, corte))

    np.testing.assert_allclose(
        completo,
        recortado,
        rtol=1e-9,
        atol=1e-9,
        equal_nan=True,
        err_msg=f"{nombre} cambia al conocerse el futuro",
    )


@pytest.mark.parametrize("nombre", sorted(REGISTRO))
def test_ningun_indicador_declara_menos_historico_del_que_usa(nombre, ventana):
    """`ventana_minima` no puede quedarse corta.

    Declararla de menos hace que se sirva un numero calculado sobre cuatro
    sesiones como si valiera lo mismo que uno calculado sobre doscientas.
    Pasarse es conservador y no rompe nada; quedarse corto, si.
    """
    indicador = REGISTRO[nombre]
    valores = indicador.calcular(ventana)
    validos = np.where(~np.isnan(valores))[0]
    assert len(validos), f"{nombre} no produce ningun valor"
    assert int(validos[0]) >= indicador.ventana_minima - 1, (
        f"{nombre} declara {indicador.ventana_minima} sesiones pero da dato "
        f"en la {int(validos[0]) + 1}"
    )


@pytest.mark.parametrize("nombre", sorted(REGISTRO))
def test_todo_indicador_devuelve_un_vector_alineado(nombre, ventana):
    """Un vector mas corto desplazaria todos los valores sin que nada falle."""
    valores = REGISTRO[nombre].calcular(ventana)
    assert valores.shape == (len(ventana),)


# ---------------------------------------------------------------------------
# Valores conocidos
# ---------------------------------------------------------------------------


def _plana(valores: list[float], referencia: list[float] | None = None) -> Ventana:
    a = np.array(valores, dtype=float)
    return Ventana(
        fechas=np.arange(len(a)),
        apertura=a,
        maximo=a,
        minimo=a,
        cierre=a,
        cierre_bruto=a,
        volumen=np.full(len(a), 1000.0),
        referencia=None if referencia is None else np.array(referencia, dtype=float),
    )


def test_la_media_simple_de_una_rampa():
    v = _plana(list(range(1, 25)))  # 1..24
    sma = REGISTRO["sma_20"].calcular(v)
    assert np.isnan(sma[18])
    assert sma[19] == pytest.approx(10.5), "media de 1..20"
    assert sma[23] == pytest.approx(14.5), "media de 5..24"


def test_la_exponencial_se_siembra_con_la_media_simple():
    """Sembrarla con el primer valor da numeros distintos durante decenas de
    sesiones, y de esta convencion depende el MACD."""
    valores = np.array([10.0, 11.0, 12.0, 13.0, 20.0])
    ema = ema_vector(valores, 4)
    assert np.isnan(ema[2])
    assert ema[3] == pytest.approx(11.5), "media simple de las cuatro primeras"
    # alfa = 2/(4+1) = 0,4
    assert ema[4] == pytest.approx(0.4 * 20.0 + 0.6 * 11.5)


def test_el_rsi_de_una_subida_continua_es_100():
    """Sin ninguna bajada en la ventana, el RSI es 100 por definicion, no NaN."""
    v = _plana([float(x) for x in range(1, 40)])
    rsi = REGISTRO["rsi_14"].calcular(v)
    assert rsi[-1] == pytest.approx(100.0)


def test_el_rsi_de_una_bajada_continua_es_0():
    v = _plana([float(x) for x in range(40, 1, -1)])
    rsi = REGISTRO["rsi_14"].calcular(v)
    assert rsi[-1] == pytest.approx(0.0)


def test_el_rsi_de_un_precio_quieto_no_es_un_numero():
    """Sin movimiento no hay fuerza relativa que medir: es 0/0, no 100.

    La formula de Wilder trata la ausencia de bajadas como fuerza infinita, asi
    que un precio congelado sale con RSI 100 si no se distingue el caso. Y un
    valor cuya cotizacion se ha parado —deslistado, suspendido, o al que el
    proveedor ha dejado de dar datos— apareceria entonces como el de momento mas
    fuerte de todo el mercado, que es justo el ranking que no se quiere.
    """
    v = _plana([10.0] * 40)
    assert np.isnan(REGISTRO["rsi_14"].calcular(v)[-1])


def test_el_estocastico_marca_los_extremos_del_rango():
    v = _plana([float(x) for x in range(1, 20)])
    assert REGISTRO["estocastico_k"].calcular(v)[-1] == pytest.approx(100.0)
    v = _plana([float(x) for x in range(20, 1, -1)])
    assert REGISTRO["estocastico_k"].calcular(v)[-1] == pytest.approx(0.0)


def test_bollinger_marca_medio_en_la_media():
    """Cierre justo en la media de su ventana: la posicion es 0,5.

    Las veinte sesiones suman 220, asi que su media es 11, y el ultimo cierre
    tambien es 11: el precio esta exactamente en el centro de la banda.
    """
    v = _plana([9.0, 13.0] + [11.0] * 18)
    assert REGISTRO["bollinger_posicion"].calcular(v)[-1] == pytest.approx(0.5)


def test_bollinger_pasa_de_uno_al_romper_la_banda_superior():
    v = _plana([9.0, 13.0] + [11.0] * 17 + [40.0])
    assert REGISTRO["bollinger_posicion"].calcular(v)[-1] > 1.0


def test_la_distancia_al_maximo_anual_es_cero_en_un_maximo_nuevo():
    v = _plana([float(x) for x in range(1, SESIONES_ANO + 10)])
    distancia = REGISTRO["distancia_maximo_52s"].calcular(v)
    assert distancia[-1] == pytest.approx(0.0)
    assert (distancia[~np.isnan(distancia)] <= 1e-12).all(), "nunca positiva"


def test_el_drawdown_mide_la_peor_caida_de_la_ventana():
    subida = list(np.linspace(100.0, 200.0, 200))
    caida = list(np.linspace(200.0, 150.0, 60))
    v = _plana(subida + caida)
    dd = REGISTRO["drawdown_maximo_1a"].calcular(v)
    assert dd[-1] == pytest.approx(-0.25, abs=1e-6), "de 200 a 150 es un -25 %"


def test_el_roc_mide_la_variacion_de_veinte_sesiones():
    v = _plana([100.0] * 20 + [110.0])
    assert REGISTRO["roc_20"].calcular(v)[-1] == pytest.approx(0.10)


def test_la_beta_contra_uno_mismo_es_uno():
    """Invariante fuerte: si el valor ES el indice, su beta vale exactamente 1."""
    rng = np.random.default_rng(11)
    serie = list(100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 300)))
    v = _plana(serie, referencia=serie)
    assert REGISTRO["beta_252"].calcular(v)[-1] == pytest.approx(1.0)


def test_la_fuerza_relativa_contra_uno_mismo_es_cero():
    rng = np.random.default_rng(12)
    serie = list(100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 200)))
    v = _plana(serie, referencia=serie)
    assert REGISTRO["fuerza_relativa_126"].calcular(v)[-1] == pytest.approx(0.0, abs=1e-12)


def test_el_ratio_de_volumen_compara_con_su_propia_media():
    v = _plana([10.0] * 21)
    volumen = np.full(21, 1000.0)
    volumen[-1] = 3000.0
    v = Ventana(
        fechas=v.fechas,
        apertura=v.apertura,
        maximo=v.maximo,
        minimo=v.minimo,
        cierre=v.cierre,
        cierre_bruto=v.cierre_bruto,
        volumen=volumen,
    )
    # Media de las ultimas 20 sesiones: diecinueve a 1000 y una a 3000.
    esperado = 3000.0 / ((19 * 1000.0 + 3000.0) / 20)
    assert REGISTRO["ratio_volumen_20"].calcular(v)[-1] == pytest.approx(esperado)


def test_la_aceleracion_distingue_subir_de_subir_cada_vez_mas():
    """Dos valores con el mismo momentum no son la misma oportunidad."""
    constante = _plana(list(np.linspace(100.0, 200.0, 60)))
    acelerada = _plana(list(100.0 * np.cumprod(np.linspace(1.001, 1.02, 60))))
    a_constante = REGISTRO["aceleracion_precio"].calcular(constante)[-1]
    a_acelerada = REGISTRO["aceleracion_precio"].calcular(acelerada)[-1]
    assert a_acelerada > a_constante


# ---------------------------------------------------------------------------
# El registro
# ---------------------------------------------------------------------------


def test_un_indicador_que_necesita_indice_se_omite_con_su_motivo():
    """Omitirlo con motivo, no devolver NaN indistinguible de un fallo."""
    resultado = calcular(_ventana(300, referencia=False))
    assert "beta_252" in resultado.omitidos
    assert "indice" in resultado.omitidos["beta_252"]
    assert "beta_252" not in resultado.valores


def test_un_historico_corto_se_omite_con_su_motivo():
    resultado = calcular(_ventana(30))
    assert "sma_200" in resultado.omitidos
    assert "historico insuficiente" in resultado.omitidos["sma_200"]
    assert "sma_20" in resultado.valores, "los que si caben se calculan igual"


def test_el_registro_rechaza_un_nombre_duplicado():
    """Dos indicadores con el mismo nombre: uno pisa al otro en silencio."""
    with pytest.raises(ValueError, match="duplicado"):
        registrar("sma_20", 20, "otro")(lambda v: v.cierre)


def test_el_catalogo_cubre_lo_que_pide_el_encargo():
    """§13 enumera un minimo; el registro tiene que cubrirlo entero."""
    exigidos = {
        "sma_20",
        "sma_50",
        "sma_100",
        "sma_200",
        "ema_20",
        "rsi_14",
        "macd",
        "macd_signal",
        "atr_14",
        "adx_14",
        "estocastico_k",
        "bollinger_posicion",
        "roc_20",
        "momentum_12_1",
        "volatilidad_60",
        "beta_252",
        "drawdown_maximo_1a",
        "distancia_maximo_52s",
        "distancia_minimo_52s",
        "ratio_volumen_20",
        "aceleracion_precio",
        "fuerza_relativa_126",
    }
    assert exigidos <= set(REGISTRO), f"faltan: {sorted(exigidos - set(REGISTRO))}"
