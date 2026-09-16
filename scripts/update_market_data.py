#!/usr/bin/env python
"""Descarga datos de mercado y los deja en Postgres.

    python scripts/update_market_data.py
    python scripts/update_market_data.py --mercados us,es --anos 3
    python scripts/update_market_data.py --proveedor sintetico   # sin red

Es el primer objetivo operativo del encargo (§60). **Idempotente**: ejecutarlo
dos veces el mismo dia no cambia una sola fila, porque cada etapa ya terminada
se salta y todo lo que escribe va por UPSERT sobre la clave natural.

Si un mercado falla, se registra y se sigue con el siguiente. Con cinco mercados
y fuentes gratuitas, que la India no responda no puede dejar sin actualizar a
EE. UU.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mercados", help="lista separada por comas; por defecto, todos")
    parser.add_argument("--anos", type=int, default=8, help="historico a descargar")
    parser.add_argument(
        "--proveedor",
        help="fuerza una sola fuente para todo, ignorando el reparto de reglas.yaml",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="repite etapas ya terminadas hoy en lugar de saltarlas",
    )
    parser.add_argument(
        "--sin-indicadores",
        action="store_true",
        help="no recalcula los indicadores tecnicos tras la descarga",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","nivel":"%(levelname)s","servicio":"ingesta",'
        '"operacion":"%(name)s","mensaje":"%(message)s"}',
    )

    from estrategia import config as core_config
    from estrategia.datos.enrutador import Enrutador

    from backend.db.session import _fabrica
    from workers.pipeline import indicadores, ingesta

    cfg = core_config.cargar()
    if args.proveedor:
        cfg = cfg.con_fuente_unica(args.proveedor)
    enrutador = Enrutador(cfg)

    faltan = enrutador.comprobar_disponibilidad()
    if faltan:
        # Antes de descargar nada: que la falta de una clave sea un mensaje
        # claro al arrancar y no un error a mitad de una descarga de media hora.
        for aviso in faltan:
            print(f"AVISO: {aviso}")

    mercados = args.mercados.split(",") if args.mercados else None

    print(f"reparto de fuentes: {enrutador.reparto}")
    with _fabrica()() as sesion:
        resultados = ingesta.ejecutar(
            sesion, cfg, enrutador, mercados=mercados, anos=args.anos, forzar=args.forzar
        )
        rancios = ingesta.marcar_rancios(sesion, ingesta._umbrales_rancio(cfg))

        # Siempre despues de la descarga y en la misma ejecucion. Un indicador
        # es una derivacion determinista de los precios: si estos se actualizan
        # y aquellos no, lo que sirve la API deja de corresponderse con la base
        # de datos y nada avisa, porque los numeros siguen pareciendo normales.
        calculados = {}
        if not args.sin_indicadores:
            calculados = indicadores.ejecutar(sesion, cfg, mercados=mercados)

    for r in resultados:
        print(r)
    for mercado_id, n in calculados.items():
        print(f"  {mercado_id}/indicadores: {n} filas")
    if rancios:
        print(f"{rancios} conjuntos marcados como rancios")

    fallos = [r for r in resultados if r.estado == "failed"]
    if fallos:
        print(f"\n{len(fallos)} etapas han fallado. El resto si se ha actualizado.")
        # Codigo distinto de cero para que un cron lo note, pero solo despues de
        # haber hecho todo lo que si se podia hacer.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
