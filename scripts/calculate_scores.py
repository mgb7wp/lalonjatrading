#!/usr/bin/env python
"""Calcula los scores y los deja en Postgres.

    python scripts/calculate_scores.py
    python scripts/calculate_scores.py --mercados us,br
    python scripts/calculate_scores.py --fecha 2026-06-30

Es el segundo objetivo operativo del encargo (§60), despues de
`update_market_data.py`. Calcula los cinco perfiles de §18 en la misma pasada:
comparten los factores en bruto, que es el trabajo caro, y solo difieren en los
pesos.

**Reproducible**: reejecutarlo sobre la misma instantanea da exactamente los
mismos numeros. Un percentil dentro de una cohorte es una funcion determinista
de sus datos y de nada mas.
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
    parser.add_argument("--fecha", help="fecha de valoracion (AAAA-MM-DD); por defecto, hoy")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","nivel":"%(levelname)s","servicio":"scoring",'
        '"operacion":"%(name)s","mensaje":"%(message)s"}',
    )

    from estrategia import config as core_config

    from backend.db.session import _fabrica
    from workers.pipeline import scores

    cfg = core_config.cargar()
    fecha = dt.date.fromisoformat(args.fecha) if args.fecha else dt.date.today()
    mercados = args.mercados.split(",") if args.mercados else None

    with _fabrica()() as sesion:
        escritos = scores.ejecutar(sesion, cfg, fecha=fecha, mercados=mercados)

    if not escritos:
        print("no se ha podido puntuar ningun valor: ¿hay datos cargados?")
        return 1
    print(f"scores del {fecha}:")
    for modelo, n in escritos.items():
        print(f"  {modelo:14} {n} valores")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
