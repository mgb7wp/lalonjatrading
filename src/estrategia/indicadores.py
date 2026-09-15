"""Indicadores precalculados, una vez por valor.

La primera version calculaba medias, ATR y momentum dentro del bucle diario,
recorriendo el historico entero en cada consulta. Con 140 valores y seis anos de
sesiones eso es inviable, y ademas hace inutilizables el panel y el analisis de
sensibilidad, que corren el backtest decenas de veces.

Aqui cada serie se recorre una sola vez y se deja todo resuelto en vectores
alineados con las sesiones del valor. El bucle diario pasa a ser una lectura por
indice.

Esto no abre la puerta al sesgo de anticipacion: todos los indicadores son
ventanas hacia atras, asi que la posicion `i` de cada vector solo depende de
datos en posiciones `<= i`. El motor lee la posicion correspondiente a la fecha
de decision y nunca una posterior; el almacen sigue vigilando el corte y los
tests de sesgo lo comprueban recortando la serie y verificando que la decision
no cambia.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .config import Config
from .constantes import MESES_POR_ANO


def media_movil_vector(valores: np.ndarray, ventana: int) -> np.ndarray:
    """Media simple movil, con NaN donde aun no hay ventana completa."""
    n = len(valores)
    salida = np.full(n, np.nan)
    if n < ventana or ventana <= 0:
        return salida
    acumulado = np.cumsum(np.insert(valores, 0, 0.0))
    salida[ventana - 1 :] = (acumulado[ventana:] - acumulado[:-ventana]) / ventana
    return salida


def atr_wilder_vector(
    maximos: np.ndarray, minimos: np.ndarray, cierres: np.ndarray, periodo: int
) -> np.ndarray:
    """ATR de Wilder en cada sesion.

    Se siembra con la media simple de los primeros `periodo` rangos verdaderos y
    a partir de ahi se suaviza, que es la definicion original de Wilder. Una
    media movil simple del rango da un numero parecido pero distinto, y como de
    esto dependen los dos stops, la definicion se fija y se comprueba.
    """
    n = len(cierres)
    salida = np.full(n, np.nan)
    if n < periodo + 1:
        return salida

    previo = cierres[:-1]
    rango = np.maximum(
        maximos[1:] - minimos[1:],
        np.maximum(np.abs(maximos[1:] - previo), np.abs(minimos[1:] - previo)),
    )
    atr = float(np.mean(rango[:periodo]))
    salida[periodo] = atr
    for i in range(periodo, len(rango)):
        atr = (atr * (periodo - 1) + float(rango[i])) / periodo
        salida[i + 1] = atr
    return salida


def momentum_vector(
    fechas: np.ndarray, cierres: np.ndarray, meses: int, excluir_meses: int
) -> np.ndarray:
    """Momentum 12-1 en cada sesion.

    Los dos extremos se resuelven "a la fecha": el ultimo cierre disponible en o
    antes del dia objetivo, para que un festivo no invalide el calculo.
    """
    n = len(fechas)
    salida = np.full(n, np.nan)
    if n == 0:
        return salida

    ordinales = np.array([f.toordinal() for f in fechas])
    obj_fin = np.array([_desplazar_meses(f, -excluir_meses).toordinal() for f in fechas])
    obj_ini = np.array([_desplazar_meses(f, -meses).toordinal() for f in fechas])

    # searchsorted 'right' - 1 da el ultimo indice con fecha <= objetivo.
    idx_fin = np.searchsorted(ordinales, obj_fin, side="right") - 1
    idx_ini = np.searchsorted(ordinales, obj_ini, side="right") - 1

    valido = (idx_ini >= 0) & (idx_fin >= 0) & (idx_ini < idx_fin)
    p_ini = np.where(valido, cierres[np.clip(idx_ini, 0, n - 1)], np.nan)
    p_fin = np.where(valido, cierres[np.clip(idx_fin, 0, n - 1)], np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        salida = np.where(valido & (p_ini > 0), p_fin / p_ini - 1.0, np.nan)
    return salida


def _desplazar_meses(f: date, meses: int) -> date:
    import calendar

    total = f.year * MESES_POR_ANO + (f.month - 1) + meses
    ano, mes = divmod(total, MESES_POR_ANO)
    dia = min(f.day, calendar.monthrange(ano, mes + 1)[1])
    return date(ano, mes + 1, dia)


@dataclass(slots=True)
class SerieValor:
    """Serie de un valor con sus indicadores ya resueltos."""

    ticker: str
    fechas: np.ndarray
    ordinales: np.ndarray
    apertura: np.ndarray
    maximo: np.ndarray
    minimo: np.ndarray
    cierre: np.ndarray
    cierre_bruto: np.ndarray
    volumen: np.ndarray
    ma_corta: np.ndarray
    ma_larga: np.ndarray
    ma_regimen: np.ndarray
    atr: np.ndarray
    momentum: np.ndarray

    def posicion(self, fecha: date) -> int:
        """Indice de la ultima sesion en o antes de `fecha`; -1 si no hay."""
        return int(np.searchsorted(self.ordinales, fecha.toordinal(), side="right")) - 1

    def posicion_exacta(self, fecha: date) -> int:
        """Indice de esa sesion concreta, o -1 si el valor no cotizo ese dia."""
        i = self.posicion(fecha)
        if i < 0 or self.fechas[i] != fecha:
            return -1
        return i


def construir_series(precios: pd.DataFrame, cfg: Config) -> dict[str, SerieValor]:
    """Calcula los indicadores de todos los valores de una sola pasada."""
    tec = cfg.reglas.tecnico
    series: dict[str, SerieValor] = {}
    if precios.empty:
        return series

    for ticker, grupo in precios.groupby("ticker", sort=False):
        g = grupo.sort_values("fecha")
        fechas = g["fecha"].to_numpy()
        cierre = g["cierre"].to_numpy(dtype=float)
        maximo = g["maximo"].to_numpy(dtype=float)
        minimo = g["minimo"].to_numpy(dtype=float)

        series[str(ticker)] = SerieValor(
            ticker=str(ticker),
            fechas=fechas,
            ordinales=np.array([f.toordinal() for f in fechas]),
            apertura=g["apertura"].to_numpy(dtype=float),
            maximo=maximo,
            minimo=minimo,
            cierre=cierre,
            cierre_bruto=g["cierre_bruto"].to_numpy(dtype=float),
            volumen=g["volumen"].to_numpy(dtype=float),
            ma_corta=media_movil_vector(cierre, tec.media_corta),
            ma_larga=media_movil_vector(cierre, tec.media_larga),
            ma_regimen=media_movil_vector(cierre, tec.regimen_mercado_media),
            atr=atr_wilder_vector(maximo, minimo, cierre, tec.atr_periodo),
            momentum=momentum_vector(
                fechas, cierre, tec.momentum_meses, tec.momentum_excluir_meses
            ),
        )
    return series


@dataclass(slots=True)
class SerieFX:
    """Tipos de cambio de una divisa, indexados por dia natural."""

    divisa: str
    ordinales: np.ndarray
    tasas: np.ndarray

    def tasa_en(self, fecha: date) -> float | None:
        """Ultima tasa conocida en o antes de esa fecha."""
        i = int(np.searchsorted(self.ordinales, fecha.toordinal(), side="right")) - 1
        return None if i < 0 else float(self.tasas[i])


def construir_fx(fx: pd.DataFrame) -> dict[str, SerieFX]:
    series: dict[str, SerieFX] = {}
    if fx.empty:
        return series
    for divisa, grupo in fx.groupby("divisa", sort=False):
        g = grupo.sort_values("fecha")
        series[str(divisa)] = SerieFX(
            divisa=str(divisa),
            ordinales=np.array([f.toordinal() for f in g["fecha"]]),
            tasas=g["tasa"].to_numpy(dtype=float),
        )
    return series
