"""Registro de fuentes disponibles.

Antes habia un `if/else` en el CLI que conocia los nombres de las fuentes. Con
dos ya empieza a molestar y con cinco es insostenible, asi que aqui hay un mapa
de nombre a constructor: **anadir una fuente es registrarla**, y ni el CLI ni el
panel ni el motor tienen que enterarse.

Los constructores importan de forma perezosa a proposito. Importar yfinance
tarda casi un segundo, y el adaptador de una fuente que necesita una libreria que
no esta instalada no debe impedir arrancar la app entera para usar otra.
"""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from ..errores import ErrorConfiguracion

if TYPE_CHECKING:  # pragma: no cover
    from ..config import Config
    from .proveedor import Fuente

_FUENTES: dict[str, Callable[["Config"], "Fuente"]] = {}


def registrar(nombre: str, constructor: Callable[["Config"], "Fuente"]) -> None:
    """Da de alta una fuente con su constructor."""
    _FUENTES[nombre] = constructor


def disponibles() -> list[str]:
    return sorted(_FUENTES)


def crear(nombre: str, cfg: "Config") -> "Fuente":
    """Construye una fuente por su nombre."""
    try:
        constructor = _FUENTES[nombre]
    except KeyError as exc:
        raise ErrorConfiguracion(
            f"fuente de datos desconocida: {nombre!r}. "
            f"Disponibles: {', '.join(disponibles())}"
        ) from exc
    return constructor(cfg)


# -- Fuentes de serie --------------------------------------------------------


def _sintetico(cfg: "Config") -> "Fuente":
    from .sintetico import ProveedorSintetico

    return ProveedorSintetico(cfg)


def _yfinance(cfg: "Config") -> "Fuente":
    from .yfinance_proveedor import ProveedorYFinance

    return ProveedorYFinance(cfg)


def _eodhd(cfg: "Config") -> "Fuente":
    from .eodhd_proveedor import ProveedorEODHD

    return ProveedorEODHD(cfg)


def _sec(cfg: "Config") -> "Fuente":
    from .sec_proveedor import ProveedorSEC

    return ProveedorSEC(cfg)


def _bce(cfg: "Config") -> "Fuente":
    from .bce_proveedor import ProveedorBCE

    return ProveedorBCE(cfg)


def _cvm(cfg: "Config") -> "Fuente":
    from .cvm_proveedor import ProveedorCVM

    return ProveedorCVM(cfg)


def _stooq(cfg: "Config") -> "Fuente":
    from .stooq_proveedor import ProveedorStooq

    return ProveedorStooq(cfg)


registrar("sintetico", _sintetico)
registrar("yfinance", _yfinance)
registrar("eodhd", _eodhd)
registrar("sec", _sec)
registrar("bce", _bce)
registrar("stooq", _stooq)
registrar("cvm", _cvm)
