"""Filtro tecnico: medias, momentum 12-1, ATR y regimen de mercado.

Todo lo que hay aqui se calcula sobre el precio en DIVISA LOCAL. El documento lo
pide explicitamente y la razon es buena: si se convierte antes, la tendencia que
se mide es la del valor mezclada con la de su divisa, y una accion india que
sube un 20% en rupias mientras la rupia cae un 20% dejaria de parecer alcista
aunque su negocio y su mercado digan lo contrario. La conversion a euros llega
mas tarde, solo para valorar la cartera y dimensionar el riesgo.

Hay un test que fija esta separacion: cambia el tipo de cambio y comprueba que
medias, momentum y ATR no se mueven ni un decimal.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import Config
from .constantes import MESES_POR_ANO
from .datos.almacen import VistaPuntual
from .tipos import SenalTecnica


def media_movil(cierres: np.ndarray, ventana: int) -> float | None:
    """Media simple de las ultimas `ventana` sesiones."""
    if len(cierres) < ventana:
        return None
    return float(np.mean(cierres[-ventana:]))


def atr_wilder(
    maximos: np.ndarray, minimos: np.ndarray, cierres: np.ndarray, periodo: int
) -> float | None:
    """ATR con el suavizado de Wilder, que es el ATR de toda la vida.

    Se siembra con la media simple de los primeros `periodo` rangos verdaderos
    y a partir de ahi se suaviza. Una media simple movil del rango verdadero da
    un numero parecido pero no igual, y el stop depende de esto, asi que la
    definicion se fija y se comprueba contra un caso conocido.
    """
    n = len(cierres)
    if n < periodo + 1:
        return None

    cierre_previo = cierres[:-1]
    rango = np.maximum(
        maximos[1:] - minimos[1:],
        np.maximum(
            np.abs(maximos[1:] - cierre_previo), np.abs(minimos[1:] - cierre_previo)
        ),
    )
    if len(rango) < periodo:
        return None

    atr = float(np.mean(rango[:periodo]))
    for tr in rango[periodo:]:
        atr = (atr * (periodo - 1) + float(tr)) / periodo
    return atr


def momentum_12_1(
    precios: pd.DataFrame, fecha: date, meses: int, excluir_meses: int
) -> float | None:
    """Rentabilidad de los ultimos `meses` sin contar los `excluir_meses` mas recientes.

    Se salta el mes mas cercano porque a muy corto plazo el momentum tiende a
    darse la vuelta, y ese efecto ensucia la senal de medio plazo que se busca.

    Los extremos se resuelven "a la fecha": se toma el ultimo cierre disponible
    en o antes del dia objetivo, de modo que un festivo no invalide el calculo.
    """
    if precios.empty:
        return None

    fin = _desplazar_meses(fecha, -excluir_meses)
    inicio = _desplazar_meses(fecha, -meses)

    p_fin = _cierre_a_fecha(precios, fin)
    p_ini = _cierre_a_fecha(precios, inicio)
    if p_fin is None or p_ini is None or p_ini <= 0:
        return None
    return p_fin / p_ini - 1.0


def _desplazar_meses(f: date, meses: int) -> date:
    total = f.year * MESES_POR_ANO + (f.month - 1) + meses
    ano, mes = divmod(total, MESES_POR_ANO)
    dia = min(f.day, _dias_del_mes(ano, mes + 1))
    return date(ano, mes + 1, dia)


def _dias_del_mes(ano: int, mes: int) -> int:
    import calendar

    return calendar.monthrange(ano, mes)[1]


def _cierre_a_fecha(precios: pd.DataFrame, objetivo: date) -> float | None:
    previos = precios[precios["fecha"] <= objetivo]
    if previos.empty:
        return None
    return float(previos.iloc[-1]["cierre"])


def senal(
    ticker: str,
    mercado: str,
    fecha: date,
    vista: VistaPuntual,
    cfg: Config,
) -> SenalTecnica | None:
    """Lectura tecnica completa de un valor a una fecha.

    Lee los indicadores ya calculados en `indicadores.py`, que son ventanas
    hacia atras: la posicion `i` solo depende de datos en posiciones `<= i`, y
    la posicion se obtiene del corte de la vista, nunca de una fecha posterior.
    """
    tec = cfg.reglas.tecnico
    serie = vista.serie(ticker)
    if serie is None:
        return None
    i = vista.posicion_hasta(ticker)
    if i < 0:
        return None

    # Si el ultimo dato es muy anterior a la fecha de decision, el valor ha
    # dejado de cotizar o le faltan datos; no se decide sobre eso.
    if serie.fechas[i] < fecha - timedelta(days=10):
        return None

    atr = _o_none(serie.atr[i])
    m_corta = _o_none(serie.ma_corta[i])
    m_larga = _o_none(serie.ma_larga[i])
    mom = _o_none(serie.momentum[i])

    # "Media de 200 sesiones" son 200 sesiones de verdad, no 200 filas que
    # podrian abarcar dos anos si la serie tiene agujeros.
    suficiente = (
        m_larga is not None
        and atr is not None
        and mom is not None
        and _sesiones_recientes(serie, i, fecha, tec.media_larga)
    )

    return SenalTecnica(
        ticker=ticker,
        mercado=mercado,
        fecha=fecha,
        cierre=float(serie.cierre[i]),
        media_corta=m_corta,
        media_larga=m_larga,
        momentum=mom,
        atr=float(atr) if atr is not None else 0.0,
        historial_suficiente=bool(suficiente),
    )


def _o_none(v) -> float | None:
    f = float(v)
    return None if np.isnan(f) else f


def _sesiones_recientes(serie, i: int, fecha: date, necesarias: int) -> bool:
    """Que las `necesarias` sesiones esten dentro de una ventana razonable.

    Se admite hasta un 50% mas de dias naturales que de sesiones exigidas, lo
    que da holgura para festivos sin dejar pasar series llenas de agujeros.
    """
    if i + 1 < necesarias:
        return False
    limite = fecha - timedelta(days=int(necesarias * 1.5) + 30)
    return bool(serie.fechas[i + 1 - necesarias] >= limite)


def regimen_por_mercado(
    fecha: date, vista: VistaPuntual, cfg: Config
) -> dict[str, bool]:
    """Si cada mercado admite posiciones nuevas.

    El documento pide comprobar el regimen por bloque y no con un unico indice
    global. Si falta el indice o esta desfasado se cierra el grifo en ese
    mercado en lugar de suponer que todo va bien: equivocarse hacia el lado
    prudente cuesta operaciones no hechas, y hacia el otro cuesta dinero.
    """
    salida: dict[str, bool] = {}
    for mercado_id, ticker_indice in cfg.reglas.tecnico.indices_regimen.items():
        serie = vista.serie(ticker_indice)
        if serie is None:
            salida[mercado_id] = False
            continue
        i = vista.posicion_hasta(ticker_indice)
        if i < 0 or serie.fechas[i] < fecha - timedelta(days=10):
            salida[mercado_id] = False
            continue
        media = _o_none(serie.ma_regimen[i])
        salida[mercado_id] = media is not None and float(serie.cierre[i]) > media
    return salida
