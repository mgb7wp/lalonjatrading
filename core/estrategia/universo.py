"""Quien puede entrar en el universo, en una fecha concreta.

La elegibilidad se evalua a fecha, no una sola vez al empezar. Calcularla con
todo el historico seria dos sesgos a la vez: anticipacion, porque usaria
volumen que aun no se habia negociado, y supervivencia, porque un valor que hoy
es liquido pudo no serlo hace cinco anos.

El volumen se mide como importe negociado —precio BRUTO x volumen bruto,
convertido a divisa base con el cambio de cada fecha— y no como numero de
acciones. Se usa el precio bruto a proposito: el volumen que publican los
proveedores no se ajusta por dividendos, asi que multiplicarlo por el precio
ajustado subestima la liquidez de los anos antiguos, que es justo donde este
filtro decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .config import Config
from .datos.almacen import VistaPuntual
from .sectores import MapaSectores
from .tipos import MotivoRechazo


@dataclass(frozen=True, slots=True)
class Elegibilidad:
    """Resultado de comprobar si un valor puede formar parte del universo."""

    ticker: str
    mercado: str
    sector: str
    elegible: bool
    volumen_medio_base: float
    motivo: MotivoRechazo | None = None


def volumen_medio_base(
    ticker: str, mercado_id: str, fecha: date, vista: VistaPuntual, cfg: Config
) -> float:
    """Importe medio diario negociado, en divisa base, de las ultimas sesiones.

    Se usa el precio BRUTO, no el ajustado: el volumen que publican los
    proveedores no se ajusta por dividendos, asi que combinarlo con el precio
    ajustado subestima la liquidez de los anos antiguos, que es justo donde este
    filtro decide.
    """
    serie = vista.serie(ticker)
    i = vista.posicion_hasta(ticker)
    if serie is None or i < 0:
        return 0.0

    sesiones = cfg.reglas.universo.sesiones_volumen
    desde = max(0, i + 1 - sesiones)
    divisa = cfg.reglas.mercado(mercado_id).divisa

    # Un solo cambio para toda la ventana, el del dia de la decision. La
    # alternativa —convertir sesion a sesion— es mas fiel a la letra del
    # documento, pero multiplica por sesenta las consultas de divisa para mover
    # el resultado menos que el ruido del propio umbral.
    try:
        cambio = vista.fx(divisa, fecha, cfg.reglas.cartera.divisa_base)
    except Exception:
        return 0.0

    importes = serie.cierre_bruto[desde : i + 1] * serie.volumen[desde : i + 1]
    if importes.size == 0:
        return 0.0
    return float(np.mean(importes) * cambio)


def evaluar(
    fecha: date,
    vista: VistaPuntual,
    cfg: Config,
    mapa: MapaSectores,
    solo_mercado: str | None = None,
) -> dict[str, Elegibilidad]:
    """Elegibilidad del universo en esa fecha.

    `solo_mercado` limita el calculo a un mercado. La revision semanal va por
    mercado, y sin el filtro se recalcularia el volumen de los cinco mercados
    cinco veces cada semana.
    """
    salida: dict[str, Elegibilidad] = {}

    for mercado_id, valores in cfg.universo.mercados.items():
        if solo_mercado is not None and mercado_id != solo_mercado:
            continue
        mercado = cfg.reglas.mercado(mercado_id)
        minimo = cfg.reglas.universo.volumen_minimo(mercado.clasificacion)

        for valor in valores:
            ticker = valor.ticker
            clasificacion = mapa.clasificar(ticker, vista.sector(ticker))

            if not clasificacion.admitido:
                salida[ticker] = Elegibilidad(
                    ticker, mercado_id, clasificacion.sector, False, 0.0,
                    clasificacion.motivo,
                )
                continue

            volumen = volumen_medio_base(ticker, mercado_id, fecha, vista, cfg)
            if volumen < minimo:
                salida[ticker] = Elegibilidad(
                    ticker, mercado_id, clasificacion.sector, False, volumen,
                    MotivoRechazo.LIQUIDEZ_INSUFICIENTE,
                )
                continue

            salida[ticker] = Elegibilidad(
                ticker, mercado_id, clasificacion.sector, True, volumen
            )
    return salida
