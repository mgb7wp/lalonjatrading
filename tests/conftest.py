"""Fixtures compartidas.

Las de base de datos viven aqui y no en un modulo aparte que se importe: pytest
las descubre solas, y asi ningun test necesita importar una fixture (importarla
la redefine en el modulo, que es un patron que confunde a las herramientas y a
quien lee).

Los tests no tocan la red ni dependen de datos descargados: todo sale del
proveedor sintetico, que es determinista. Un test que fallara solo los martes
porque el mercado hizo algo raro no serviria para nada.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest
import sqlalchemy as sa
from estrategia import config as config_mod
from estrategia.datos.almacen import Instantanea
from estrategia.datos.sintetico import ProveedorSintetico

#: Secreto de firma SOLO para los tests. Se pone antes de que nada lea la
#: configuracion: `settings()` esta cacheada, asi que si un import la lee primero
#: el valor se congela vacio y los tests de autenticacion revientan.
#:
#: Va aqui y no en el fichero de CI porque una suite que solo pasa si alguien se
#: acordo de exportar una variable de entorno no es una suite: es una trampa. Es
#: exactamente lo que dejo el CI en rojo desde la FASE 12 sin que se notara en
#: local, donde ese entorno si estaba puesto.
SECRETO_DE_PRUEBAS = "secreto-solo-para-los-tests-no-sirve-en-ningun-despliegue"


def pytest_configure(config):  # noqa: ARG001 - firma de pytest
    os.environ.setdefault("JWT_SECRET", SECRETO_DE_PRUEBAS)
    os.environ.setdefault("ENTORNO", "pruebas")

    import backend.config

    backend.config.settings.cache_clear()


INICIO = dt.date(2019, 1, 1)
FIN = dt.date(2024, 12, 31)


@pytest.fixture(scope="session")
def cfg():
    return config_mod.cargar()


@pytest.fixture(scope="session")
def proveedor(cfg):
    return ProveedorSintetico(cfg)


@pytest.fixture(scope="session")
def instantanea(cfg, proveedor):
    """Instantanea completa, compartida por toda la sesion de tests."""
    tickers = cfg.universo.tickers()
    indices = list(cfg.reglas.tecnico.indices_regimen.values())
    referencias = [r.ticker for r in cfg.implementacion.referencias.values()]
    inst = Instantanea(
        precios=proveedor.precios(tickers + indices + referencias, INICIO, FIN),
        fundamentales=proveedor.fundamentales(tickers, INICIO, FIN),
        fx=proveedor.fx(["USD", "INR", "BRL"], INICIO, FIN),
        sectores=proveedor.sectores(tickers),
        fecha_descarga=FIN,
        origen="sintetico",
    )
    return inst.preparar(cfg)


# ---------------------------------------------------------------------------
# Base de datos (FASE 2)
# ---------------------------------------------------------------------------


URL_POR_DEFECTO = "postgresql+psycopg://lalonja@/lalonja_test?host=/tmp&port=5432"


@pytest.fixture(scope="session")
def engine():
    """Base de datos de pruebas recreada desde cero y migrada con Alembic.

    Desde cero en cada sesion a proposito: es el criterio de aceptacion de la
    FASE 2 —la migracion se aplica sobre una base de datos limpia— y asi se
    ejerce en cada ejecucion en lugar de comprobarse a mano una vez.
    """
    url = os.environ.get("TEST_DATABASE_URL", URL_POR_DEFECTO)

    # Guardarrail. Esta fixture BORRA el esquema entero, asi que se niega a
    # trabajar sobre una base de datos que no se llame de pruebas: un `pytest`
    # lanzado con el .env de desarrollo cargado no puede vaciar la base de datos
    # de uno. El nombre se saca con el parser de SQLAlchemy y no partiendo la
    # cadena, porque una URL con `host=/tmp` lleva barras despues del nombre.
    nombre = sa.engine.make_url(url).database or ""
    if "test" not in nombre:
        pytest.fail(
            f"TEST_DATABASE_URL apunta a una base de datos que no es de pruebas: {nombre!r}"
        )

    motor = sa.create_engine(url)
    try:
        with motor.connect() as c:
            c.execute(sa.text("SELECT 1"))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"sin Postgres accesible ({type(e).__name__}); se omiten los de BD")

    with motor.begin() as c:
        c.execute(sa.text("DROP SCHEMA public CASCADE"))
        c.execute(sa.text("CREATE SCHEMA public"))

    from alembic import command
    from alembic.config import Config

    import backend.config

    os.environ["DATABASE_URL"] = url
    backend.config.settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")

    yield motor
    motor.dispose()


@pytest.fixture
def sesion(engine):
    """Sesion que se deshace al terminar, para que un test no ensucie al siguiente."""
    with sa.orm.Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture(scope="session")
def bd_con_referencia(engine):
    """Base de datos con los paises, divisas, mercados, bolsas y valores cargados."""
    from backend.db.seed import cargar

    with sa.orm.Session(engine) as s:
        cargar(s)
        s.commit()
    return engine
