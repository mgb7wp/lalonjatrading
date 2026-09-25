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

from .config import Config
from .datos.almacen import VistaPuntual
from .tipos import SenalTecnica


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
    if serie.fechas[i] < fecha - timedelta(days=cfg.reglas.datos.dias_maximos_sin_precio):
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
        and _sesiones_recientes(serie, i, fecha, tec.media_larga, cfg)
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


def _sesiones_recientes(
    serie, i: int, fecha: date, necesarias: int, cfg: Config
) -> bool:
    """Que las `necesarias` sesiones esten dentro de una ventana razonable.

    Se admiten `holgura_historial_factor` veces mas dias naturales que sesiones
    exigidas, mas `holgura_historial_dias`: holgura para festivos sin dejar
    pasar series llenas de agujeros.
    """
    if i + 1 < necesarias:
        return False
    tec = cfg.reglas.tecnico
    dias = int(necesarias * tec.holgura_historial_factor) + tec.holgura_historial_dias
    limite = fecha - timedelta(days=dias)
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
        maximo = timedelta(days=cfg.reglas.datos.dias_maximos_sin_precio)
        if i < 0 or serie.fechas[i] < fecha - maximo:
            salida[mercado_id] = False
            continue
        media = _o_none(serie.ma_regimen[i])
        salida[mercado_id] = media is not None and float(serie.cierre[i]) > media
    return salida
