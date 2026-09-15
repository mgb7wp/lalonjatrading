"""Arranque del worker.

Sin Celery a proposito (decision D-11): APScheduler dentro de un contenedor
cubre un pipeline diario con mucho menos coste operativo, y el presupuesto de
§50 es real. Celery entrara cuando haya una razon concreta —paralelismo entre
mercados, reintentos persistentes—, no por costumbre.

Cada mercado se procesa tras **su** cierre, con su calendario y su huso. No hay
un "cierre global": es la primera cosa que se rompe en una plataforma
multi-mercado escrita como si solo existiera Nueva York.
"""

from __future__ import annotations

import logging
import signal
import sys
from types import FrameType

log = logging.getLogger("worker")


def configurar_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","nivel":"%(levelname)s","servicio":"worker",'
        '"operacion":"%(name)s","mensaje":"%(message)s"}',
    )


def main() -> int:
    configurar_logging()

    def parar(sig: int, _frame: FrameType | None) -> None:
        log.info("senal %s recibida, parando", sig)
        sys.exit(0)

    signal.signal(signal.SIGTERM, parar)
    signal.signal(signal.SIGINT, parar)

    log.info("worker arrancado; sin tareas programadas todavia (FASE 3)")
    signal.pause()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
