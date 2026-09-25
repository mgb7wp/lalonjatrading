"""La puerta de aceptacion: cuando un modelo sustituye al baseline.

El criterio de la fase, literal: **un modelo solo sustituye al baseline si lo
bate fuera de muestra y despues de costes. Un resultado negativo se publica.**

## Por que esto es codigo y no una norma escrita

Una norma escrita se cumple cuando uno esta tranquilo. Despues de tres semanas
peleando con un modelo, "bate al baseline por 0,3 puntos dentro de muestra y con
costes cero" empieza a parecer suficiente. Si la decision la toma una funcion,
no hay conversacion.

## Lo que se exige

1. **Fuera de muestra.** La metrica de dentro de muestra ni se mira: un modelo
   con parametros de sobra la sube siempre.
2. **Despues de costes.** Un modelo que gana rotando cinco veces mas que el
   baseline no gana: paga comisiones y deslizamiento con la diferencia.
3. **Por un margen.** Batir por 0,001 es ruido. El margen minimo es explicito.
4. **En la mayoria de los pliegues.** Ganar de media pero perder en cuatro de
   cinco es haber tenido suerte en uno.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Cuanto hay que batir al baseline para que cuente. En puntos de la metrica.
#: No es cero a proposito: la diferencia entre dos modelos parecidos es ruido
#: muestral mucho mas a menudo de lo que parece.
MARGEN_MINIMO = 0.02

#: Fraccion de pliegues en los que hay que ganar. Mas de la mitad.
FRACCION_PLIEGUES = 0.6


@dataclass(frozen=True, slots=True)
class Resultado:
    """Lo que produce evaluar un candidato contra el baseline."""

    acepta: bool
    motivo: str
    media_candidato: float
    media_baseline: float
    pliegues_ganados: int
    pliegues: int
    detalles: dict = field(default_factory=dict)

    def __str__(self) -> str:
        veredicto = "ACEPTADO" if self.acepta else "RECHAZADO"
        return (
            f"{veredicto}: candidato {self.media_candidato:.4f} vs baseline "
            f"{self.media_baseline:.4f} ({self.pliegues_ganados}/{self.pliegues} "
            f"pliegues). {self.motivo}"
        )


def decidir(
    candidato_por_pliegue: list[float],
    baseline_por_pliegue: list[float],
    *,
    margen: float = MARGEN_MINIMO,
    fraccion: float = FRACCION_PLIEGUES,
) -> Resultado:
    """Decide si el candidato sustituye al baseline.

    Las dos listas son metricas **fuera de muestra y ya netas de costes**, una
    por pliegue. Que vengan asi es responsabilidad de quien evalua; esta funcion
    no puede comprobarlo y por eso lo dice en voz alta.
    """
    if not candidato_por_pliegue or len(candidato_por_pliegue) != len(baseline_por_pliegue):
        return Resultado(
            acepta=False,
            motivo="no hay metricas comparables por pliegue",
            media_candidato=float("nan"),
            media_baseline=float("nan"),
            pliegues_ganados=0,
            pliegues=len(candidato_por_pliegue),
        )

    n = len(candidato_por_pliegue)
    media_c = sum(candidato_por_pliegue) / n
    media_b = sum(baseline_por_pliegue) / n
    ganados = sum(
        1 for c, b in zip(candidato_por_pliegue, baseline_por_pliegue, strict=True) if c > b
    )
    minimo_ganados = -(-int(n * fraccion * 100) // 100)  # techo, sin float

    detalles = {
        "margen_exigido": margen,
        "diferencia": media_c - media_b,
        "pliegues_minimos": minimo_ganados,
    }

    if media_c - media_b < margen:
        return Resultado(
            acepta=False,
            motivo=(
                f"no bate al baseline por el margen exigido: {media_c - media_b:+.4f} < {margen}"
            ),
            media_candidato=media_c,
            media_baseline=media_b,
            pliegues_ganados=ganados,
            pliegues=n,
            detalles=detalles,
        )

    if ganados < minimo_ganados:
        return Resultado(
            acepta=False,
            motivo=(
                f"gana de media pero solo en {ganados} de {n} pliegues, y hacen "
                f"falta {minimo_ganados}: la media la sostiene un pliegue suelto"
            ),
            media_candidato=media_c,
            media_baseline=media_b,
            pliegues_ganados=ganados,
            pliegues=n,
            detalles=detalles,
        )

    return Resultado(
        acepta=True,
        motivo="bate al baseline fuera de muestra, despues de costes y en la mayoria de pliegues",
        media_candidato=media_c,
        media_baseline=media_b,
        pliegues_ganados=ganados,
        pliegues=n,
        detalles=detalles,
    )
