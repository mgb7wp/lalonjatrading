"""Base declarativa y convenciones comunes.

La convencion de nombres de restricciones no es cosmetica. Sin ella, Postgres
inventa nombres como `score_security_id_fkey1` y Alembic genera migraciones que
no saben que borrar: una restriccion sin nombre estable es una restriccion que
no se puede modificar dos veces. Se fija aqui, antes de la primera tabla, porque
cambiarla despues obliga a renombrar todo lo ya creado.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

CONVENCION_NOMBRES = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuracion
        pk: dict[str, Any] = {c.name: getattr(self, c.name) for c in self.__table__.primary_key}
        campos = ", ".join(f"{k}={v!r}" for k, v in pk.items())
        return f"<{type(self).__name__} {campos}>"


class Marcas:
    """`created_at` / `updated_at` en UTC, puestos por la base de datos.

    Por la base de datos y no por Python: los datos entran por la API, por los
    workers y por scripts de carga masiva, y tres relojes distintos producen un
    historial que no se puede ordenar.
    """

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
