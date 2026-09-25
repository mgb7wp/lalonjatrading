"""Walk-forward purgado y con embargo.

Es la pieza que decide si un backtest de un modelo significa algo. Sin ella, las
metricas fuera de muestra salen preciosas y no valen nada.

## El problema, concretamente

Una observacion de este sistema no es un punto: es un INTERVALO. Si el 1 de
enero se pregunta "¿batira al indice en tres meses?", esa etiqueta no se conoce
hasta el 1 de abril. La observacion ocupa enero-abril entera.

Con una particion ingenua —entreno hasta el 31 de marzo, pruebo desde el 1 de
abril— la observacion del 1 de febrero esta en el entrenamiento y su etiqueta se
resolvio el 1 de mayo, ya dentro del periodo de prueba. El modelo ha visto lo
que pasaba en mayo mientras "aprendia". No es una fuga sutil: es la misma
informacion en los dos lados.

**Purgar** es quitar del entrenamiento toda observacion cuyo intervalo de
etiqueta se solape con el periodo de prueba.

## El embargo

Aparte del solape esta la correlacion en serie: dos observaciones consecutivas
comparten casi todo el precio. Una que empieza el dia despues del final de la
prueba sigue estando pegada a ella. El **embargo** quita tambien una franja
posterior.

**Aviso honesto sobre el embargo**: en un walk-forward estricto —entrenar solo
con el pasado— el embargo NO muerde nunca, porque no hay entrenamiento despues
de la prueba. Se implementa igual y hay un test que lo demuestra mordiendo,
porque la variante de validacion cruzada si mete datos posteriores, y ahi es
imprescindible. Decir que "esta protegido por embargo" cuando el embargo no
toca nada seria una tranquilidad falsa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class Pliegue:
    """Un corte: que indices entrenan, cuales prueban y que se ha quitado."""

    indice: int
    entrenamiento: np.ndarray
    prueba: np.ndarray
    inicio_prueba: date
    fin_prueba: date
    purgadas: int
    embargadas: int


class ParticionImposible(ValueError):
    """No hay datos suficientes para los pliegues pedidos."""


def _a_fechas(serie) -> np.ndarray:
    return pd.to_datetime(pd.Series(serie)).dt.date.to_numpy()


def walk_forward(
    inicios,
    horizonte_dias: int,
    *,
    n_pliegues: int = 5,
    embargo_dias: int = 0,
    permitir_futuro: bool = False,
) -> list[Pliegue]:
    """Parte una muestra en pliegues sucesivos, purgando el solape.

    `inicios` son las fechas de decision, una por observacion. La etiqueta de
    cada una se resuelve `horizonte_dias` despues.

    `permitir_futuro=False` es el walk-forward de verdad: se entrena SOLO con lo
    anterior a la prueba, que es lo unico que se podria haber hecho en su dia.
    Ponerlo a `True` da la variante de validacion cruzada —entrena tambien con
    lo posterior— que sirve para medir capacidad, no para simular una decision.
    """
    fechas = _a_fechas(inicios)
    if len(fechas) == 0:
        raise ParticionImposible("no hay observaciones que partir")
    if n_pliegues < 1:
        raise ParticionImposible("hacen falta al menos un pliegue")
    if horizonte_dias <= 0:
        raise ParticionImposible("el horizonte tiene que ser positivo")

    fines = np.array([f + timedelta(days=horizonte_dias) for f in fechas])
    orden = np.argsort(fechas, kind="stable")
    ordenadas = fechas[orden]

    # Los bloques de prueba se reparten por NUMERO DE OBSERVACIONES y no por
    # tiempo natural: repartir por tiempo deja pliegues vacios en los periodos
    # con pocos datos, y entonces la media de las metricas pesa raro.
    cortes = np.array_split(orden, n_pliegues)
    if any(len(c) == 0 for c in cortes):
        raise ParticionImposible(f"{len(fechas)} observaciones no dan para {n_pliegues} pliegues")

    pliegues: list[Pliegue] = []
    for k, bloque in enumerate(cortes):
        inicio_prueba = min(fechas[i] for i in bloque)
        # El periodo de prueba ocupa hasta que se resuelve su ULTIMA etiqueta,
        # no hasta su ultima fecha de decision. Usar la segunda dejaria fuera
        # justo el tramo que provoca el solape.
        fin_prueba = max(fines[i] for i in bloque)

        candidatos = np.array([i for i in orden if i not in set(bloque.tolist())], dtype=int)
        if not permitir_futuro:
            candidatos = np.array([i for i in candidatos if fechas[i] < inicio_prueba], dtype=int)

        antes = len(candidatos)
        # Purga: fuera todo lo que se solape con [inicio_prueba, fin_prueba].
        sin_solape = np.array(
            [i for i in candidatos if fines[i] < inicio_prueba or fechas[i] > fin_prueba],
            dtype=int,
        )
        purgadas = antes - len(sin_solape)

        embargadas = 0
        if embargo_dias > 0:
            limite = fin_prueba + timedelta(days=embargo_dias)
            tras_embargo = np.array(
                [i for i in sin_solape if not (fin_prueba < fechas[i] <= limite)],
                dtype=int,
            )
            embargadas = len(sin_solape) - len(tras_embargo)
            sin_solape = tras_embargo

        pliegues.append(
            Pliegue(
                indice=k,
                entrenamiento=np.sort(sin_solape),
                prueba=np.sort(bloque),
                inicio_prueba=inicio_prueba,
                fin_prueba=fin_prueba,
                purgadas=purgadas,
                embargadas=embargadas,
            )
        )

    _ = ordenadas  # documenta que la entrada se ordena; no se usa mas
    return pliegues


def hay_fuga(pliegue: Pliegue, inicios, horizonte_dias: int) -> bool:
    """`True` si alguna observacion de entrenamiento se solapa con la prueba.

    Existe para que los tests no tengan que reimplementar la comprobacion, y
    para poder llamarla como afirmacion en el propio entrenamiento: una fuga que
    solo vigila un test es una fuga que vuelve en cuanto alguien toque la
    particion desde otro sitio.
    """
    fechas = _a_fechas(inicios)
    fines = np.array([f + timedelta(days=horizonte_dias) for f in fechas])
    for i in pliegue.entrenamiento:
        if not (fines[i] < pliegue.inicio_prueba or fechas[i] > pliegue.fin_prueba):
            return True
    return False
