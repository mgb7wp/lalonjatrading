"""Asignacion de huecos: que candidatas se compran esta semana.

Este paso ocurre **al decidir**, no al ejecutar, y esa es la decision de diseno
que justifica el modulo. Si los limites de cartera se comprobasen en el momento
del fill, el mercado que abre antes se quedaria siempre con los huecos: India
abre a las 04:00 UTC, Europa a las 08:00 y EE. UU. a las 14:30, asi que un
lunes cualquiera India elegiria primero. Repetido a lo largo de anos, eso es una
inclinacion sistematica hacia un mercado por razones de huso horario, no de
estrategia. Reservando los huecos en el corte semanal, todas las candidatas
compiten en igualdad y el orden lo marca la puntuacion.

Las candidatas se recorren de mejor a peor y las que no caben se **saltan**: se
sigue bajando por la lista, no se corta en el primer rechazo. El documento dice
"se compran por ese orden mientras queden huecos", que admite las dos lecturas;
esta es la que llena la cartera.

Cada rechazo se registra con su motivo y su puesto en el ranking. Eso es lo que
permite que el informe conteste a "por que no se compro la mejor candidata", y
que se pueda ver si un limite esta costando dinero de forma sistematica.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from . import riesgo as riesgo_mod
from . import salidas as salidas_mod
from .cartera import Cartera
from .config import Config
from .tipos import Candidata, MotivoRechazo, Orden


@dataclass(frozen=True, slots=True)
class Rechazo:
    """Una candidata que no llego a orden, con su motivo y su puesto."""

    ticker: str
    mercado: str
    sector: str
    rango: int
    motivo: MotivoRechazo
    puntuacion_final: float


@dataclass(frozen=True, slots=True)
class Asignacion:
    """Lo que sale de una revision semanal."""

    ordenes: list[Orden]
    rechazos: list[Rechazo]


def asignar(
    fecha: date,
    candidatas: list[Candidata],
    cartera: Cartera,
    regimen: dict[str, bool],
    fx_decision: dict[str, float],
    capital_base: float,
    cfg: Config,
) -> Asignacion:
    """Reparte los huecos libres entre las candidatas, de mejor a peor.

    `fx_decision` trae el cambio divisa->base del dia anterior, que es el que se
    usa para decidir y dimensionar.
    """
    reglas = cfg.reglas.cartera
    ordenes: list[Orden] = []
    rechazos: list[Rechazo] = []

    # Estado reservado: parte del estado real y se va consumiendo segun se
    # asignan huecos, para que dos candidatas no se queden el mismo.
    n_posiciones = cartera.n_posiciones
    por_sector = {s: cartera.n_en_sector(s) for s in {c.sector for c in candidatas}}
    por_mercado = {m: cartera.n_en_mercado(m) for m in {c.mercado for c in candidatas}}
    efectivo = cartera.efectivo

    for rango, cand in enumerate(candidatas, start=1):

        def rechazar(motivo: MotivoRechazo) -> None:
            rechazos.append(
                Rechazo(cand.ticker, cand.mercado, cand.sector, rango, motivo,
                        cand.puntuacion_final)
            )

        if cartera.tiene(cand.ticker):
            rechazar(MotivoRechazo.YA_EN_CARTERA)
            continue
        if not regimen.get(cand.mercado, False):
            rechazar(MotivoRechazo.REGIMEN_APAGADO)
            continue
        if n_posiciones >= reglas.max_posiciones:
            rechazar(MotivoRechazo.SIN_HUECO)
            continue
        if por_sector.get(cand.sector, 0) >= reglas.max_por_sector:
            rechazar(MotivoRechazo.TOPE_SECTOR)
            continue
        if por_mercado.get(cand.mercado, 0) >= reglas.max_por_mercado:
            rechazar(MotivoRechazo.TOPE_MERCADO)
            continue

        cambio = fx_decision.get(cfg.reglas.mercado(cand.mercado).divisa)
        if cambio is None:
            rechazar(MotivoRechazo.SIN_PRECIO_EJECUCION)
            continue

        precio_local = cand.senal.cierre
        stop_local = salidas_mod.stop_inicial(precio_local, cand.senal.atr, cfg)
        if stop_local <= 0:
            rechazar(MotivoRechazo.TAMANO_CERO)
            continue

        tamano = riesgo_mod.calcular(
            capital_base=capital_base,
            precio_entrada_base=precio_local * cambio,
            stop_inicial_base=stop_local * cambio,
            lote=cfg.reglas.universo.lote(cand.mercado),
            cfg=cfg,
        )
        if tamano.acciones <= 0:
            rechazar(MotivoRechazo.TAMANO_CERO)
            continue

        # Se reserva con un margen para comision y deslizamiento; el importe
        # exacto se conocera en la apertura y puede variar.
        reserva = tamano.nominal_base * 1.01 + cfg.reglas.costes.comision_fija_eur
        if reserva > efectivo:
            rechazar(MotivoRechazo.EFECTIVO_INSUFICIENTE)
            continue

        ordenes.append(
            Orden(
                ticker=cand.ticker,
                mercado=cand.mercado,
                sector=cand.sector,
                fecha_decision=fecha,
                acciones=tamano.acciones,
                stop_inicial_local=stop_local,
                atr_entrada=cand.senal.atr,
                rango_asignacion=rango,
                puntuacion_final=cand.puntuacion_final,
                riesgo_teorico_pct=tamano.riesgo_teorico_pct,
                riesgo_efectivo_pct=tamano.riesgo_efectivo_pct,
                limitada_por_peso_maximo=tamano.limitada_por_peso_maximo,
            )
        )
        n_posiciones += 1
        por_sector[cand.sector] = por_sector.get(cand.sector, 0) + 1
        por_mercado[cand.mercado] = por_mercado.get(cand.mercado, 0) + 1
        efectivo -= reserva

    return Asignacion(ordenes, rechazos)
