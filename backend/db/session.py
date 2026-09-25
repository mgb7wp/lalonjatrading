"""Conexion a Postgres.

El motor se crea de forma perezosa. Sin eso, importar la aplicacion para correr
un test o generar el OpenAPI exigiria una base de datos levantada, y la API
dejaria de poder arrancar en modo degradado para *informar* de que la base de
datos no responde, que es justo lo que /health tiene que poder hacer.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings


@lru_cache
def engine() -> Engine:
    return create_engine(settings().database_url, pool_pre_ping=True, future=True)


@lru_cache
def _fabrica() -> sessionmaker[Session]:
    return sessionmaker(bind=engine(), autoflush=False, expire_on_commit=False)


def sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesion por peticion."""
    s = _fabrica()()
    try:
        yield s
    finally:
        s.close()


def comprobar() -> tuple[bool, str]:
    """Si la base de datos responde, y por que no si no.

    Devuelve el error en lugar de lanzarlo: /health tiene que poder contar que
    la base de datos esta caida, no caerse con ella.
    """
    try:
        with engine().connect() as c:
            c.execute(text("SELECT 1"))
        return True, ""
    except Exception as e:  # noqa: BLE001 - aqui cualquier fallo es "no responde"
        return False, f"{type(e).__name__}: {e}"
