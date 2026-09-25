"""Listas de seguimiento (FASE 14, §35).

Lo que se comprueba no es que se pueda anadir un ticker —eso es lo facil— sino
las propiedades que se rompen en silencio:

- que una variacion que no se puede calcular salga `None` **con su motivo** y no
  un cero, porque un cero afirma "no se movio";
- que la probabilidad de §35 se declare bloqueada por D-7 en lugar de omitirse;
- que la vista NO haga una consulta por valor, que es lo que la vuelve inservible
  el dia que una lista tiene doscientos;
- que aqui NO se deduplique, al reves que en los rankings;
- que la lista de otro no se pueda ni confirmar que existe.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from backend.db.models import ModelVersion, Price, Score, Security, Signal
from backend.db.models.enums import Cohort, ModelKind, SignalType
from backend.db.session import sesion as dependencia_sesion
from backend.main import crear_app

CONTRASENA = "una-contrasena-larga-de-prueba"
CORTE = dt.date(2025, 3, 31)
#: Justo antes del corte menos 30 dias, para que sea la foto "anterior".
ANTES = CORTE - dt.timedelta(days=35)

D = Decimal


@pytest.fixture
def cliente(bd_con_referencia, monkeypatch):
    """Cuatro valores con distinta combinacion de lo que se sabe de ellos.

    - AAPL:    score ahora y antes, precio ahora y antes, senal  -> fila completa
    - ACS.MC:  score solo ahora, precio solo ahora               -> sin variaciones
    - AMS.MC:  score que BAJA de 80 a 50, precio                 -> variacion negativa
    - AENA.MC: precio, pero sin score ni senal                   -> sin puntuar
    - ACX.MC:  nada                                              -> todo declarado

    AMS.MC existe por el test de orden: con solo scores positivos, tratar un
    `None` como cero da el mismo orden que tratarlo como ausente, y el test no
    distinguiria una implementacion de la otra. Con una variacion NEGATIVA si.
    """
    import backend.api.v1.auth as auth
    import backend.limites as limites

    contadores: dict[str, int] = {}
    revocados: dict[str, float] = {}

    def contar(clave: str, ventana: int) -> int:
        cubo = f"{clave}:{int(dt.datetime.now(dt.UTC).timestamp()) // ventana}"
        contadores[cubo] = contadores.get(cubo, 0) + 1
        return contadores[cubo]

    monkeypatch.setattr(limites, "_contar", contar)
    monkeypatch.setattr(auth, "_revocar", lambda jti, seg: revocados.__setitem__(jti, seg))
    monkeypatch.setattr(auth, "_esta_revocado", lambda jti: jti in revocados)

    with sa.orm.Session(bd_con_referencia) as s:
        ids = dict(
            s.execute(
                sa.select(Security.ticker, Security.id).where(
                    Security.ticker.in_(["AAPL", "ACS.MC", "AMS.MC", "AENA.MC", "ACX.MC"])
                )
            ).all()
        )
        mv = ModelVersion(name="equilibrado", version="0.0.14-listas", kind=ModelKind.RULES.value)
        s.add(mv)
        s.flush()

        def precio(ticker, fecha, cierre):
            s.add(
                Price(
                    security_id=ids[ticker],
                    date=fecha,
                    open=cierre,
                    high=cierre,
                    low=cierre,
                    close=cierre,
                    close_raw=cierre,
                    volume=1000,
                    source="prueba-listas",
                    downloaded_at=fecha,
                )
            )

        def score(ticker, fecha, overall):
            s.add(
                Score(
                    security_id=ids[ticker],
                    date=fecha,
                    model_version_id=mv.id,
                    overall=D(overall),
                    cohort_used=Cohort.MARKET_SECTOR.value,
                    n_cohort=30,
                    available_pillars=4,
                )
            )

        # AAPL: sube de 60 a 75 y el precio de 100 a 120 (+20 %).
        precio("AAPL", ANTES, 100)
        precio("AAPL", CORTE, 120)
        score("AAPL", ANTES, "60")
        score("AAPL", CORTE, "75")
        s.add(
            Signal(
                security_id=ids["AAPL"],
                date=CORTE,
                model_version_id=mv.id,
                signal=SignalType.BUY.value,
                reason="score_alto",
                author="motor",
                methodology_ref="https://lalonja-trading.com/metodologia",
            )
        )
        # ACS.MC: solo la foto de hoy. Las dos variaciones tienen que salir
        # declaradas, no a cero.
        precio("ACS.MC", CORTE, 30)
        score("ACS.MC", CORTE, "40")
        # AMS.MC: se desploma de 80 a 50.
        precio("AMS.MC", ANTES, 50)
        precio("AMS.MC", CORTE, 45)
        score("AMS.MC", ANTES, "80")
        score("AMS.MC", CORTE, "50")
        # AENA.MC: precio pero sin puntuar.
        precio("AENA.MC", CORTE, 150)
        # ACX.MC: nada de nada.

        # Un precio POSTERIOR al corte, para comprobar que no se usa.
        precio("AAPL", CORTE + dt.timedelta(days=10), 999)
        s.commit()
        version_id = mv.id

    app = crear_app()

    def sesion_de_prueba():
        with sa.orm.Session(bd_con_referencia) as s:
            yield s

    app.dependency_overrides[dependencia_sesion] = sesion_de_prueba
    yield TestClient(app)

    with sa.orm.Session(bd_con_referencia) as s:
        s.execute(sa.text("DELETE FROM user_account WHERE email LIKE '%@pruebas.example.com'"))
        s.execute(sa.delete(Signal).where(Signal.model_version_id == version_id))
        s.execute(sa.delete(Score).where(Score.model_version_id == version_id))
        s.execute(sa.delete(ModelVersion).where(ModelVersion.id == version_id))
        s.execute(sa.delete(Price).where(Price.source == "prueba-listas"))
        s.commit()


def _cabeceras(cliente, correo: str) -> dict:
    r = cliente.post("/api/v1/auth/register", json={"email": correo, "contrasena": CONTRASENA})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['acceso']}"}


def _lista(cliente, cab, nombre="Seguimiento") -> int:
    r = cliente.post("/api/v1/watchlists", json={"nombre": nombre}, headers=cab)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _anadir(cliente, cab, lista, ticker, espera=201):
    r = cliente.post(f"/api/v1/watchlists/{lista}/items", json={"ticker": ticker}, headers=cab)
    assert r.status_code == espera, r.text
    return r


def _ver(cliente, cab, lista, **params) -> dict:
    params.setdefault("fecha", str(CORTE))
    r = cliente.get(f"/api/v1/watchlists/{lista}", params=params, headers=cab)
    assert r.status_code == 200, r.text
    return r.json()


def _por_ticker(datos: dict) -> dict:
    return {f["ticker"]: f for f in datos["valores"]}


# --- Las cinco columnas de §35 ---------------------------------------------


def test_la_lista_trae_score_variaciones_y_senal(cliente):
    cab = _cabeceras(cliente, "completa@pruebas.example.com")
    lista = _lista(cliente, cab)
    _anadir(cliente, cab, lista, "AAPL")

    fila = _por_ticker(_ver(cliente, cab, lista))["AAPL"]
    assert fila["score"] == 75.0
    assert fila["variacion_score"] == 15.0, "de 60 a 75"
    assert fila["precio"] == 120.0
    assert fila["variacion_precio"] == 20.0, "de 100 a 120 es un +20 %"
    assert fila["senal"] == "buy"
    assert fila["motivo_senal"] == "score_alto"


def test_una_variacion_que_no_se_puede_calcular_no_es_cero(cliente):
    """Un cero afirma «no se movió», que es una afirmación sobre datos que no
    existen. Sale `None` y con el motivo escrito al lado."""
    cab = _cabeceras(cliente, "sinprevio@pruebas.example.com")
    lista = _lista(cliente, cab)
    _anadir(cliente, cab, lista, "ACS.MC")

    fila = _por_ticker(_ver(cliente, cab, lista))["ACS.MC"]
    assert fila["score"] == 40.0, "la foto de hoy sí está"
    assert fila["variacion_score"] is None
    assert fila["variacion_score"] != 0
    assert fila["variacion_precio"] is None
    assert "variacion_score" in fila["motivos"]
    assert "variacion_precio" in fila["motivos"]


def test_un_valor_sin_puntuar_lo_dice_en_vez_de_sacar_un_cero(cliente):
    """En un percentil, un 0 significa «el peor de su cohorte». No es lo mismo
    que no tener nota, y confundirlos manda a un valor al fondo de la tabla por
    un dato que nadie ha calculado."""
    cab = _cabeceras(cliente, "sinpuntuar@pruebas.example.com")
    lista = _lista(cliente, cab)
    _anadir(cliente, cab, lista, "AENA.MC")

    fila = _por_ticker(_ver(cliente, cab, lista))["AENA.MC"]
    assert fila["score"] is None
    assert fila["precio"] == 150.0
    assert "equilibrado" in fila["motivos"]["score"]
    assert "senal" in fila["motivos"]


def test_un_valor_del_que_no_se_sabe_nada_declara_todos_sus_huecos(cliente):
    cab = _cabeceras(cliente, "vacio@pruebas.example.com")
    lista = _lista(cliente, cab)
    _anadir(cliente, cab, lista, "ACX.MC")

    fila = _por_ticker(_ver(cliente, cab, lista))["ACX.MC"]
    assert fila["score"] is None and fila["precio"] is None and fila["senal"] is None
    for clave in ("score", "precio", "senal", "probabilidad"):
        assert clave in fila["motivos"], f"falta el motivo de {clave}"


def test_la_probabilidad_se_declara_bloqueada_por_d7_y_no_se_omite(cliente):
    """La columna de §35 existe; el dato no. Quien consuma la API tiene que poder
    ver que está previsto y por qué está vacío, no encontrarse un hueco y suponer
    que se le olvidó a alguien."""
    cab = _cabeceras(cliente, "d7@pruebas.example.com")
    lista = _lista(cliente, cab)
    _anadir(cliente, cab, lista, "AAPL")

    fila = _por_ticker(_ver(cliente, cab, lista))["AAPL"]
    assert "probabilidad" in fila, "la columna tiene que estar en la respuesta"
    assert fila["probabilidad"] is None
    assert "D-7" in fila["motivos"]["probabilidad"]


# --- El corte temporal -----------------------------------------------------


def test_el_corte_temporal_deja_fuera_los_precios_posteriores(cliente):
    cab = _cabeceras(cliente, "corte@pruebas.example.com")
    lista = _lista(cliente, cab)
    _anadir(cliente, cab, lista, "AAPL")

    fila = _por_ticker(_ver(cliente, cab, lista))["AAPL"]
    assert fila["precio"] == 120.0, "el 999 del futuro no puede aparecer"
    assert fila["fecha_precio"] == str(CORTE)


# --- Rendimiento: una consulta por columna, no por valor -------------------


def test_la_vista_no_hace_una_consulta_por_valor(cliente, bd_con_referencia):
    """Con una lista PREMIUM de 250 valores, una consulta por valor son más de
    mil para pintar una pantalla. El número de consultas tiene que ser el mismo
    con tres valores que con uno."""
    cab = _cabeceras(cliente, "consultas@pruebas.example.com")
    lista = _lista(cliente, cab)

    consultas: list[str] = []

    def contar(conn, cursor, statement, params, context, muchos):  # noqa: ARG001
        consultas.append(statement)

    sa.event.listen(bd_con_referencia, "before_cursor_execute", contar)
    try:
        _anadir(cliente, cab, lista, "AAPL")
        consultas.clear()
        _ver(cliente, cab, lista)
        con_uno = len(consultas)

        _anadir(cliente, cab, lista, "ACS.MC")
        _anadir(cliente, cab, lista, "AENA.MC")
        _anadir(cliente, cab, lista, "ACX.MC")
        consultas.clear()
        _ver(cliente, cab, lista)
        con_cuatro = len(consultas)
    finally:
        sa.event.remove(bd_con_referencia, "before_cursor_execute", contar)

    assert con_cuatro == con_uno, (
        f"{con_uno} consultas con un valor y {con_cuatro} con cuatro: "
        "está consultando por valor en lugar de por columna"
    )


# --- Orden -----------------------------------------------------------------


def test_lo_que_no_tiene_dato_se_ordena_al_final_y_no_como_un_cero(cliente):
    """Con variaciones de signo distinto, tratar un `None` como cero lo coloca
    EN MEDIO de la tabla, por delante de los que de verdad han caido.

      AAPL   +15
      AMS.MC -30
      ACS.MC  sin variacion

    Correcto:      AAPL, AMS.MC, ACS.MC (el que no tiene dato, al final).
    Con None = 0:  AAPL, ACS.MC, AMS.MC (el que no tiene dato, delante del que
                   ha caido un 30, como si hubiera aguantado plano).

    La primera version de este test ordenaba por score, y como los scores nunca
    son negativos las dos implementaciones daban el mismo orden: el test pasaba
    igual con la mutacion. Se cambio despues de comprobarlo.
    """
    cab = _cabeceras(cliente, "orden@pruebas.example.com")
    lista = _lista(cliente, cab)
    for t in ("ACS.MC", "AMS.MC", "AAPL"):
        _anadir(cliente, cab, lista, t)

    datos = _ver(cliente, cab, lista, orden="variacion_score")
    tickers = [f["ticker"] for f in datos["valores"]]
    assert tickers == ["AAPL", "AMS.MC", "ACS.MC"]
    assert tickers != ["AAPL", "ACS.MC", "AMS.MC"], "un None no puede ordenar como un cero"

    por_ticker = [f["ticker"] for f in _ver(cliente, cab, lista, orden="ticker")["valores"]]
    assert por_ticker == ["AAPL", "ACS.MC", "AMS.MC"]


# --- Lo que aqui NO se hace ------------------------------------------------


def test_aqui_no_se_deduplica_por_empresa(cliente, bd_con_referencia):
    """En los rankings, dos líneas de la misma empresa son un defecto (D-12). En
    una watchlist son una elección: si alguien ha puesto las dos, quiere ver las
    dos, y quitarle una sería decidir por él."""
    with sa.orm.Session(bd_con_referencia) as s:
        # Se emparejan AAPL y ACS.MC bajo la misma empresa a proposito.
        s.execute(
            sa.update(Security)
            .where(Security.ticker.in_(["AAPL", "ACS.MC"]))
            .values(company_id="empresa-de-prueba")
        )
        s.commit()
    try:
        cab = _cabeceras(cliente, "dedup@pruebas.example.com")
        lista = _lista(cliente, cab)
        _anadir(cliente, cab, lista, "AAPL")
        _anadir(cliente, cab, lista, "ACS.MC")

        datos = _ver(cliente, cab, lista)
        assert datos["n"] == 2, "las dos líneas se quedan"
    finally:
        with sa.orm.Session(bd_con_referencia) as s:
            s.execute(
                sa.update(Security)
                .where(Security.company_id == "empresa-de-prueba")
                .values(company_id=None)
            )
            s.commit()


# --- Cupos y propiedad -----------------------------------------------------


def test_el_limite_de_listas_del_plan_es_un_409(cliente):
    cab = _cabeceras(cliente, "cupolistas@pruebas.example.com")
    _lista(cliente, cab, "Primera")
    r = cliente.post("/api/v1/watchlists", json={"nombre": "Segunda"}, headers=cab)
    assert r.status_code == 409, "FREE tiene una sola lista"


def test_el_limite_de_valores_por_lista_tambien(cliente, bd_con_referencia):
    """FREE admite 10 valores por lista. El cupo se comprueba por la misma puerta
    que el de listas y el de carteras."""
    cab = _cabeceras(cliente, "cupovalores@pruebas.example.com")
    lista = _lista(cliente, cab)
    with sa.orm.Session(bd_con_referencia) as s:
        tickers = list(
            s.scalars(
                sa.select(Security.ticker)
                .where(Security.market_id == "es", Security.asset_type != "index")
                .order_by(Security.ticker)
                .limit(11)
            ).all()
        )
    for t in tickers[:10]:
        _anadir(cliente, cab, lista, t)
    _anadir(cliente, cab, lista, tickers[10], espera=409)


def test_un_valor_repetido_se_rechaza_diciendo_cual(cliente):
    cab = _cabeceras(cliente, "repetido@pruebas.example.com")
    lista = _lista(cliente, cab)
    _anadir(cliente, cab, lista, "AAPL")
    r = _anadir(cliente, cab, lista, "AAPL", espera=409)
    assert "AAPL" in r.json()["detail"]


def test_la_lista_de_otro_no_se_puede_ni_confirmar_que_existe(cliente):
    ana = _cabeceras(cliente, "ana@pruebas.example.com")
    suya = _lista(cliente, ana)

    luis = _cabeceras(cliente, "luis@pruebas.example.com")
    for peticion in (
        cliente.get(f"/api/v1/watchlists/{suya}", headers=luis),
        cliente.delete(f"/api/v1/watchlists/{suya}", headers=luis),
        cliente.patch(f"/api/v1/watchlists/{suya}", json={"nombre": "mia"}, headers=luis),
        cliente.post(f"/api/v1/watchlists/{suya}/items", json={"ticker": "AAPL"}, headers=luis),
    ):
        assert peticion.status_code == 404, peticion.text

    assert cliente.get(f"/api/v1/watchlists/{suya}", headers=ana).status_code == 200


def test_sin_sesion_no_se_ve_ninguna_lista(cliente):
    assert cliente.get("/api/v1/watchlists").status_code == 401


def test_quitar_un_valor_que_no_esta_es_un_404(cliente):
    cab = _cabeceras(cliente, "quitar@pruebas.example.com")
    lista = _lista(cliente, cab)
    r = cliente.delete(f"/api/v1/watchlists/{lista}/items/AAPL", headers=cab)
    assert r.status_code == 404

    _anadir(cliente, cab, lista, "AAPL")
    assert cliente.delete(f"/api/v1/watchlists/{lista}/items/AAPL", headers=cab).status_code == 204
    assert _ver(cliente, cab, lista)["n"] == 0
