"""El deslizamiento se cuenta una sola vez por operacion (tarea B3).

El fallo que cubren: los precios de compra y de venta ya llevan el
deslizamiento dentro, y al cerrar la operacion se volvia a restar como coste.
La curva de capital salia bien, porque se mueve con el efectivo real, pero el
resultado de cada operacion salia peor de lo que fue: el % de ganadoras y los
resultados por mercado y por bloque, sobre todo en emergentes, donde el
deslizamiento es mayor.

La comprobacion de fondo es contable: el resultado de una operacion tiene que
ser exactamente lo que entro en caja al vender menos lo que salio al comprar.
"""

from __future__ import annotations

import datetime as dt

import pytest

from estrategia import backtest as backtest_mod
from estrategia import costes as costes_mod
from estrategia.cartera import Cartera
from estrategia.tipos import MotivoSalida, Orden, Posicion


def _posicion(**kwargs):
    base = dict(
        ticker="X", mercado="in", sector="industrial", divisa="EUR", acciones=10,
        fecha_entrada=dt.date(2023, 1, 2), precio_entrada_local=100.0,
        precio_entrada_base=100.0, fx_entrada=1.0, atr_entrada=2.0,
        stop_inicial_local=96.0, maximo_cierre_local=100.0,
        stop_dinamico_local=94.0, coste_entrada_base=0.0,
        riesgo_teorico_pct=0.01, riesgo_efectivo_pct=0.008,
        ultimo_cierre_local=100.0,
    )
    base.update(kwargs)
    return Posicion(**base)


def test_el_resultado_no_resta_otra_vez_el_deslizamiento():
    """Referencia 100 -> 110, con un 1 % de deslizamiento a cada lado y 3 EUR
    de comision por operacion. Se paga 101 y se cobra 108,9."""
    cartera = Cartera(efectivo=10_000.0)
    acciones = 10
    desliz_entrada = acciones * 100.0 * 0.01
    desliz_salida = acciones * 110.0 * 0.01
    pos = _posicion(
        acciones=acciones, precio_entrada_local=101.0, precio_entrada_base=101.0,
        coste_entrada_base=3.0 + desliz_entrada,
        deslizamiento_entrada_base=desliz_entrada,
    )
    cartera.abrir(pos, acciones * 101.0 + 3.0)
    ingreso = acciones * 108.9 - 3.0
    op = cartera.cerrar(
        "X", dt.date(2023, 2, 1), 108.9, 1.0, ingreso, 3.0 + desliz_salida,
        MotivoSalida.STOP_INTRADIA, deslizamiento_salida_base=desliz_salida,
    )

    # 10 x (108,9 - 101) - 6 de comisiones = 73. Con el fallo salian 52.
    assert op.resultado_base == pytest.approx(73.0)
    assert op.resultado_base == pytest.approx(cartera.efectivo - 10_000.0)
    # El coste total sigue incluyendo el deslizamiento: es lo que cuesta operar.
    assert op.costes_base == pytest.approx(6.0 + desliz_entrada + desliz_salida)
    assert op.deslizamiento_base == pytest.approx(desliz_entrada + desliz_salida)


def test_una_operacion_casi_plana_no_se_vuelve_perdedora():
    """El caso que distorsiona el % de ganadoras: sin comision y con un 0,3 %
    de deslizamiento, referencia 100 -> 100,8. Se paga 100,30 y se cobran
    100,50: se gano dinero y debe contar como ganadora. Restando otra vez el
    deslizamiento salia una perdida de unos 0,40."""
    cartera = Cartera(efectivo=1_000.0)
    d_in, d_out = 0.3, 0.3015
    pos = _posicion(
        acciones=1, precio_entrada_local=100.3, precio_entrada_base=100.3,
        coste_entrada_base=d_in, deslizamiento_entrada_base=d_in,
    )
    cartera.abrir(pos, 100.3)
    op = cartera.cerrar(
        "X", dt.date(2023, 2, 1), 100.8 * (1 - 0.003), 1.0, 100.8 * (1 - 0.003),
        d_out, MotivoSalida.STOP_INTRADIA, deslizamiento_salida_base=d_out,
    )
    assert op.resultado_base == pytest.approx(cartera.efectivo - 1_000.0)
    assert op.ganadora


def _primer_ticker(cfg, mercado):
    return next(
        t for t in cfg.universo.tickers() if cfg.universo.mercado_de_ticker[t] == mercado
    )


def _dos_sesiones(vista_de, ticker, desde):
    """Dos sesiones con precio del valor, separadas unas semanas."""
    dia = desde
    encontradas = []
    while len(encontradas) < 2:
        if vista_de(dia).precio_en(ticker, dia) is not None:
            encontradas.append(dia)
            dia += dt.timedelta(days=30)
        else:
            dia += dt.timedelta(days=1)
    return encontradas


@pytest.mark.parametrize("mercado", ["es", "us", "de", "in", "br"])
def test_el_resultado_cuadra_con_la_caja_en_cada_mercado(cfg, instantanea, mercado):
    """Con los precios, cambios, comisiones, impuestos y deslizamientos reales
    del motor: lo que se anota como resultado es lo que se movio en caja."""
    ticker = _primer_ticker(cfg, mercado)
    divisa = cfg.reglas.mercado(mercado).divisa
    entrada, salida = _dos_sesiones(instantanea.vista, ticker, dt.date(2023, 3, 1))

    capital = 100_000.0
    cartera = Cartera(efectivo=capital)
    orden = Orden(
        ticker=ticker, mercado=mercado, sector="industrial",
        fecha_decision=entrada - dt.timedelta(days=3), acciones=100,
        stop_inicial_local=0.01, atr_entrada=1.0, rango_asignacion=1,
        puntuacion_final=50.0, riesgo_teorico_pct=0.01, riesgo_efectivo_pct=0.01,
        limitada_por_peso_maximo=False,
    )
    eventos: list = []
    backtest_mod._abrir(
        cartera, orden, entrada, instantanea.vista(entrada), cfg, eventos, divisa
    )
    assert cartera.tiene(ticker), eventos

    vista = instantanea.vista(salida)
    precio = float(vista.precio_en(ticker, salida)["apertura"])
    backtest_mod._cerrar(
        cartera, ticker, salida, precio, vista, cfg,
        MotivoSalida.STOP_INTRADIA, eventos, divisa,
    )
    op = cartera.operaciones[-1]

    assert op.resultado_base == pytest.approx(cartera.efectivo - capital, abs=1e-6)
    assert op.deslizamiento_base > 0
    assert op.costes_base > op.deslizamiento_base

    # Y el deslizamiento anotado es exactamente el que va en los precios.
    pct = cfg.reglas.costes.deslizamiento(mercado, cfg.reglas.mercado(mercado).clasificacion)
    pagado = costes_mod.precio_con_deslizamiento(1.0, "compra", mercado, cfg)
    assert pagado == pytest.approx(1.0 + pct)


def test_en_todo_el_backtest_los_resultados_suman_lo_que_gano_la_caja(
    cfg, instantanea, monkeypatch
):
    """Al final todo se liquida: la suma de los resultados de las operaciones
    tiene que ser el efectivo final menos el capital inicial."""
    carteras: list[Cartera] = []

    class CarteraVigilada(Cartera):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            carteras.append(self)

    monkeypatch.setattr(backtest_mod, "Cartera", CarteraVigilada)
    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2020, 1, 1), dt.date(2024, 12, 31))

    assert len(r.operaciones) > 10
    cartera = carteras[-1]
    assert cartera.n_posiciones == 0
    suma = sum(o.resultado_base for o in r.operaciones)
    assert suma == pytest.approx(cartera.efectivo - r.capital_inicial, abs=1e-6)
