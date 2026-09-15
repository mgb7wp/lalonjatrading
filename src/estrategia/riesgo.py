"""Tamano de posicion.

Funciones puras: entran numeros, salen numeros. Toda la decision de que comprar
vive en `ordenes.py`; aqui solo se responde a cuanto.

Un detalle aritmetico que conviene conocer antes de leer un informe de
sensibilidad. La formula del documento es

    acciones = (capital x riesgo_por_operacion) / (entrada - stop_inicial)

y como el stop inicial es `entrada - stop_inicial_atr x ATR`, el denominador es
`stop_inicial_atr x ATR` y **el precio de entrada se cancela**: el tamano depende
solo del ATR. El peso que eso implica es

    peso = riesgo_por_operacion x precio / (stop_inicial_atr x ATR)

que con los valores de partida (1% y 2 ATR) supera el tope del 15% siempre que
el ATR sea menor que un 3,3% del precio, es decir, en la mayoria de las grandes
companias. Traducido: en el grueso de las operaciones manda `peso_maximo` y no
`riesgo.por_operacion`, y el riesgo real por operacion queda en un 0,4-0,6% en
vez del 1% nominal.

Esto importa para el informe: mover `riesgo.por_operacion` un 25% arriba y abajo
apenas cambiara nada, y seria facil leerlo como "la estrategia es robusta a ese
parametro" cuando lo cierto es que ese parametro estaba inactivo. Por eso cada
operacion guarda su riesgo teorico y su riesgo efectivo, y el informe cuenta con
que frecuencia se topo con el limite.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config


@dataclass(frozen=True, slots=True)
class Tamano:
    """Cuantas acciones comprar y por que salio ese numero."""

    acciones: int
    riesgo_teorico_pct: float
    riesgo_efectivo_pct: float
    limitada_por_peso_maximo: bool
    nominal_base: float


def calcular(
    capital_base: float,
    precio_entrada_base: float,
    stop_inicial_base: float,
    lote: int,
    cfg: Config,
) -> Tamano:
    """Numero de acciones a comprar, redondeado a la baja y al lote del mercado.

    Todo llega ya convertido a divisa base: el documento pide que el precio, el
    stop y el capital se conviertan antes de calcular nada.
    """
    riesgo = cfg.reglas.riesgo.por_operacion
    peso_maximo = cfg.reglas.cartera.peso_maximo

    distancia = precio_entrada_base - stop_inicial_base
    if distancia <= 0 or precio_entrada_base <= 0 or capital_base <= 0:
        return Tamano(0, riesgo, 0.0, False, 0.0)

    por_riesgo = (capital_base * riesgo) / distancia
    por_peso = (capital_base * peso_maximo) / precio_entrada_base

    limitada = por_peso < por_riesgo
    acciones_brutas = min(por_riesgo, por_peso)

    lote = max(int(lote), 1)
    acciones = int(acciones_brutas // lote) * lote

    if acciones <= 0:
        return Tamano(0, riesgo, 0.0, limitada, 0.0)

    nominal = acciones * precio_entrada_base
    riesgo_efectivo = (acciones * distancia) / capital_base
    return Tamano(acciones, riesgo, riesgo_efectivo, limitada, nominal)
