"""Entorno de Alembic.

La URL sale de la configuracion de la aplicacion, no de alembic.ini: una sola
fuente para la cadena de conexion evita el clasico "las migraciones fueron a la
base de datos equivocada".
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.config import settings
from backend.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings().database_url)

target_metadata = Base.metadata


def include_object(objeto, nombre, tipo, reflejado, comparar_con):
    """Deja fuera del autogenerate las particiones de `price`.

    Las crea la migracion con SQL explicito y Postgres las refleja como tablas
    normales. Sin este filtro, cada autogenerate propondria borrar treinta y
    seis tablas que si tienen que estar.
    """
    if tipo == "table" and nombre.startswith("price_p"):
        return False
    return True


def migraciones_sin_conexion() -> None:
    context.configure(
        url=settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def migraciones_con_conexion() -> None:
    conectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with conectable.connect() as conexion:
        context.configure(
            connection=conexion,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    migraciones_sin_conexion()
else:
    migraciones_con_conexion()
