"""Registro de experimentos de backtest (§23).

Existe por RT-1: el riesgo no es equivocarse en un backtest, es probar cien
combinaciones sobre el mismo historico, quedarse con la mejor y no recordar que
se probaron cien. Con suficientes intentos siempre sale una curva preciosa, y
sin registro no hay forma de distinguirla de un hallazgo real.

La defensa es aritmetica, no moral: si cada experimento DISTINTO deja una fila,
contar filas da el numero de intentos, y ese numero es lo que permite juzgar si
el mejor resultado es senal o es el premio de una loteria con cien boletos.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .models.analysis import BacktestRun
from .models.enums import BacktestPeriod

#: Claves de `parameters` que NO entran en la huella porque no cambian el
#: resultado: describen la ejecucion, no el experimento. Si entraran, dos
#: ejecuciones identicas tendrian huellas distintas y el recuento de
#: experimentos —lo unico que esta tabla existe para medir— dejaria de servir.
CLAVES_NO_SIGNIFICATIVAS = frozenset({"ejecutado_en", "maquina", "duracion_s", "notas"})


def calcular_huella(
    *,
    model_version: str,
    period_kind: str,
    period_start: dt.date,
    period_end: dt.date,
    data_source: str,
    universe_hash: str,
    parameters: dict,
) -> str:
    """sha256 de todo lo que define el experimento.

    `sort_keys=True` no es cosmetico: sin el, dos diccionarios con las mismas
    claves en distinto orden darian huellas distintas y el mismo experimento
    contaria dos veces. `default=str` deja pasar fechas y Decimals sin que haya
    que acordarse de convertirlos en cada sitio que llama.
    """
    significativos = {k: v for k, v in parameters.items() if k not in CLAVES_NO_SIGNIFICATIVAS}
    material = json.dumps(
        {
            "model_version": model_version,
            "period_kind": period_kind,
            "period_start": str(period_start),
            "period_end": str(period_end),
            "data_source": data_source,
            "universe_hash": universe_hash,
            "parameters": significativos,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def registrar(
    sesion: Session,
    *,
    model_version_id: int,
    model_version: str,
    period_kind: str,
    period_start: dt.date,
    period_end: dt.date,
    data_source: str,
    universe_hash: str,
    universe_size: int,
    parameters: dict,
    metrics: dict,
    notes: str | None = None,
) -> tuple[int, bool]:
    """Anota un backtest. Devuelve `(id, es_nuevo)`.

    Repetir el MISMO experimento no crea una fila: incrementa `run_count` y
    actualiza `last_run_at`. Asi el recuento de filas sigue siendo el numero de
    experimentos distintos, que es la cifra con significado, sin perder que se
    volvio a ejecutar.

    Las metricas SI se sobrescriben al repetir. Si un experimento identico da
    numeros distintos, lo que hay es un problema de reproducibilidad, y quiero
    que el ultimo valor sea el vigente para que la discrepancia se vea al
    comparar con lo que se publico.
    """
    if period_kind not in set(BacktestPeriod):
        raise ValueError(f"period_kind desconocido: {period_kind!r}")
    if period_end <= period_start:
        raise ValueError("el periodo del backtest esta vacio o invertido")
    if universe_size <= 0:
        raise ValueError("un backtest sobre un universo vacio no significa nada")

    fingerprint = calcular_huella(
        model_version=model_version,
        period_kind=period_kind,
        period_start=period_start,
        period_end=period_end,
        data_source=data_source,
        universe_hash=universe_hash,
        parameters=parameters,
    )

    sentencia = (
        insert(BacktestRun)
        .values(
            model_version_id=model_version_id,
            period_kind=period_kind,
            period_start=period_start,
            period_end=period_end,
            data_source=data_source,
            universe_hash=universe_hash,
            universe_size=universe_size,
            parameters=parameters,
            metrics=metrics,
            fingerprint=fingerprint,
            run_count=1,
            notes=notes,
        )
        .on_conflict_do_update(
            index_elements=["fingerprint"],
            set_={
                "run_count": BacktestRun.__table__.c.run_count + 1,
                "last_run_at": func.now(),
                "metrics": metrics,
            },
        )
        .returning(BacktestRun.id, BacktestRun.run_count)
    )
    id_, run_count = sesion.execute(sentencia).one()
    return int(id_), run_count == 1


def experimentos_por_periodo(sesion: Session) -> dict[str, int]:
    """Cuantos experimentos DISTINTOS se han hecho sobre cada tramo.

    Es la consulta que responde a "cuantas veces hemos mirado el periodo de
    validacion", que segun RT-1 deberia ser muy pocas y al final del todo.
    """
    filas = sesion.execute(
        select(BacktestRun.period_kind, func.count()).group_by(BacktestRun.period_kind)
    ).all()
    return {clave: int(n) for clave, n in filas}
