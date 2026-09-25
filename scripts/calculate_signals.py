#!/usr/bin/env python
"""Emite las senales del dia a partir de los scores ya calculados.

    python scripts/calculate_signals.py
    python scripts/calculate_signals.py --mercados us,br --modelo momentum
    python scripts/calculate_signals.py --fecha 2026-06-30

Va DESPUES de `calculate_scores.py` y lee de la tabla `score`: no recalcula
nada. Cambiar los umbrales de senal es lo que uno toca a menudo, y tiene que
poder rehacerse sin volver a puntuar el universo entero y sin que los scores ya
publicados cambien por el camino.

Imprime el recuento por motivo, que es para lo que existe el vocabulario
cerrado: responder a "por que no hubo ni una compra esta semana".
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mercados", help="lista separada por comas; por defecto, todos")
    parser.add_argument("--fecha", help="fecha (AAAA-MM-DD); por defecto, hoy")
    parser.add_argument("--modelo", default="equilibrado", help="perfil de pesos de §18")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","nivel":"%(levelname)s","servicio":"senales",'
        '"operacion":"%(name)s","mensaje":"%(message)s"}',
    )

    from estrategia import config as core_config

    from backend.db.session import _fabrica
    from workers.pipeline import senales

    cfg = core_config.cargar()
    fecha = dt.date.fromisoformat(args.fecha) if args.fecha else dt.date.today()
    mercados = args.mercados.split(",") if args.mercados else None

    with _fabrica()() as sesion:
        recuento = senales.ejecutar(sesion, cfg, fecha=fecha, mercados=mercados, modelo=args.modelo)
        sesion.commit()

    if not recuento:
        print("no se ha emitido ninguna senal: ¿hay scores de esa fecha?")
        return 1

    print(f"senales del {fecha} ({args.modelo}):")
    for motivo, n in sorted(recuento.items(), key=lambda x: -x[1]):
        print(f"  {motivo:26} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
