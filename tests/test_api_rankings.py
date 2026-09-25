"""Rankings (§32) y screener (§31).

Las dos propiedades que de verdad se prueban aqui:

1. **Una empresa, una fila** (D-12). Si el ADR y la accion local aparecen los
   dos, quien construya una cartera con ese top se concentra sin darse cuenta.
2. **La lista blanca de campos del screener.** El cliente manda nombres de
   campo; resolverlos con `getattr` convertiria una peticion en acceso
   arbitrario al esquema.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from backend.db.models import Exchange, Market, ModelVersion, Price, Score, Security
from backend.db.models.enums import AssetType, Cohort, ModelKind
from backend.db.session import sesion as dependencia_sesion
from backend.main import crear_app

HOY = dt.date(2026, 4, 15)
HACE_UN_MES = dt.date(2026, 3, 16)
VERSION = "0.0.9-rank"


def _valor(
    s,
    ticker,
    nombre,
    mercado,
    exchange,
    divisa,
    company_id,
    principal,
    sector="tecnologia",
    tipo=AssetType.COMMON_STOCK,
):
    v = Security(
        ticker=ticker,
        name=nombre,
        market_id=mercado,
        exchange_id=exchange,
        currency_code=divisa,
        asset_type=tipo.value,
        sector=sector,
        company_id=company_id,
        is_primary_listing=principal,
        active=True,
    )
    s.add(v)
    s.flush()
    return v


def _puntuar(s, valor, mv, fecha, overall, **extra):
    s.add(
        Score(
            security_id=valor.id,
            date=fecha,
            model_version_id=mv.id,
            overall=overall,
            cohort_used=Cohort.MARKET.value,
            n_cohort=10,
            available_pillars=["fundamental", "technical", "risk"],
            **extra,
        )
    )


def _precio(s, valor, fecha, volumen):
    s.add(
        Price(
            security_id=valor.id,
            date=fecha,
            open=10,
            high=10,
            low=10,
            close=10,
            close_raw=10,
            volume=volumen,
            source="prueba-rank",
            downloaded_at=fecha,
        )
    )


@pytest.fixture
def entorno(bd_con_referencia):
    """Universo minimo: una empresa con dos lineas y otras dos empresas."""
    app = crear_app()
    with sa.orm.Session(bd_con_referencia) as s:
        mercado = s.scalars(sa.select(Market).limit(1)).first()
        exchange = s.scalars(
            sa.select(Exchange).where(Exchange.market_id == mercado.id).limit(1)
        ).first()
        mv = ModelVersion(name="equilibrado", version=VERSION, kind=ModelKind.RULES.value)
        s.add(mv)
        s.flush()

        # Misma empresa, dos lineas de cotizacion. La local es la principal.
        local = _valor(
            s,
            "ZZLOCAL",
            "Empresa Doble (local)",
            mercado.id,
            exchange.id,
            mercado.currency_code,
            "EMPRESA-DOBLE",
            True,
        )
        adr = _valor(
            s,
            "ZZADR",
            "Empresa Doble (ADR)",
            mercado.id,
            exchange.id,
            mercado.currency_code,
            "EMPRESA-DOBLE",
            False,
            tipo=AssetType.ADR,
        )
        otra = _valor(
            s,
            "ZZOTRA",
            "Otra Empresa",
            mercado.id,
            exchange.id,
            mercado.currency_code,
            "OTRA",
            True,
            sector="banca",
        )
        tercera = _valor(
            s,
            "ZZTRES",
            "Tercera Empresa",
            mercado.id,
            exchange.id,
            mercado.currency_code,
            "TERCERA",
            True,
            sector="banca",
        )

        _puntuar(s, local, mv, HOY, 95, fundamental=90, risk=40, momentum=80, quality=70)
        _puntuar(s, adr, mv, HOY, 97, fundamental=96, risk=44, momentum=82, quality=72)
        _puntuar(s, otra, mv, HOY, 60, fundamental=55, risk=85, momentum=20, quality=30)
        _puntuar(s, tercera, mv, HOY, 30, fundamental=20, risk=75, momentum=10, quality=25)

        # Foto de hace un mes, para los rankings de variacion.
        _puntuar(s, local, mv, HACE_UN_MES, 90)
        _puntuar(s, otra, mv, HACE_UN_MES, 80)
        _puntuar(s, tercera, mv, HACE_UN_MES, 25)

        for v, vol in ((local, 1_000_000), (adr, 10), (otra, 500), (tercera, 500)):
            _precio(s, v, HOY, vol)
        s.commit()
        mercado_id = mercado.id

    def sesion_de_prueba():
        with sa.orm.Session(bd_con_referencia) as s:
            yield s

    app.dependency_overrides[dependencia_sesion] = sesion_de_prueba
    yield TestClient(app), mercado_id

    with sa.orm.Session(bd_con_referencia) as s:
        s.execute(sa.text("DELETE FROM price WHERE source = 'prueba-rank'"))
        s.execute(
            sa.text(
                "DELETE FROM score WHERE model_version_id IN "
                "(SELECT id FROM model_version WHERE version = :v)"
            ),
            {"v": VERSION},
        )
        s.execute(sa.text("DELETE FROM model_version WHERE version = :v"), {"v": VERSION})
        s.execute(sa.text("DELETE FROM security WHERE ticker LIKE 'ZZ%'"))
        s.commit()


def _ranking(cliente, **params):
    params.setdefault("fecha", HOY.isoformat())
    return cliente.get("/api/v1/rankings", params=params).json()


# --- D-12: una empresa, una fila -------------------------------------------


def test_el_adr_y_la_accion_local_no_aparecen_los_dos(entorno):
    """El duplicado que concentra una cartera sin que nadie lo vea."""
    cliente, mercado = entorno
    puestos = _ranking(cliente, mercado=mercado, n=50)["puestos"]
    tickers = [p["ticker"] for p in puestos]

    assert "ZZLOCAL" in tickers
    assert "ZZADR" not in tickers, "la misma empresa dos veces en el ranking"


def test_se_conserva_la_linea_principal_y_no_la_de_mas_score(entorno):
    """El ADR tiene MAS score que la linea local, a proposito.

    Asi las dos reglas posibles dan respuestas distintas: quedarse con el mejor
    numero elegiria el ADR; quedarse con la linea principal, que es lo que dice
    D-12, elige la local. Comprobado mutando el codigo: con la regla del score
    este test falla.

    Importa porque el ADR y la accion local no son intercambiables —distinta
    divisa, distinto huso, distinta liquidez— y la cartera se construye sobre la
    que de verdad se puede operar.
    """
    cliente, mercado = entorno
    puestos = _ranking(cliente, mercado=mercado, n=50)["puestos"]
    fila = next(p for p in puestos if p["ticker"] in {"ZZLOCAL", "ZZADR"})

    assert fila["ticker"] == "ZZLOCAL"


def test_se_puede_pedir_sin_deduplicar_para_auditar(entorno):
    cliente, _ = entorno
    r = cliente.post(
        "/api/v1/screener",
        json={"fecha": HOY.isoformat(), "deduplicar": False, "n": 100},
    ).json()
    tickers = {f["ticker"] for f in r["filas"]}

    assert {"ZZLOCAL", "ZZADR"} <= tickers


# --- Los diez rankings -----------------------------------------------------


def test_el_catalogo_trae_las_diez_vistas(entorno):
    cliente, _ = entorno
    catalogo = cliente.get("/api/v1/rankings/catalogo").json()
    assert len(catalogo) == 10
    assert "mas_mejorado" in catalogo and "mayor_caida" in catalogo


def test_mejor_y_peor_score_son_ordenes_opuestos(entorno):
    cliente, mercado = entorno
    mejor = _ranking(cliente, tipo="mejor_score", mercado=mercado, n=10)["puestos"]
    peor = _ranking(cliente, tipo="peor_score", mercado=mercado, n=10)["puestos"]

    assert mejor[0]["ticker"] == "ZZLOCAL"
    assert peor[0]["ticker"] == "ZZTRES"


def test_menor_riesgo_ordena_por_el_pilar_y_no_por_el_score(entorno):
    """`ZZOTRA` tiene peor score que `ZZLOCAL` pero mejor pilar de riesgo."""
    cliente, mercado = entorno
    puestos = _ranking(cliente, tipo="menor_riesgo", mercado=mercado, n=10)["puestos"]

    assert puestos[0]["ticker"] == "ZZOTRA"


def test_mas_mejorado_mide_la_variacion_y_no_el_nivel(entorno):
    """`ZZTRES` es el peor del universo y aun asi el que mas ha mejorado.

    Es lo que separa "most improved" de "mejor score": si el ranking devolviera
    el de mas score, este test caeria.
    """
    cliente, mercado = entorno
    puestos = _ranking(cliente, tipo="mas_mejorado", mercado=mercado, n=10)["puestos"]

    assert puestos[0]["ticker"] == "ZZTRES"
    assert puestos[0]["valor"] == 5.0
    assert puestos[0]["anterior"] == 25.0


def test_mayor_caida_encuentra_al_que_se_desploma(entorno):
    cliente, mercado = entorno
    puestos = _ranking(cliente, tipo="mayor_caida", mercado=mercado, n=10)["puestos"]

    assert puestos[0]["ticker"] == "ZZOTRA"
    assert puestos[0]["valor"] == -20.0


def test_sin_foto_anterior_no_se_inventa_una_variacion(entorno):
    """Devolver el ranking por score seria responder otra pregunta sin avisar."""
    cliente, mercado = entorno
    r = _ranking(cliente, tipo="mas_mejorado", mercado=mercado, fecha=HACE_UN_MES.isoformat())

    assert r["puestos"] == []


# --- El corte temporal -----------------------------------------------------


def test_la_respuesta_dice_de_que_dia_son_los_datos(entorno):
    """Un ranking de hace tres semanas se lee como si fuera de hoy sin esto."""
    cliente, mercado = entorno
    r = _ranking(cliente, mercado=mercado, fecha="2026-05-01")

    assert r["fecha"] == "2026-05-01"
    assert r["fecha_datos"] == HOY.isoformat()


def test_no_se_usan_scores_posteriores_al_corte(entorno):
    cliente, mercado = entorno
    r = _ranking(cliente, mercado=mercado, fecha=HACE_UN_MES.isoformat())

    assert r["fecha_datos"] == HACE_UN_MES.isoformat()


# --- Screener --------------------------------------------------------------


def test_filtros_combinados(entorno):
    cliente, mercado = entorno
    r = cliente.post(
        "/api/v1/screener",
        json={
            "fecha": HOY.isoformat(),
            "filtros": [
                {"campo": "overall", "operador": "gte", "valor": 50},
                {"campo": "sector", "operador": "eq", "valor": "banca"},
            ],
        },
    ).json()

    assert [f["ticker"] for f in r["filas"]] == ["ZZOTRA"]


def test_between_e_in(entorno):
    cliente, mercado = entorno
    entre = cliente.post(
        "/api/v1/screener",
        json={
            "fecha": HOY.isoformat(),
            "filtros": [{"campo": "overall", "operador": "between", "valor": [29, 61]}],
        },
    ).json()
    assert {f["ticker"] for f in entre["filas"]} == {"ZZOTRA", "ZZTRES"}

    dentro = cliente.post(
        "/api/v1/screener",
        json={
            "fecha": HOY.isoformat(),
            "filtros": [{"campo": "sector", "operador": "in", "valor": ["banca"]}],
        },
    ).json()
    assert {f["ticker"] for f in dentro["filas"]} == {"ZZOTRA", "ZZTRES"}


def test_el_total_distingue_cuantos_hay_de_cuantos_se_ensenan(entorno):
    """ "20 resultados" no distingue "solo hay 20" de "hay 400"."""
    cliente, _ = entorno
    r = cliente.post("/api/v1/screener", json={"fecha": HOY.isoformat(), "n": 1}).json()

    assert r["n"] == 1
    assert r["total"] >= 3


# --- La lista blanca -------------------------------------------------------


def test_un_campo_que_no_esta_en_la_lista_blanca_se_rechaza(entorno):
    """Resolver el campo con `getattr` daria acceso a cualquier columna."""
    cliente, _ = entorno
    r = cliente.post(
        "/api/v1/screener",
        json={"filtros": [{"campo": "created_at", "operador": "gte", "valor": "2020-01-01"}]},
    )

    assert r.status_code == 400
    assert "desconocido" in r.json()["detail"]


def test_no_se_puede_ordenar_por_un_campo_arbitrario(entorno):
    cliente, _ = entorno
    r = cliente.post("/api/v1/screener", json={"orden": "id"})

    assert r.status_code == 400


@pytest.mark.parametrize(
    "malo",
    [
        {"campo": "overall", "operador": "between", "valor": 5},
        {"campo": "overall", "operador": "between", "valor": [1, 2, 3]},
        {"campo": "sector", "operador": "in", "valor": []},
    ],
)
def test_un_operador_mal_usado_da_400_y_no_un_500(entorno, malo):
    """Un 500 aqui seria una traza en los logs y un usuario sin saber que hizo mal."""
    cliente, _ = entorno
    r = cliente.post("/api/v1/screener", json={"filtros": [malo]})

    assert r.status_code == 400


def test_los_campos_disponibles_se_publican(entorno):
    cliente, _ = entorno
    campos = cliente.get("/api/v1/screener/campos").json()

    assert "overall" in campos["numericos"]
    assert "sector" in campos["texto"]
    assert "between" in campos["operadores"]
