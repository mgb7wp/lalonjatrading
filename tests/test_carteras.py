"""Derivacion de carteras (FASE 13).

El criterio de aceptacion tiene dos partes y las dos estan aqui:

1. **El P&L cuadra con un caso calculado a mano**, comisiones y divisa incluidas.
   Los numeros de ese test estan calculados aparte, a mano, y escritos como
   constantes: si se calcularan con el mismo codigo que se prueba, el test
   pasaria aunque la formula fuera otra.
2. **Corregir una transaccion antigua corrige todo lo que cuelga de ella.** Es
   lo que se pierde en cuanto el saldo vive en una columna.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from backend.carteras import Transaccion, derivar, exposicion

D = Decimal


def _compra(ticker, cantidad, precio, comisiones="0", fx="1", fecha=None, impuestos="0"):
    return Transaccion(
        ticker=ticker,
        tipo="buy",
        cantidad=D(str(cantidad)),
        precio=D(str(precio)),
        comisiones=D(comisiones),
        impuestos=D(impuestos),
        fx=D(fx),
        fecha=fecha,
    )


def _venta(ticker, cantidad, precio, comisiones="0", fx="1", fecha=None, impuestos="0"):
    return Transaccion(
        ticker=ticker,
        tipo="sell",
        cantidad=D(str(cantidad)),
        precio=D(str(precio)),
        comisiones=D(comisiones),
        impuestos=D(impuestos),
        fx=D(fx),
        fecha=fecha,
    )


# --- El caso calculado a mano ---------------------------------------------


def test_el_pnl_cuadra_con_el_caso_calculado_a_mano():
    """Criterio de aceptacion, con los numeros hechos aparte.

    Enunciado:

      1) Compra 100 AAPL a 150 USD, comision 10 USD, con el dolar a 0,90 EUR.
      2) Compra  50 AAPL a 170 USD, comision 10 USD, con el dolar a 0,92 EUR.
      3) Vende   120 AAPL a 200 USD, comision 12 USD, con el dolar a 0,95 EUR.
      Quedan 30 acciones y el precio de hoy es 210 USD con el dolar a 0,93.

    A mano:

      Compra 1: (100*150 + 10) * 0,90 = 15.010 * 0,90 = 13.509,00 EUR
                coste unitario = 135,09
      Compra 2: ( 50*170 + 10) * 0,92 =  8.510 * 0,92 =  7.829,20 EUR
                coste unitario = 156,584
      Venta:    (120*200 - 12) * 0,95 = 23.988 * 0,95 = 22.788,60 EUR
                FIFO: 100 del lote 1 + 20 del lote 2
                coste vendido = 100*135,09 + 20*156,584 = 13.509 + 3.131,68
                              = 16.640,68 EUR
                realizado = 22.788,60 - 16.640,68 = 6.147,92 EUR

      Quedan 30 del lote 2: coste = 30 * 156,584 = 4.697,52 EUR
      Valor hoy = 30 * 210 * 0,93 = 5.859,00 EUR
      No realizado = 5.859,00 - 4.697,52 = 1.161,48 EUR
      Total = 6.147,92 + 1.161,48 = 7.309,40 EUR
    """
    transacciones = [
        _compra("AAPL", 100, "150", comisiones="10", fx="0.90", fecha=dt.date(2024, 1, 10)),
        _compra("AAPL", 50, "170", comisiones="10", fx="0.92", fecha=dt.date(2024, 3, 5)),
        _venta("AAPL", 120, "200", comisiones="12", fx="0.95", fecha=dt.date(2024, 9, 20)),
    ]
    c = derivar(transacciones, precios={"AAPL": D("210")}, fx_actual={"AAPL": D("0.93")})
    p = c.posiciones["AAPL"]

    assert p.cantidad == D("30")
    assert p.realizado == D("6147.92")
    assert p.coste == D("4697.52")
    assert p.valor == D("5859.00")
    assert p.no_realizado == D("1161.48")
    assert c.total == D("7309.40")


def test_con_coste_medio_en_vez_de_fifo_el_resultado_seria_otro():
    """Por que elegir convencion importa, y no es un matiz.

    Sobre el mismo caso, el coste medio da:
      coste total = 13.509 + 7.829,20 = 21.338,20 por 150 acciones
      unitario medio = 142,254666...
      coste de 120 vendidas = 17.070,56
      realizado = 22.788,60 - 17.070,56 = 5.718,04

    Frente a 6.147,92 con FIFO: 429,88 EUR de diferencia en lo que hay que
    declarar. Este test fija que usamos FIFO comprobando que NO sale el otro.
    """
    transacciones = [
        _compra("AAPL", 100, "150", comisiones="10", fx="0.90", fecha=dt.date(2024, 1, 10)),
        _compra("AAPL", 50, "170", comisiones="10", fx="0.92", fecha=dt.date(2024, 3, 5)),
        _venta("AAPL", 120, "200", comisiones="12", fx="0.95", fecha=dt.date(2024, 9, 20)),
    ]
    realizado = derivar(transacciones).posiciones["AAPL"].realizado

    assert realizado == D("6147.92"), "FIFO"
    assert realizado != D("5718.04"), "no es coste medio"


# --- Corregir el pasado ----------------------------------------------------


def test_corregir_una_transaccion_antigua_corrige_todo_lo_que_cuelga():
    """La otra mitad del criterio.

    Se cambia la comision de la PRIMERA compra y tiene que moverse el coste, el
    P&L realizado de una venta posterior y el total. Con un saldo guardado en
    una columna, la correccion no llegaria a la venta de hace ocho meses.
    """
    base = [
        _compra("MSFT", 10, "100", comisiones="5", fecha=dt.date(2024, 1, 1)),
        _venta("MSFT", 5, "120", comisiones="5", fecha=dt.date(2024, 6, 1)),
    ]
    antes = derivar(base, precios={"MSFT": D("130")})

    corregido = [
        _compra("MSFT", 10, "100", comisiones="55", fecha=dt.date(2024, 1, 1)),
        base[1],
    ]
    despues = derivar(corregido, precios={"MSFT": D("130")})

    # La comision sube 50: 25 van al coste de lo vendido y 25 al de lo que queda.
    assert despues.posiciones["MSFT"].realizado == antes.posiciones["MSFT"].realizado - D("25")
    assert despues.posiciones["MSFT"].coste == antes.posiciones["MSFT"].coste + D("25")
    assert despues.total == antes.total - D("50"), "los 50 enteros, ni mas ni menos"


def test_el_orden_lo_da_la_fecha_y_no_el_orden_de_llegada():
    """FIFO sobre una lista desordenada no es FIFO.

    Las transacciones llegan de la base de datos en cualquier orden; si el motor
    no las ordenase, el lote que se consume al vender seria el que se insertara
    primero, no el que se compro antes.
    """
    desordenadas = [
        _compra("X", 10, "200", fecha=dt.date(2024, 6, 1)),
        _compra("X", 10, "100", fecha=dt.date(2024, 1, 1)),
        _venta("X", 10, "300", fecha=dt.date(2024, 9, 1)),
    ]
    # FIFO de verdad consume el lote de 100 (enero), no el de 200 (junio).
    assert derivar(desordenadas).posiciones["X"].realizado == D("2000")


# --- Comisiones, impuestos y dividendos ------------------------------------


def test_la_comision_de_compra_encarece_el_coste_y_la_de_venta_reduce_lo_cobrado():
    """Si las de compra fueran gasto aparte, el coste medio saldria mas bajo de
    lo que costo de verdad y el P&L, mas alto."""
    c = derivar([_compra("A", 10, "100", comisiones="50")])
    assert c.posiciones["A"].coste == D("1050")
    assert c.posiciones["A"].coste_medio == D("105")

    v = derivar([_compra("B", 10, "100"), _venta("B", 10, "100", comisiones="50")])
    assert v.posiciones["B"].realizado == D("-50"), (
        "comprar y vender al mismo precio pierde la comision"
    )


def test_un_dividendo_no_reduce_el_coste(caplog):
    """Restarlo del coste bajaria la base y falsearia el P&L realizado del dia
    que se venda. Es renta, no devolucion de capital."""
    c = derivar(
        [
            _compra("D", 100, "10"),
            Transaccion("D", "dividend", D("100"), D("0.5"), impuestos=D("10")),
        ],
        precios={"D": D("10")},
    )
    assert c.posiciones["D"].coste == D("1000"), "el coste no se toca"
    assert c.posiciones["D"].dividendos == D("40"), "50 brutos menos 10 de retencion"
    assert c.total == D("40")


def test_una_comision_de_custodia_no_encarece_ninguna_accion():
    """Repartirla entre las posiciones falsearia el coste medio de todas."""
    c = derivar(
        [
            _compra("A", 10, "100"),
            Transaccion("", "fee", D("0"), D("0"), comisiones=D("25")),
        ],
        precios={"A": D("100")},
    )
    assert c.posiciones["A"].coste == D("1000")
    assert c.gastos == D("25")
    assert c.total == D("-25")


# --- Divisa ----------------------------------------------------------------


def test_el_coste_se_fija_al_cambio_del_dia_y_la_valoracion_al_de_hoy():
    """Mezclarlos inventa una ganancia por divisa que no existe, o esconde una
    que si. Aqui el precio no se mueve y el euro si: todo el resultado es
    diferencia de cambio, y tiene que aparecer."""
    c = derivar(
        [_compra("EUR_TEST", 100, "10", fx="1.00")],
        precios={"EUR_TEST": D("10")},
        fx_actual={"EUR_TEST": D("1.20")},
    )
    p = c.posiciones["EUR_TEST"]

    assert p.coste == D("1000"), "lo que se pago, al cambio de aquel dia"
    assert p.valor == D("1200"), "lo que vale hoy, al cambio de hoy"
    assert p.no_realizado == D("200")


# --- Lo que no se sabe se declara ------------------------------------------


def test_un_valor_sin_precio_no_se_valora_a_coste():
    """Valorar a coste finge que no se ha movido, que es una afirmacion sobre
    datos que no se tienen."""
    c = derivar([_compra("SINPRECIO", 10, "100")], precios={})

    assert "SINPRECIO" in c.sin_valorar
    assert c.posiciones["SINPRECIO"].valor is None
    assert c.valor == D("0"), "no entra en el valor de la cartera"


def test_los_pesos_se_calculan_sobre_el_valor_y_no_sobre_el_coste():
    """La pregunta que responde un peso es 'cuanto de mi dinero esta hoy aqui'."""
    c = derivar(
        [_compra("A", 10, "100"), _compra("B", 10, "100")],
        precios={"A": D("300"), "B": D("100")},
    )
    pesos = c.pesos()

    assert pesos["A"] == D("0.75"), "por coste seria 0,5"
    assert pesos["B"] == D("0.25")


def test_lo_que_no_esta_clasificado_no_se_reparte():
    """Repartirlo inventaria una diversificacion que no se ha comprobado."""
    c = derivar(
        [_compra("A", 10, "100"), _compra("B", 10, "100")],
        precios={"A": D("100"), "B": D("100")},
    )
    exp = exposicion(c, {"A": "banca", "B": None})

    assert exp["banca"] == D("0.5")
    assert exp["sin clasificar"] == D("0.5")


def test_una_posicion_cerrada_no_cuenta_como_abierta_pero_su_realizado_si():
    c = derivar(
        [_compra("C", 10, "100"), _venta("C", 10, "150")],
        precios={"C": D("200")},
    )
    assert c.posiciones["C"].cantidad == D("0")
    assert c.abiertas == []
    assert c.realizado == D("500")
    assert c.valor == D("0")
    assert c.total == D("500")
