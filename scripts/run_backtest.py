#!/usr/bin/env python
"""Backtest sobre los datos de Postgres, anotado en el registro de experimentos.

    python scripts/run_backtest.py
    python scripts/run_backtest.py --periodo validacion --modelo momentum
    python scripts/run_backtest.py --mercados us,br --salida informe.html

Cierra la FASE 7 juntando sus tres piezas: lee de la base con el adaptador
(`backend/adapters/desde_bd.py`), mide con las metricas nuevas —Sortino, profit
factor, rotacion, alfa contra las referencias— y **deja constancia del
experimento** en `backtest_run`.

Lo ultimo no es un extra. Un registro de experimentos que hay que acordarse de
rellenar a mano no se rellena, y entonces no sirve para lo unico que existe:
saber cuantas veces se ha buscado antes de encontrar (RT-1). Aqui se anota solo,
en la misma ejecucion, sin que nadie tenga que quererlo.

El periodo por defecto es el de DISENO. Pedir `--periodo validacion` esta
permitido y queda contado: el numero de experimentos distintos sobre validacion
es justo la cifra que dice si lo que sale de ahi sigue siendo una prueba
independiente.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def _huella_universo(tickers: list[str]) -> str:
    """sha256 del universo, ordenado.

    Ordenado porque el universo es un conjunto: que el adaptador los devuelva en
    otro orden no lo convierte en otro experimento.
    """
    return hashlib.sha256("|".join(sorted(tickers)).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mercados", help="lista separada por comas; por defecto, todos")
    parser.add_argument(
        "--periodo",
        choices=["diseno", "validacion", "completo"],
        default="diseno",
        help="tramo del historico (por defecto: diseno)",
    )
    parser.add_argument("--modelo", default="equilibrado", help="perfil de pesos de §18")
    parser.add_argument("--salida", help="ruta donde escribir el informe HTML")
    parser.add_argument(
        "--sin-registrar",
        action="store_true",
        help="no anota el experimento (para pruebas; usalo poco y a sabiendas)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","nivel":"%(levelname)s","servicio":"backtest",'
        '"operacion":"%(name)s","mensaje":"%(message)s"}',
    )

    import estrategia
    from estrategia import backtest as backtest_mod
    from estrategia import config as core_config
    from estrategia import validacion as validacion_mod
    from estrategia.informe import a_markdown, construir

    from backend.adapters.desde_bd import BaseContaminada, instantanea_desde_bd
    from backend.db import experimentos
    from backend.db.session import _fabrica
    from workers.pipeline.scores import cargar_modelos

    cfg = core_config.cargar()
    mercados = args.mercados.split(",") if args.mercados else None

    with _fabrica()() as sesion:
        try:
            inst = instantanea_desde_bd(sesion, mercados=mercados)
        except BaseContaminada as e:
            print(f"ERROR: {e}")
            return 2

        if inst.precios.empty:
            print("no hay precios en la base de datos. Ejecuta antes update_market_data.py")
            return 1

        inst.preparar(cfg)
        division = validacion_mod.dividir(inst, cfg)
        inicio, fin = {
            "diseno": division.diseno,
            "validacion": division.validacion,
            "completo": (division.inicio, division.fin),
        }[args.periodo]

        print(f"backtest {args.periodo}: {inicio} -> {fin}  ({args.modelo})")
        resultado = backtest_mod.ejecutar(inst, cfg, inicio, fin)
        informe = construir(resultado, cfg, inst)

        if args.salida:
            from estrategia.informe_html import a_html

            Path(args.salida).write_text(a_html(informe), encoding="utf-8")
            print(f"informe escrito en {args.salida}")
        else:
            print(a_markdown(informe))

        if args.sin_registrar:
            print("NO registrado: este experimento no cuenta en el recuento de RT-1")
            return 0

        modelos = cargar_modelos(sesion, RAIZ / "config" / "modelos.yaml")
        modelo = modelos.get(args.modelo)
        if modelo is None:
            print(f"perfil desconocido: {args.modelo}. Hay: {', '.join(sorted(modelos))}")
            return 1

        tickers = sorted(set(inst.precios["ticker"]))
        id_, nuevo = experimentos.registrar(
            sesion,
            model_version_id=modelo.id,
            model_version=f"{modelo.name}:{modelo.version}",
            period_kind=args.periodo,
            period_start=inicio,
            period_end=fin,
            data_source=inst.origen,
            universe_hash=_huella_universo(tickers),
            universe_size=len(tickers),
            # Los dos sitios donde vive lo que se toca, y los dos tienen que
            # entrar en la huella: `reglas` son los umbrales y costes del motor;
            # `pesos` son los del perfil de §18, que viven en modelos.yaml.
            # Guardar solo el nombre del perfil daria la misma huella a dos
            # juegos de pesos distintos, y entonces el recuento de experimentos
            # —lo unico que esta tabla existe para medir— contaria de menos.
            parameters={
                "modelo": args.modelo,
                "reglas": cfg.reglas.model_dump(mode="json"),
                "pesos": modelo.parameters or {},
                # La version del motor tambien define el experimento: con los
                # mismos parametros, un motor corregido da otros numeros, y sin
                # esto el backtest nuevo sobrescribiria las metricas del viejo.
                "motor": estrategia.__version__,
            },
            metrics=informe.resumen.como_dict(),
        )
        sesion.commit()

        recuento = experimentos.experimentos_por_periodo(sesion)
        print(
            f"experimento #{id_} ({'nuevo' if nuevo else 'repetido'}). "
            f"Distintos hasta ahora: {recuento}"
        )
        # `completo` incluye el periodo de validacion: tambien lo gasta.
        usados = recuento.get("validacion", 0) + recuento.get("completo", 0)
        if usados > cfg.reglas.validacion.consultas_para_alarma:
            print(
                f"AVISO: el periodo de validacion se ha usado en {usados} "
                f"experimentos distintos. Cada uno lo acerca mas a ser un "
                f"segundo periodo de diseno."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
