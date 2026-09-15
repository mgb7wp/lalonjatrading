"""Tests de la API.

No tocan Postgres: /health esta escrito para poder informar de que la base de
datos no responde, asi que aqui se ejercita justamente ese camino.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import crear_app


@pytest.fixture(scope="module")
def cliente():
    return TestClient(crear_app())


def test_health_responde_aunque_no_haya_base_de_datos(cliente):
    r = cliente.get("/api/v1/health")
    assert r.status_code == 200, "health no puede caerse con sus dependencias"
    cuerpo = r.json()
    assert cuerpo["estado"] in {"ok", "degradado", "caido"}
    nombres = {d["nombre"] for d in cuerpo["dependencias"]}
    assert {"postgres", "core"} <= nombres


def test_health_dice_cual_es_la_dependencia_caida(cliente):
    """Un health que solo dice 'mal' no sirve para arreglar nada."""
    deps = cliente.get("/api/v1/health").json()["dependencias"]
    for d in deps:
        if d["estado"] == "caido":
            assert d["detalle"], f"{d['nombre']} esta caido sin decir por que"


def test_el_nucleo_esta_sano_en_el_entorno_de_test(cliente):
    deps = {d["nombre"]: d for d in cliente.get("/api/v1/health").json()["dependencias"]}
    assert deps["core"]["estado"] == "ok", deps["core"]["detalle"]


def test_health_data_declara_que_todavia_no_existe(cliente):
    """Mejor un 501 honesto que un verde que no significa nada."""
    assert cliente.get("/api/v1/health/data").status_code == 501


def test_los_mercados_salen_de_la_configuracion(cliente):
    r = cliente.get("/api/v1/markets")
    assert r.status_code == 200
    mercados = {m["id"]: m for m in r.json()}
    # Los cuatro del encargo, mas Alemania que ya estaba resuelta (decision D-2).
    assert {"us", "es", "br", "in"} <= set(mercados)
    assert mercados["br"]["currency"] == "BRL"
    assert mercados["in"]["trading_calendar"] == "XBOM"
    assert all(m["securities"] > 0 for m in mercados.values())


def test_un_mercado_desconocido_da_404(cliente):
    assert cliente.get("/api/v1/markets/xx").status_code == 404


def test_el_openapi_se_genera(cliente):
    """Si el esquema no se genera, /docs esta roto y no se nota hasta produccion."""
    esquema = cliente.get("/openapi.json").json()
    assert "/api/v1/markets" in esquema["paths"]
