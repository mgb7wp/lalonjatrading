"""La regla de dependencias, comprobada y no solo documentada.

`core/estrategia` es el motor cuantitativo: datos, indicadores, scoring,
backtest. `backend`, `workers` y `ml` son la plataforma. La direccion de las
importaciones va siempre de la plataforma hacia el motor, nunca al reves.

No es purismo. Es lo que hace que se pueda correr un backtest sin levantar
Postgres, que los 92 tests del motor no necesiten base de datos, y que la
logica financiera no se contamine de detalles de transporte. Una direccion
invertida no rompe nada el dia que se escribe: rompe el dia que alguien quiere
correr el motor en un portatil sin Docker.

docs/ARCHITECTURE.md §4.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NUCLEO = RAIZ / "core" / "estrategia"

#: Lo que el nucleo no puede nombrar jamas.
PROHIBIDOS_EN_NUCLEO = {
    "backend",
    "workers",
    "ml",
    "fastapi",
    "sqlalchemy",
    "alembic",
    "psycopg",
    "redis",
    "streamlit",
}


def _modulos_importados(fichero: Path) -> set[str]:
    """Nombres de primer nivel importados de forma absoluta."""
    arbol = ast.parse(fichero.read_text(encoding="utf-8"))
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres.update(a.name.split(".")[0] for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            nombres.add(nodo.module.split(".")[0])
    return nombres


def test_el_nucleo_no_importa_la_plataforma():
    problemas = []
    for fichero in sorted(NUCLEO.rglob("*.py")):
        for nombre in _modulos_importados(fichero) & PROHIBIDOS_EN_NUCLEO:
            problemas.append(f"{fichero.relative_to(RAIZ)} importa {nombre}")
    assert not problemas, "el nucleo no puede depender de la plataforma:\n" + "\n".join(problemas)


def test_el_nucleo_se_importa_sin_base_de_datos():
    """Importar el motor no puede exigir Postgres ni variables de entorno."""
    import estrategia.backtest  # noqa: F401
    import estrategia.config as config_mod
    import estrategia.fundamental  # noqa: F401
    import estrategia.indicadores  # noqa: F401

    cfg = config_mod.cargar()
    assert cfg.reglas.universo.mercados


def test_la_plataforma_si_puede_importar_el_nucleo():
    """La direccion permitida, para que el test no pase por estar todo vacio."""
    ficheros = list((RAIZ / "backend").rglob("*.py"))
    assert ficheros, "no hay backend que comprobar"
    usa_nucleo = any("estrategia" in _modulos_importados(f) for f in ficheros)
    assert usa_nucleo, "el backend deberia apoyarse en el nucleo, no reimplementarlo"
