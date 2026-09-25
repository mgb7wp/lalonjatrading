"""Comisiones, deslizamiento e impuestos de transaccion.

El deslizamiento no es un porcentaje global: se toma el del mercado si existe y
si no el del bloque desarrollado/emergente, como pide el documento.

El impuesto de transaccion necesita mas estructura que un porcentaje por pais,
porque los casos reales no se parecen entre si: el espanol grava solo las
compras y solo a las empresas de una lista que la Agencia Tributaria publica
cada ano, y ademas no existe antes de 2021; la tasa de la SEC estadounidense
grava solo las ventas; la STT india grava los dos lados. Todo eso vive en
`config/impuestos_transaccion.yaml` y se resuelve en `config.py`.

Aviso que el informe repite: con 10.000 EUR de capital y 3 EUR fijos por
operacion, una posicion pequena paga en comisiones una fraccion que no se ve en
la curva agregada. Por eso cada operacion guarda sus costes de ida y vuelta como
porcentaje del nominal, y el informe saca los peores. No se filtra por coste:
eso cambiaria la estrategia, y el documento pide medir antes de tocar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .config import Config, Lado


@dataclass(frozen=True, slots=True)
class Costes:
    """Desglose de los costes de una operacion, en divisa base."""

    comision: float
    deslizamiento: float
    impuesto: float
    impuesto_extrapolado: bool = False

    @property
    def total(self) -> float:
        return self.comision + self.deslizamiento + self.impuesto


def precio_con_deslizamiento(
    precio: float, lado: Lado, mercado_id: str, cfg: Config
) -> float:
    """Precio realmente pagado o cobrado.

    Se compra algo peor que el precio de referencia y se vende algo peor
    tambien; el deslizamiento siempre juega en contra.
    """
    pct = cfg.reglas.costes.deslizamiento(
        mercado_id, cfg.reglas.mercado(mercado_id).clasificacion
    )
    return precio * (1.0 + pct) if lado == "compra" else precio * (1.0 - pct)


def calcular(
    ticker: str,
    mercado_id: str,
    lado: Lado,
    nominal_base: float,
    fecha: date,
    cfg: Config,
) -> Costes:
    """Costes de una operacion, en divisa base.

    `nominal_base` es el importe de la operacion al precio de referencia, sin
    deslizamiento: el deslizamiento se devuelve aparte para poder informarlo.
    """
    reglas = cfg.reglas.costes

    comision = reglas.comision_fija_eur + reglas.comision_pct * nominal_base

    pct_desliz = reglas.deslizamiento(
        mercado_id, cfg.reglas.mercado(mercado_id).clasificacion
    )
    deslizamiento = nominal_base * pct_desliz

    impuesto = 0.0
    extrapolado = False
    pais = cfg.impuestos.paises.get(mercado_id)
    if pais is not None and pais.grava(ticker, lado, fecha):
        impuesto = nominal_base * pais.pct
        if pais.solo_lista_anual and fecha.year not in pais.lista_anual:
            # Se ha usado la lista de otro ano; el informe lo advierte en lugar
            # de presentarlo como si fuera el dato de ese ejercicio.
            extrapolado = True

    return Costes(comision, deslizamiento, impuesto, extrapolado)
