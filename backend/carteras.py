"""Derivacion de una cartera a partir de sus transacciones.

**Nada se guarda calculado.** Posiciones, coste, P&L y pesos salen siempre de
recorrer las transacciones. Es la exigencia de la FASE 13 y no es purismo: en
cuanto el saldo vive en una columna, corregir una compra de hace ocho meses deja
esa columna mintiendo, y nadie se entera hasta que el P&L no cuadra con el
extracto del broker. Derivando, corregir la transaccion corrige todo lo que
cuelga de ella por construccion.

El precio es recorrer las transacciones cada vez. Con carteras de decenas o
cientos de operaciones eso son microsegundos; el dia que sean cien mil, se
cachea el resultado con la huella de las transacciones como clave, que sigue
siendo derivar.

## FIFO, y por que importa elegir

El coste de lo vendido se toma de los lotes **mas antiguos primero**. No es la
unica convencion posible —el coste medio da otro P&L realizado— pero es la que
exige la normativa fiscal espaniola para valores homogeneos, y una cartera cuyo
P&L realizado no coincide con el que hay que declarar sirve de poco.

Con coste medio, vender la mitad de una posicion comprada en dos tramos da un
resultado distinto. No es un matiz: es dinero.

## Decimal y no float

Todo el dinero va en `Decimal`. `0.1 + 0.2` en coma flotante no es `0.3`, y un
P&L que arrastra ese error acaba sin cuadrar con el extracto por unos centimos
que nadie sabe de donde salen.

## Divisa

Cada transaccion guarda el tipo de cambio **del dia en que se ejecuto**
(`fx_rate_to_base`), porque eso es lo que se pago de verdad. La valoracion de
hoy usa el tipo de hoy. Mezclarlos —valorar al tipo de compra, o recalcular el
coste al tipo actual— inventa una ganancia por divisa que no existe o esconde
una que si.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal

CERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class Transaccion:
    """Una operacion, tal y como se ejecuto. Es el unico dato de entrada."""

    ticker: str
    tipo: str  # buy | sell | dividend | fee
    cantidad: Decimal
    precio: Decimal
    comisiones: Decimal = CERO
    impuestos: Decimal = CERO
    divisa: str = "EUR"
    #: Tipo de cambio divisa -> base EL DIA de la operacion.
    fx: Decimal = Decimal("1")
    fecha: dt.date | None = None


@dataclass
class Posicion:
    """Lo que se tiene de un valor, todo derivado."""

    ticker: str
    cantidad: Decimal = CERO
    #: Coste de lo que AUN se tiene, en divisa base, comisiones incluidas.
    coste: Decimal = CERO
    realizado: Decimal = CERO
    dividendos: Decimal = CERO
    precio_actual: Decimal | None = None
    fx_actual: Decimal | None = None

    @property
    def coste_medio(self) -> Decimal | None:
        return None if self.cantidad == CERO else self.coste / self.cantidad

    @property
    def valor(self) -> Decimal | None:
        if self.precio_actual is None or self.fx_actual is None:
            return None
        return self.cantidad * self.precio_actual * self.fx_actual

    @property
    def no_realizado(self) -> Decimal | None:
        v = self.valor
        return None if v is None else v - self.coste


@dataclass
class Cartera:
    """La cartera entera, derivada."""

    posiciones: dict[str, Posicion] = field(default_factory=dict)
    #: Comisiones sueltas (`fee`) que no van contra ningun valor.
    gastos: Decimal = CERO
    #: Valores cuyo precio actual no se conoce. Se declaran en lugar de
    #: valorarlos a coste: valorar a coste finge que no se han movido.
    sin_valorar: list[str] = field(default_factory=list)

    @property
    def abiertas(self) -> list[Posicion]:
        return [p for p in self.posiciones.values() if p.cantidad > CERO]

    @property
    def valor(self) -> Decimal:
        return sum((p.valor or CERO) for p in self.abiertas)

    @property
    def coste(self) -> Decimal:
        return sum(p.coste for p in self.abiertas)

    @property
    def no_realizado(self) -> Decimal:
        return sum((p.no_realizado or CERO) for p in self.abiertas)

    @property
    def realizado(self) -> Decimal:
        return sum(p.realizado for p in self.posiciones.values())

    @property
    def dividendos(self) -> Decimal:
        return sum(p.dividendos for p in self.posiciones.values())

    @property
    def total(self) -> Decimal:
        """P&L total: lo realizado, lo no realizado, dividendos y gastos.

        Los gastos sueltos restan aqui y no en ninguna posicion: una comision de
        custodia no encarece el coste de una accion concreta, y repartirla
        falsearia el coste medio de todas.
        """
        return self.realizado + self.no_realizado + self.dividendos - self.gastos

    def pesos(self) -> dict[str, Decimal]:
        """Peso de cada posicion sobre el valor de mercado.

        Sobre el valor y no sobre el coste: la pregunta que responde un peso es
        "cuanto de mi dinero esta hoy aqui", y eso es valor.
        """
        total = self.valor
        if total == CERO:
            return {}
        return {p.ticker: (p.valor or CERO) / total for p in self.abiertas}


@dataclass(frozen=True, slots=True)
class _Lote:
    cantidad: Decimal
    coste_unitario: Decimal  # en divisa base, con la parte de comisiones dentro


def derivar(
    transacciones: list[Transaccion],
    precios: dict[str, Decimal] | None = None,
    fx_actual: dict[str, Decimal] | None = None,
) -> Cartera:
    """Recorre las transacciones en orden y devuelve la cartera resultante.

    `precios` son los cierres actuales EN DIVISA LOCAL y `fx_actual` los tipos de
    cambio de hoy. Lo que no se pueda valorar se declara en `sin_valorar`.
    """
    precios = precios or {}
    fx_actual = fx_actual or {}
    cartera = Cartera()
    lotes: dict[str, deque[_Lote]] = {}

    # Orden estable por fecha: FIFO sobre una lista desordenada no es FIFO. Las
    # que no traen fecha conservan el orden en que llegan.
    ordenadas = sorted(
        enumerate(transacciones),
        key=lambda par: (par[1].fecha or dt.date.min, par[0]),
    )

    for _, t in ordenadas:
        if t.tipo == "fee" and not t.ticker:
            cartera.gastos += t.comisiones * t.fx
            continue

        pos = cartera.posiciones.setdefault(t.ticker, Posicion(ticker=t.ticker))
        cola = lotes.setdefault(t.ticker, deque())

        if t.tipo == "buy":
            # Las comisiones y los impuestos de compra ENCARECEN el coste. Si
            # fueran gasto aparte, el coste medio saldria mas bajo de lo que
            # costo de verdad y el P&L, mas alto.
            bruto = (t.cantidad * t.precio + t.comisiones + t.impuestos) * t.fx
            unitario = bruto / t.cantidad if t.cantidad else CERO
            cola.append(_Lote(cantidad=t.cantidad, coste_unitario=unitario))
            pos.cantidad += t.cantidad
            pos.coste += bruto

        elif t.tipo == "sell":
            # Las comisiones de venta REDUCEN lo cobrado, no aumentan el coste:
            # el coste ya esta fijado por la compra.
            ingreso = (t.cantidad * t.precio - t.comisiones - t.impuestos) * t.fx
            por_vender = t.cantidad
            coste_vendido = CERO
            while por_vender > CERO and cola:
                lote = cola[0]
                usa = min(lote.cantidad, por_vender)
                coste_vendido += usa * lote.coste_unitario
                por_vender -= usa
                if usa == lote.cantidad:
                    cola.popleft()
                else:
                    cola[0] = _Lote(lote.cantidad - usa, lote.coste_unitario)

            # Vender mas de lo que se tiene es un corto o un error de captura.
            # No se inventa coste para lo que falta: se cuenta como ingreso
            # entero y la cantidad queda negativa, que es visible.
            pos.cantidad -= t.cantidad
            pos.coste -= coste_vendido
            pos.realizado += ingreso - coste_vendido

        elif t.tipo == "dividend":
            # Un dividendo NO reduce el coste: es renta. Restarlo del coste
            # bajaria la base y falsearia el P&L realizado del dia que se venda.
            pos.dividendos += (t.cantidad * t.precio - t.impuestos - t.comisiones) * t.fx

        elif t.tipo == "fee":
            pos.realizado -= (t.comisiones + t.impuestos) * t.fx

    for pos in cartera.posiciones.values():
        if pos.cantidad <= CERO:
            continue
        precio = precios.get(pos.ticker)
        if precio is None:
            cartera.sin_valorar.append(pos.ticker)
            continue
        pos.precio_actual = Decimal(str(precio))
        pos.fx_actual = Decimal(str(fx_actual.get(pos.ticker, 1)))

    return cartera


def exposicion(cartera: Cartera, dimension: dict[str, str | None]) -> dict[str, Decimal]:
    """Reparte el peso de la cartera por sector, pais o lo que se pase.

    Lo que no tiene clasificacion va a `sin clasificar` y NO se reparte entre las
    demas: repartirlo inventaria una diversificacion que no se ha comprobado.
    """
    salida: dict[str, Decimal] = {}
    for ticker, peso in cartera.pesos().items():
        clave = dimension.get(ticker) or "sin clasificar"
        salida[clave] = salida.get(clave, CERO) + peso
    return dict(sorted(salida.items(), key=lambda p: -p[1]))
