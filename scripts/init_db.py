#!/usr/bin/env python
"""Deja la base de datos lista: migraciones y datos de referencia.

    python scripts/init_db.py

Idempotente de principio a fin. Se puede ejecutar en cada arranque de un
despliegue: `alembic upgrade head` no hace nada si ya esta al dia, y la carga de
referencia es un UPSERT sobre la clave natural.

Esa propiedad no es un lujo. Un script de inicializacion que solo se puede
ejecutar una vez acaba ejecutandose a mano, y un paso manual en el arranque de
un despliegue es un paso que algun dia se olvida.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--solo-migraciones",
        action="store_true",
        help="aplica el esquema sin cargar los datos de referencia",
    )
    args = parser.parse_args(argv)

    from alembic import command
    from alembic.config import Config

    from backend.config import settings

    cfg = settings()
    # Sin la contrasena: este mensaje acaba en los logs de despliegue.
    import sqlalchemy as sa

    url = sa.engine.make_url(cfg.database_url)
    print(f"base de datos: {url.render_as_string(hide_password=True)}")

    print("aplicando migraciones...")
    command.upgrade(Config(str(RAIZ / "alembic.ini")), "head")

    if args.solo_migraciones:
        print("listo (sin datos de referencia)")
        return 0

    from backend.db.seed import cargar
    from backend.db.session import _fabrica

    print("cargando datos de referencia...")
    with _fabrica()() as sesion:
        resumen = cargar(sesion)
        sesion.commit()
    print(f"listo: {resumen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
