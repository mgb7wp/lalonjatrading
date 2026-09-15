"""Fixtures compartidas.

Los tests no tocan la red ni dependen de datos descargados: todo sale del
proveedor sintetico, que es determinista. Un test que fallara solo los martes
porque el mercado hizo algo raro no serviria para nada.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from estrategia import config as config_mod
from estrategia.datos.almacen import Instantanea
from estrategia.datos.sintetico import ProveedorSintetico

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
