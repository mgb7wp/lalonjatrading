"""Tests de la API.

Los de `/health` corren sin Postgres a proposito: ese endpoint esta escrito para
poder informar de que la base de datos no responde, asi que aqui se ejercita
justamente ese camino.

Los de `/markets` si necesitan base de datos desde la FASE 2, porque los
mercados salen de la tabla `market` y no de la configuracion en caliente.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from backend.db.session import sesion as dependencia_sesion
from backend.main import crear_app


@pytest.fixture(scope="module")
def cliente():
    return TestClient(crear_app())


@pytest.fixture
def cliente_bd(bd_con_referencia):
    """Cliente cuya sesion apunta a la base de datos de pruebas.

    Se sustituye la dependencia en lugar de manipular variables de entorno: es
    el mecanismo que ofrece FastAPI para esto y no deja estado global pegado
    entre modulos de test.
    """
    app = crear_app()

    def sesion_de_prueba():
        with sa.orm.Session(bd_con_referencia) as s:
            yield s

    app.dependency_overrides[dependencia_sesion] = sesion_de_prueba
    with TestClient(app) as c:
        yield c


# --- salud -----------------------------------------------------------------


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


def test_health_data_informa_de_frescura_y_cobertura(cliente_bd):
    """Que datos hay, de cuando, de que fuente y con que huecos (§46)."""
    r = cliente_bd.get("/api/v1/health/data")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] in {"ok", "degradado", "caido"}
    assert "datasets" in cuerpo and "stale" in cuerpo


def test_sin_datos_cargados_health_data_no_dice_que_todo_va_bien(cliente_bd):
    """Una base de datos vacia no es un sistema sano.

    Es uno que aun no ha ingerido nada, y devolver verde ahi es el tipo de
    verde que hace que nadie mire. La fixture carga la referencia pero no
    ingiere series, asi que este es exactamente ese caso.
    """
    cuerpo = cliente_bd.get("/api/v1/health/data").json()
    if not cuerpo["datasets"]:
        assert cuerpo["estado"] == "caido"


def test_el_openapi_se_genera(cliente):
    """Si el esquema no se genera, /docs esta roto y no se nota hasta produccion."""
    esquema = cliente.get("/openapi.json").json()
    assert "/api/v1/markets" in esquema["paths"]


# --- mercados --------------------------------------------------------------


def test_los_mercados_salen_de_la_base_de_datos(cliente_bd):
    r = cliente_bd.get("/api/v1/markets")
    assert r.status_code == 200
    mercados = {m["id"]: m for m in r.json()}
    # Los cuatro del encargo, mas Alemania que ya estaba resuelta (decision D-2).
    assert {"us", "es", "br", "in"} <= set(mercados)
    assert mercados["br"]["currency"] == "BRL"
    assert mercados["in"]["trading_calendar"] == "XBOM"
    assert mercados["in"]["timezone"] == "Asia/Kolkata"
    assert all(m["securities"] > 0 for m in mercados.values())


def test_el_endpoint_declara_si_el_benchmark_lleva_dividendos(cliente_bd):
    """Decision D-5: es lo que decide si el target de un modelo esta sesgado.

    Hoy los cinco son indices de precio y el endpoint lo dice. Es un hecho
    incomodo publicado, no un problema resuelto.
    """
    mercados = cliente_bd.get("/api/v1/markets").json()
    assert all(m["benchmark_is_total_return"] is False for m in mercados)
    assert all(m["benchmark"] for m in mercados)


def test_un_mercado_concreto(cliente_bd):
    m = cliente_bd.get("/api/v1/markets/es").json()
    assert m["name"] == "España"
    assert m["country_code"] == "ES"
    assert m["trading_calendar"] == "XMAD"


def test_un_mercado_desconocido_da_404(cliente_bd):
    assert cliente_bd.get("/api/v1/markets/xx").status_code == 404
