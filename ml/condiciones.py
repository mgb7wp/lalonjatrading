"""D-7 comprobada contra los datos, no contra la memoria de nadie.

La decision D-7 dice que el ML no arranca hasta que haya universo >= 1.000
valores limpios y >= 15 anios de historico en dos mercados. Mientras eso viva
solo en un documento, el dia que alguien tenga ganas de entrenar algo la
decision se salta sin querer y sin dejar rastro.

Aqui se mide y se devuelve un `no`. Encima se puede razonar.

## Por que 1.000 y 15 anios, y no "los que haya"

Una observacion de este sistema ocupa meses, y las consecutivas se solapan casi
del todo. Con 138 valores y ventanas de tres meses, las observaciones
INDEPENDIENTES son decenas, no miles: menos que los parametros de cualquier
modelo util. Lo que sale de ahi no generaliza, memoriza el periodo.

Y quince anios no es un capricho: menos de eso no cubre un ciclo completo con su
crisis dentro, asi que el modelo aprende como se comporta un mercado alcista y
lo llama "aprender a invertir".
"""

from __future__ import annotations

from dataclasses import dataclass

#: Los dos numeros de D-7. Aqui y en ningun otro sitio.
MINIMO_VALORES = 1000
MINIMO_ANIOS = 15
MINIMO_MERCADOS_CON_HISTORICO = 2


@dataclass(frozen=True, slots=True)
class Veredicto:
    cumple: bool
    valores: int
    mercados_con_historico: int
    anios_por_mercado: dict[str, float]
    motivos: list[str]

    def __str__(self) -> str:
        if self.cumple:
            return "D-7 cumplida: se puede entrenar"
        return "D-7 NO cumplida: " + "; ".join(self.motivos)


def evaluar(valores: int, anios_por_mercado: dict[str, float]) -> Veredicto:
    """Comprueba las dos condiciones. Funcion pura: se prueba sin base de datos."""
    con_historico = sorted(
        (m for m, a in anios_por_mercado.items() if a >= MINIMO_ANIOS),
        key=str,
    )
    motivos: list[str] = []

    if valores < MINIMO_VALORES:
        motivos.append(
            f"el universo tiene {valores} valores y hacen falta {MINIMO_VALORES} "
            f"({valores * 100 // MINIMO_VALORES}% del minimo)"
        )
    if len(con_historico) < MINIMO_MERCADOS_CON_HISTORICO:
        mejor = max(anios_por_mercado.values(), default=0.0)
        motivos.append(
            f"solo {len(con_historico)} mercado(s) llegan a {MINIMO_ANIOS} anios de "
            f"historico y hacen falta {MINIMO_MERCADOS_CON_HISTORICO}; el mas largo "
            f"tiene {mejor:.1f}"
        )

    return Veredicto(
        cumple=not motivos,
        valores=valores,
        mercados_con_historico=len(con_historico),
        anios_por_mercado=dict(anios_por_mercado),
        motivos=motivos,
    )


def medir(sesion) -> Veredicto:
    """Mide D-7 sobre la base de datos.

    Cuenta valores ACTIVOS y no filas de `security`: los indices y los dados de
    baja no son universo entrenable, y contarlos daria por cumplida la condicion
    antes de tiempo.
    """
    from sqlalchemy import text

    valores = int(
        sesion.execute(
            text("SELECT count(*) FROM security WHERE active = true AND asset_type <> 'index'")
        ).scalar()
        or 0
    )
    filas = sesion.execute(
        text(
            "SELECT s.market_id, min(p.date), max(p.date) "
            "FROM price p JOIN security s ON s.id = p.security_id "
            "WHERE s.asset_type <> 'index' GROUP BY s.market_id"
        )
    ).all()
    anios = {m: (hasta - desde).days / 365.25 for m, desde, hasta in filas}
    return evaluar(valores, anios)


class D7NoCumplida(RuntimeError):
    """Se ha intentado entrenar sin muestra suficiente."""


def exigir(veredicto: Veredicto) -> None:
    """Revienta si D-7 no se cumple.

    Va al principio de cualquier entrenamiento. Un aviso en el log se lee una
    vez y se ignora la siguiente; una excepcion no.
    """
    if not veredicto.cumple:
        raise D7NoCumplida(str(veredicto))
