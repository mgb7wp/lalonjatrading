"""Ordenacion final de las candidatas.

Junta la puntuacion fundamental con el percentil de momentum segun
`seleccion.pesos`. El momentum se percentila dentro de cada mercado por la misma
razon que los ratios: comparar en bruto la rentabilidad de doce meses de una
accion brasilena con la de una alemana mezcla dos ciclos economicos y dos
inflaciones distintas y no dice nada util. Una vez ambas notas estan
percentiladas, si son comparables entre mercados, que es lo que permite ordenar
una lista global de candidatas.

Las cohortes pequenas se tratan aqui igual que en `fundamental.py`: posiciones
de Hazen y recurso al bloque cuando el mercado no tiene gente suficiente.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .config import Config
from .fundamental import percentiles_hazen
from .tipos import Candidata, CohorteUsada, PuntuacionFundamental, SenalTecnica


def ordenar_candidatas(
    fecha: date,
    comprables: dict[str, SenalTecnica],
    puntuaciones: dict[str, PuntuacionFundamental],
    sectores: dict[str, str],
    cfg: Config,
) -> list[Candidata]:
    """Lista global de candidatas, de mejor a peor.

    `comprables` solo debe traer las que ya pasan el filtro tecnico y el de
    regimen; aqui no se vuelve a filtrar, solo se ordena.
    """
    if not comprables:
        return []

    fcfg = cfg.reglas.fundamental
    pesos = cfg.reglas.seleccion.pesos

    filas = []
    for ticker, senal in comprables.items():
        pf = puntuaciones.get(ticker)
        # Sin la pata fundamental activa, todas parten de una nota neutra y
        # manda el momentum. Es el modo que permite validar el motor sobre un
        # historico largo, donde no hay fundamentales.
        if not fcfg.activo:
            nota_fundamental = 50.0
            n_cohorte, cohorte_usada = 0, CohorteUsada.INSUFICIENTE
        elif pf is None or not pf.aprueba or pf.puntuacion is None:
            continue
        else:
            nota_fundamental = pf.puntuacion
            n_cohorte, cohorte_usada = pf.n_cohorte, pf.cohorte_usada

        filas.append(
            {
                "ticker": ticker,
                "mercado": senal.mercado,
                "sector": sectores.get(ticker, ""),
                "bloque": cfg.reglas.mercado(senal.mercado).clasificacion,
                "momentum": senal.momentum,
                "nota_fundamental": nota_fundamental,
                "n_cohorte": n_cohorte,
                "cohorte_usada": cohorte_usada,
                "senal": senal,
            }
        )

    if not filas:
        return []
    df = pd.DataFrame(filas)

    percentil_mom: dict[int, float] = {}
    for mercado, grupo in df.groupby("mercado", sort=True):
        if len(grupo) >= fcfg.min_empresas_percentil:
            cohorte = grupo
        else:
            bloque = cfg.reglas.mercado(mercado).clasificacion
            cohorte = df[df["bloque"] == bloque]
        pct = percentiles_hazen(cohorte["momentum"].astype(float))
        for idx in grupo.index:
            percentil_mom[idx] = float(pct.get(idx, 50.0))

    candidatas: list[Candidata] = []
    for idx, fila in df.iterrows():
        p_mom = percentil_mom.get(idx, 50.0)
        final = pesos.fundamental * fila["nota_fundamental"] + pesos.momentum * p_mom
        candidatas.append(
            Candidata(
                ticker=fila["ticker"],
                mercado=fila["mercado"],
                sector=fila["sector"],
                fecha_decision=fecha,
                puntuacion_fundamental=float(fila["nota_fundamental"]),
                percentil_momentum=p_mom,
                puntuacion_final=float(final),
                senal=fila["senal"],
                n_cohorte=int(fila["n_cohorte"]),
                cohorte_usada=fila["cohorte_usada"],
            )
        )

    # El desempate por ticker no es cosmetico: sin el, dos ejecuciones del mismo
    # backtest pueden dar carteras distintas segun como ordene pandas.
    candidatas.sort(key=lambda c: c.clave_orden())
    return candidatas
