"""Reglas de salida: stops y cierres de la revision semanal.

Funciones puras sobre una posicion y los datos de una sesion. El motor es el
unico que guarda estado entre dias.

La regla mas importante de este modulo no esta escrita en el documento pero se
deduce de el: **el stop con el que se juzga la sesion D se calcula con datos
hasta D-1, nunca con el cierre ni el ATR del propio dia D**. El stop dinamico es
"el cierre mas alto desde la entrada menos 3 ATR, recalculado a diario"; si se
recalculase antes de mirar el minimo de hoy, se estaria usando el cierre de hoy
para decidir si hoy se toco el stop. Es un fallo de una sola linea, invisible en
los resultados y que mejora todos los backtests. Por eso el orden del motor es:
juzgar la sesion con el stop de ayer, y solo despues actualizar el trinquete con
el cierre de hoy.

Dos decisiones mas que el documento deja abiertas y que aqui se fijan:

- El stop inicial usa el ATR del dia de entrada, congelado. El dinamico usa el
  ATR corriente, porque el documento dice que se recalcula a diario.
- El maximo del trinquete son CIERRES, nunca maximos intradia. Usar maximos
  apretaria los stops y mejoraria el resultado sin que la estrategia lo diga.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import Config
from .tipos import MotivoSalida, Posicion


@dataclass(frozen=True, slots=True)
class Salida:
    """Una salida decidida, con su precio y su motivo."""

    motivo: MotivoSalida
    precio_local: float


def stop_inicial(precio_entrada: float, atr_entrada: float, cfg: Config) -> float:
    """Stop de partida: `stop_inicial_atr` ATR por debajo de la entrada."""
    return precio_entrada - cfg.reglas.salidas.stop_inicial_atr * atr_entrada


def stop_dinamico_bruto(maximo_cierre: float, atr_actual: float, cfg: Config) -> float:
    """Stop dinamico antes de aplicar el trinquete."""
    return maximo_cierre - cfg.reglas.salidas.stop_dinamico_atr * atr_actual


def evaluar_stop(posicion: Posicion, sesion: pd.Series) -> Salida | None:
    """Comprueba el stop contra una sesion, con el nivel vigente de ayer.

    Si el valor abre ya por debajo del stop se sale a la apertura, porque a ese
    precio no habia forma de vender mas caro. Si no, y el minimo lo toca, se
    sale al precio del stop.
    """
    nivel = posicion.stop_efectivo_local
    apertura = float(sesion["apertura"])
    minimo = float(sesion["minimo"])

    if apertura <= nivel:
        return Salida(MotivoSalida.STOP_HUECO, apertura)
    if minimo <= nivel:
        return Salida(MotivoSalida.STOP_INTRADIA, nivel)
    return None


def evaluar_salida_semanal(
    posicion: Posicion,
    cierre: float,
    media_larga: float | None,
    sigue_aprobando_fundamental: bool,
    cfg: Config,
) -> Salida | None:
    """Salidas de la revision semanal: bajo la media larga o fundamental roto."""
    salidas = cfg.reglas.salidas

    if salidas.salir_bajo_media_larga and media_larga is not None and cierre < media_larga:
        return Salida(MotivoSalida.BAJO_MEDIA_LARGA, cierre)

    if salidas.salir_si_falla_fundamental and not sigue_aprobando_fundamental:
        return Salida(MotivoSalida.FALLA_FUNDAMENTAL, cierre)

    return None


def actualizar_trinquete(
    posicion: Posicion, cierre: float, atr_actual: float, cfg: Config
) -> Posicion:
    """Mueve el maximo y el stop dinamico con el cierre de la sesion.

    El trinquete impide que el stop baje aunque el ATR se dispare y el calculo
    en bruto de hoy salga por debajo del de ayer.
    """
    bruto = stop_dinamico_bruto(
        max(posicion.maximo_cierre_local, cierre), atr_actual, cfg
    )
    return posicion.con_cierre(cierre, bruto)
