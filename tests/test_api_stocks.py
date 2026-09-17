"""`GET /stocks/{ticker}/analysis`: el endpoint vertebral de §27.

Dos propiedades por encima del resto:

1. **Un bloque no disponible se declara, no se rellena.** Un `null` suelto no
   distingue "no lo sabemos" de "vale cero", y esa diferencia decide si alguien
   puede fiarse del numero.
2. **El corte temporal se respeta bloque a bloque.** Es el sitio exacto donde
   RT-1/RT-2 avisan de que el sesgo de anticipacion se reintroduce al anadir la
   capa SaaS: un endpoint que lee la tabla de precios sin corte devuelve el
   futuro sin que nadie lo note.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from backend.db.models import ModelVersion, Price, Score, Security, Signal
from backend.db.models.enums import AssetType, Cohort, ModelKind, SignalType
from backend.db.session import sesion as dependencia_sesion
from backend.main import crear_app

AYER = dt.date(2026, 3, 10)
HOY = dt.date(2026, 3, 11)
MANANA = dt.date(2026, 3, 12)


@pytest.fixture
def entorno(bd_con_referencia):
    """Un valor con precios a ambos lados del corte, score y senal."""
    app = crear_app()
    with sa.orm.Session(bd_con_referencia) as s:
        valor = s.scalars(
            sa.select(Security)
            .where(Security.active.is_(True), Security.asset_type != AssetType.INDEX.value)
            .limit(1)
        ).first()
        assert valor is not None

        mv = ModelVersion(name="equilibrado", version="0.0.9-api", kind=ModelKind.RULES.value)
        s.add(mv)
        s.flush()

        for fecha, cierre in ((AYER, 100.0), (HOY, 110.0), (MANANA, 999.0)):
            s.add(
                Price(
                    security_id=valor.id,
                    date=fecha,
                    open=cierre,
                    high=cierre,
                    low=cierre,
                    close=cierre,
                    close_raw=cierre,
                    volume=1000,
                    source="prueba",
                    # Obligatorio: no es auditoria, es de que descarga salio el
                    # dato. Yahoo revisa el pasado hacia atras, asi que dos
                    # descargas del mismo dia bursatil pueden no coincidir.
                    downloaded_at=HOY,
                )
            )
        s.add(
            Score(
                security_id=valor.id,
                date=HOY,
                model_version_id=mv.id,
                overall=88,
                fundamental=90,
                technical=75,
                risk=20,
                # `sentiment` se deja a None: es el pilar que tiene que salir
                # declarado como no disponible en lugar de rellenado.
                growth=85,
                valuation=15,
                cohort_used=Cohort.MARKET.value,
                n_cohort=30,
                available_pillars=["fundamental", "technical", "risk"],
            )
        )
        s.add(
            Signal(
                security_id=valor.id,
                date=HOY,
                model_version_id=mv.id,
                signal=SignalType.BUY.value,
                reason="score_alto",
                reason_detail={"score": 88.0},
                market_regime="alcista",
                author="prueba",
                methodology_ref="docs/ARCHITECTURE.md#9-motor-de-senales",
            )
        )
        s.commit()
        ticker = valor.ticker

    def sesion_de_prueba():
        with sa.orm.Session(bd_con_referencia) as s:
            yield s

    app.dependency_overrides[dependencia_sesion] = sesion_de_prueba
    yield TestClient(app), ticker

    # Se limpia lo escrito: esta fixture SI confirma, asi que tiene que
    # recoger detras de si o le cambia el suelo a los tests que vengan.
    with sa.orm.Session(bd_con_referencia) as s:
        s.execute(sa.text("DELETE FROM signal WHERE author = 'prueba'"))
        s.execute(sa.text("DELETE FROM price WHERE source = 'prueba'"))
        s.execute(
            sa.text(
                "DELETE FROM score WHERE model_version_id IN "
                "(SELECT id FROM model_version WHERE version = '0.0.9-api')"
            )
        )
        s.execute(sa.text("DELETE FROM model_version WHERE version = '0.0.9-api'"))
        s.commit()


# --- El corte temporal -----------------------------------------------------


def test_el_corte_no_deja_pasar_un_precio_posterior(entorno):
    """La prueba de RT-2, y la razon de que el endpoint acepte `fecha`.

    Hay un precio de 999 el dia siguiente al corte. Si aparece, el endpoint
    esta sirviendo el futuro y cualquier analisis hecho con el es mentira.
    """
    cliente, ticker = entorno
    r = cliente.get(f"/api/v1/stocks/{ticker}/analysis", params={"fecha": HOY.isoformat()})

    assert r.status_code == 200
    precio = r.json()["precio"]
    assert precio["disponible"] is True
    assert precio["datos"]["cierre"] == 110.0, "tendria que ser el del dia del corte"
    assert precio["datos"]["fecha"] == HOY.isoformat()


def test_retroceder_el_corte_devuelve_lo_que_se_sabia_entonces(entorno):
    cliente, ticker = entorno
    r = cliente.get(f"/api/v1/stocks/{ticker}/analysis", params={"fecha": AYER.isoformat()})

    cuerpo = r.json()
    assert cuerpo["precio"]["datos"]["cierre"] == 100.0
    # Aquel dia todavia no habia score ni senal.
    assert cuerpo["score"]["disponible"] is False
    assert cuerpo["senal"]["disponible"] is False


# --- Lo que falta se declara, no se rellena --------------------------------


def test_un_pilar_ausente_se_declara_y_no_se_imputa(entorno):
    """El criterio de aceptacion de la fase, literal.

    Imputar la media convertiria "no lo sabemos" en "es del monton": una
    afirmacion distinta, y ademas falsa. D-8 dice que se renormaliza sobre los
    pilares disponibles, nunca que se rellene con 50.
    """
    cliente, ticker = entorno
    datos = cliente.get(
        f"/api/v1/stocks/{ticker}/analysis", params={"fecha": HOY.isoformat()}
    ).json()["score"]["datos"]

    assert datos["pilares"]["sentiment"] is None
    assert "sentiment" in datos["pilares_no_disponibles"]
    assert datos["pilares_no_disponibles"]["sentiment"], "tiene que decir por que falta"
    assert datos["pilares"]["fundamental"] == 90.0


def test_cada_bloque_ausente_explica_por_que(entorno):
    """Un bloque vacio sin motivo obliga a adivinar si es un hueco o un fallo."""
    cliente, ticker = entorno
    cuerpo = cliente.get(
        f"/api/v1/stocks/{ticker}/analysis", params={"fecha": AYER.isoformat()}
    ).json()

    for nombre in ("fundamental", "tecnico", "score", "senal", "prediccion"):
        bloque = cuerpo[nombre]
        if not bloque["disponible"]:
            assert bloque["motivo"], f"el bloque {nombre} no dice por que falta"
            assert bloque["datos"] is None, f"el bloque {nombre} trae datos sin estar disponible"


def test_la_prediccion_se_declara_ausente_en_lugar_de_omitirse(entorno):
    """D-7 aplaza el modelo estadistico. Quien consume la API tiene que poder
    ver que ese bloque existe y por que esta vacio, no encontrarse un hueco."""
    cliente, ticker = entorno
    prediccion = cliente.get(f"/api/v1/stocks/{ticker}/analysis").json()["prediccion"]

    assert prediccion["disponible"] is False
    assert "D-7" in prediccion["motivo"]


# --- Frescura y explicabilidad ---------------------------------------------


def test_cada_bloque_disponible_dice_de_cuando_es(entorno):
    """Un dato de hace catorce meses y uno de ayer se leen igual sin la fecha."""
    cliente, ticker = entorno
    cuerpo = cliente.get(
        f"/api/v1/stocks/{ticker}/analysis", params={"fecha": MANANA.isoformat()}
    ).json()

    frescura = cuerpo["precio"]["frescura"]
    assert frescura["as_of"] == MANANA.isoformat()
    assert frescura["dias"] == 0

    otra = cliente.get(f"/api/v1/stocks/{ticker}/analysis", params={"fecha": "2026-03-20"}).json()[
        "precio"
    ]["frescura"]
    assert otra["dias"] == 8, "ocho dias desde el ultimo precio conocido"


def test_la_explicacion_separa_lo_que_sostiene_de_lo_que_lastra(entorno):
    cliente, ticker = entorno
    exp = cliente.get(
        f"/api/v1/stocks/{ticker}/analysis", params={"fecha": HOY.isoformat()}
    ).json()["explicacion"]["datos"]

    a_favor = {f["nombre"] for f in exp["a_favor"]}
    en_contra = {f["nombre"] for f in exp["en_contra"]}

    assert "fundamental" in a_favor
    assert {"risk", "valuation"} <= en_contra
    assert not (a_favor & en_contra), "un factor no puede estar en las dos listas"


def test_un_cambio_que_no_se_puede_calcular_se_declara(entorno):
    """Sin score de hace 30 dias, el cambio no es cero: es incomparable.

    Devolver 0 diria "no se movio", que es una afirmacion sobre datos que no
    existen.
    """
    cliente, ticker = entorno
    exp = cliente.get(
        f"/api/v1/stocks/{ticker}/analysis", params={"fecha": HOY.isoformat()}
    ).json()["explicacion"]["datos"]

    assert exp["cambio_30d"] == {}
    assert "overall" in exp["cambio_no_comparable"]


# --- Basicos ---------------------------------------------------------------


def test_un_ticker_que_no_existe_da_404(entorno):
    cliente, _ = entorno
    assert cliente.get("/api/v1/stocks/NOEXISTE/analysis").status_code == 404


# --- Busqueda (FASE 17: "buscar un valor" sin tocar la API a mano) ---------


def test_la_busqueda_encuentra_por_ticker_y_por_nombre(entorno, bd_con_referencia):
    cliente, ticker = entorno
    with sa.orm.Session(bd_con_referencia) as s:
        nombre = s.scalars(sa.select(Security.name).where(Security.ticker == ticker)).first()

    por_ticker = cliente.get("/api/v1/stocks", params={"q": ticker}).json()
    assert any(f["ticker"] == ticker for f in por_ticker)

    por_nombre = cliente.get("/api/v1/stocks", params={"q": nombre.split()[0]}).json()
    assert any(f["ticker"] == ticker for f in por_nombre)


def test_la_busqueda_no_devuelve_indices(entorno, bd_con_referencia):
    """Un indice no se compra, asi que no pinta nada en un buscador de valores."""
    cliente, _ = entorno
    filas = cliente.get("/api/v1/stocks", params={"q": "a", "n": 50}).json()
    assert filas, "la busqueda tiene que devolver algo"
    with sa.orm.Session(bd_con_referencia) as s:
        indices = set(
            s.scalars(
                sa.select(Security.ticker).where(Security.asset_type == AssetType.INDEX.value)
            ).all()
        )
    assert not ({f["ticker"] for f in filas} & indices)


def test_el_que_empieza_por_lo_buscado_va_antes(entorno):
    """Quien escribe «ACS» quiere ACS.MC, no la tercera empresa cuyo nombre lo
    lleva dentro."""
    cliente, _ = entorno
    filas = cliente.get("/api/v1/stocks", params={"q": "ACS"}).json()
    assert filas
    assert filas[0]["ticker"].upper().startswith("ACS")


def test_un_comodin_escrito_por_el_usuario_se_busca_como_caracter(entorno):
    """Sin escapar, un `%` convierte la busqueda en «todo» y devuelve el universo
    entero como si hubiera coincidido con algo."""
    cliente, _ = entorno
    assert cliente.get("/api/v1/stocks", params={"q": "%"}).json() == []
    assert cliente.get("/api/v1/stocks", params={"q": "_"}).json() == []
