"""Carteras por la API (FASE 13).

El motor de derivacion ya tiene sus tests en `test_carteras.py`. Aqui se
comprueba lo que solo se rompe al montar la API encima:

- que el caso calculado a mano siga cuadrando **despues de pasar por HTTP, por
  Postgres y por la conversion de divisa leida de `fx_rate`**, que es donde se
  pierden los centimos y donde se cuela el convenio de cambio invertido;
- que corregir una transaccion antigua corrija todo lo que cuelga de ella **sin
  ningun paso de recalculo**, que es el criterio de aceptacion de la fase;
- que el corte temporal valga tambien para una cartera;
- que la cartera de otro no se pueda ni confirmar que existe;
- que el limite de plan pase por la unica puerta que hay.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from backend.db.models import FxRate, ModelVersion, Price, Score, Security
from backend.db.models.enums import Cohort, ModelKind
from backend.db.session import sesion as dependencia_sesion
from backend.main import crear_app

CONTRASENA = "una-contrasena-larga-de-prueba"
CORTE = dt.date(2024, 12, 31)
DESPUES = dt.date(2025, 6, 30)

#: Cambio EUR -> USD con el que se valora. Se elige 1,25 —y no un 1/0,93— para
#: que el inverso sea exacto: un test cuyo numero esperado depende de como
#: redondea Decimal no comprueba la cartera, comprueba a Decimal.
TASA_EUR_USD = Decimal("1.25")
FX_USD_EUR = Decimal("0.80")

D = Decimal


@pytest.fixture
def cliente(bd_con_referencia, monkeypatch):
    """Cliente con base de datos, con Redis en memoria y con datos de mercado.

    Los precios, los tipos de cambio y los scores se insertan aqui y se borran
    al terminar: un test que deja filas sueltas en una base de datos compartida
    hace fallar a otro que no tiene nada que ver, y el que lo depure empezara
    por el sitio equivocado.
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
                    Security.ticker.in_(["AAPL", "ACS.MC", "AENA.MC", "ACX.MC"])
                )
            ).all()
        )
        # ACX.MC se queda deliberadamente SIN precio, para el test de lo que
        # no se puede valorar.
        for ticker, cierre in (("AAPL", 210), ("ACS.MC", 30), ("AENA.MC", 150)):
            s.add(
                Price(
                    security_id=ids[ticker],
                    date=CORTE,
                    open=cierre,
                    high=cierre,
                    low=cierre,
                    close=cierre,
                    close_raw=cierre,
                    volume=1000,
                    source="prueba-carteras",
                    downloaded_at=CORTE,
                )
            )
        # Un precio POSTERIOR al corte, para comprobar que no se usa.
        s.add(
            Price(
                security_id=ids["AAPL"],
                date=DESPUES,
                open=999,
                high=999,
                low=999,
                close=999,
                close_raw=999,
                volume=1000,
                source="prueba-carteras",
                downloaded_at=DESPUES,
            )
        )
        s.add(
            FxRate(
                base_currency="EUR",
                quote_currency="USD",
                date=dt.date(2024, 1, 1),
                rate=TASA_EUR_USD,
                source="prueba-carteras",
            )
        )
        mv = ModelVersion(name="equilibrado", version="0.0.13-carteras", kind=ModelKind.RULES.value)
        s.add(mv)
        s.flush()
        # AAPL y ACS.MC puntuados con numeros MUY distintos: asi la media
        # ponderada y la aritmetica no coinciden y el test puede distinguirlas.
        # AENA.MC se queda sin score, para que la cobertura tenga que bajar.
        for ticker, overall in (("AAPL", "80"), ("ACS.MC", "20")):
            s.add(
                Score(
                    security_id=ids[ticker],
                    date=CORTE,
                    model_version_id=mv.id,
                    overall=D(overall),
                    cohort_used=Cohort.MARKET_SECTOR.value,
                    n_cohort=30,
                    available_pillars=4,
                )
            )
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
        s.execute(sa.delete(Score).where(Score.model_version_id == version_id))
        s.execute(sa.delete(ModelVersion).where(ModelVersion.id == version_id))
        s.execute(sa.delete(Price).where(Price.source == "prueba-carteras"))
        s.execute(sa.delete(FxRate).where(FxRate.source == "prueba-carteras"))
        s.commit()


def _cabeceras(cliente, correo: str) -> dict:
    r = cliente.post("/api/v1/auth/register", json={"email": correo, "contrasena": CONTRASENA})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['acceso']}"}


def _cartera(cliente, cab: dict, nombre: str = "Principal") -> int:
    r = cliente.post("/api/v1/portfolios", json={"nombre": nombre}, headers=cab)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mover(cliente, cab, cartera, **campos):
    r = cliente.post(f"/api/v1/portfolios/{cartera}/transactions", json=campos, headers=cab)
    assert r.status_code == 201, r.text
    return r.json()


def _caso_a_mano(cliente, cab, cartera) -> list[dict]:
    """Las tres operaciones del caso calculado a mano de `test_carteras.py`."""
    return [
        _mover(
            cliente,
            cab,
            cartera,
            ticker="AAPL",
            tipo="buy",
            cantidad="100",
            precio="150",
            comisiones="10",
            fx="0.90",
            fecha="2024-01-10",
        ),
        _mover(
            cliente,
            cab,
            cartera,
            ticker="AAPL",
            tipo="buy",
            cantidad="50",
            precio="170",
            comisiones="10",
            fx="0.92",
            fecha="2024-03-05",
        ),
        _mover(
            cliente,
            cab,
            cartera,
            ticker="AAPL",
            tipo="sell",
            cantidad="120",
            precio="200",
            comisiones="12",
            fx="0.95",
            fecha="2024-09-20",
        ),
    ]


def _valorar(cliente, cab, cartera, fecha=CORTE) -> dict:
    r = cliente.get(f"/api/v1/portfolios/{cartera}", params={"fecha": str(fecha)}, headers=cab)
    assert r.status_code == 200, r.text
    return r.json()


# --- El criterio de aceptacion --------------------------------------------


def test_el_pnl_cuadra_con_el_caso_a_mano_pasando_por_la_api(cliente):
    """Los mismos numeros de `test_carteras.py`, pero de extremo a extremo.

    Aqui el valor de mercado cambia respecto al test del motor porque el cambio
    de hoy sale de `fx_rate` (1 EUR = 1,25 USD, o sea 0,80 EUR por dolar):

      Valor hoy    = 30 * 210 * 0,80 = 5.040,00 EUR
      No realizado = 5.040,00 - 4.697,52 =   342,48 EUR
      Total        = 6.147,92 +   342,48 = 6.490,40 EUR

    El realizado NO depende del cambio de hoy: se calculo con los cambios
    congelados de cada operacion, y por eso sigue siendo 6.147,92.
    """
    cab = _cabeceras(cliente, "amano@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    _caso_a_mano(cliente, cab, cartera)

    v = _valorar(cliente, cab, cartera)
    (pos,) = v["posiciones"]

    assert D(pos["cantidad"]) == D("30")
    assert D(pos["realizado"]) == D("6147.92")
    assert D(pos["coste"]) == D("4697.52")
    assert D(pos["valor"]) == D("5040.00")
    assert D(pos["no_realizado"]) == D("342.48")
    assert D(v["totales"]["total"]) == D("6490.40")


def test_corregir_una_transaccion_antigua_corrige_todo_sin_recalcular_nada(cliente):
    """El criterio de aceptacion de la fase, por la API.

    Se corrige la compra de ENERO —la primera de tres— y tiene que cambiar el
    P&L realizado de una venta de SEPTIEMBRE, sin llamar a ningun endpoint de
    recalculo, porque no existe ninguno.

      Compra 1 corregida: (100*140 + 10) * 0,90 = 12.609,00 -> unitario 126,09
      coste vendido = 100*126,09 + 20*156,584 = 15.740,68
      realizado     = 22.788,60 - 15.740,68   =  7.047,92

    Lo que queda en cartera sale del lote 2 y no se toca: 4.697,52.
    """
    cab = _cabeceras(cliente, "corregir@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    primera, _, _ = _caso_a_mano(cliente, cab, cartera)

    antes = _valorar(cliente, cab, cartera)
    assert D(antes["posiciones"][0]["realizado"]) == D("6147.92")

    r = cliente.put(
        f"/api/v1/portfolios/{cartera}/transactions/{primera['id']}",
        json={
            "ticker": "AAPL",
            "tipo": "buy",
            "cantidad": "100",
            "precio": "140",
            "comisiones": "10",
            "fx": "0.90",
            "fecha": "2024-01-10",
        },
        headers=cab,
    )
    assert r.status_code == 200, r.text

    despues = _valorar(cliente, cab, cartera)
    (pos,) = despues["posiciones"]
    assert D(pos["realizado"]) == D("7047.92"), "la venta de septiembre tiene que haber cambiado"
    assert D(pos["coste"]) == D("4697.52"), "lo que queda sale del lote 2 y no se toca"


def test_borrar_una_transaccion_deshace_lo_que_colgaba_de_ella(cliente):
    cab = _cabeceras(cliente, "borrar@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    _, _, venta = _caso_a_mano(cliente, cab, cartera)

    r = cliente.delete(f"/api/v1/portfolios/{cartera}/transactions/{venta['id']}", headers=cab)
    assert r.status_code == 204

    v = _valorar(cliente, cab, cartera)
    (pos,) = v["posiciones"]
    assert D(pos["cantidad"]) == D("150"), "vuelven las 120 vendidas"
    assert D(pos["realizado"]) == D("0"), "ya no hay nada realizado"


# --- El corte temporal -----------------------------------------------------


def test_el_corte_temporal_deja_fuera_transacciones_y_precios_posteriores(cliente):
    """Una cartera a fecha pasada no puede ver ni una compra ni un precio del
    futuro. Es el mismo RT-2 que en `/stocks/{ticker}/analysis`: al montar la
    capa SaaS es exactamente aqui donde se reintroduce la anticipacion."""
    cab = _cabeceras(cliente, "corte@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    _mover(
        cliente,
        cab,
        cartera,
        ticker="ACS.MC",
        tipo="buy",
        cantidad="100",
        precio="20",
        fecha="2024-02-01",
    )
    _mover(
        cliente,
        cab,
        cartera,
        ticker="ACS.MC",
        tipo="buy",
        cantidad="900",
        precio="20",
        fecha=str(DESPUES),
    )

    v = _valorar(cliente, cab, cartera)
    (pos,) = v["posiciones"]
    assert D(pos["cantidad"]) == D("100"), "la compra posterior al corte no entra"
    assert pos["fecha_precio"] == str(CORTE), "ni el precio posterior al corte"
    assert D(pos["precio"]) == D("30")


def test_sin_corte_la_cartera_incluye_todo_lo_registrado(cliente):
    cab = _cabeceras(cliente, "sincorte@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    _mover(
        cliente,
        cab,
        cartera,
        ticker="ACS.MC",
        tipo="buy",
        cantidad="100",
        precio="20",
        fecha="2024-02-01",
    )
    _mover(
        cliente,
        cab,
        cartera,
        ticker="ACS.MC",
        tipo="buy",
        cantidad="900",
        precio="20",
        fecha=str(DESPUES),
    )

    r = cliente.get(f"/api/v1/portfolios/{cartera}", headers=cab)
    assert r.status_code == 200, r.text
    assert D(r.json()["posiciones"][0]["cantidad"]) == D("1000")


# --- Divisa ----------------------------------------------------------------


def test_el_cambio_se_congela_al_escribir_y_no_se_reescribe_despues(cliente):
    """El tipo de la operacion es el del dia en que se ejecuto, guardado con
    ella. Recalcularlo con el de hoy reescribiria la historia de la cartera cada
    manana."""
    cab = _cabeceras(cliente, "fxcongelado@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    t = _mover(
        cliente,
        cab,
        cartera,
        ticker="AAPL",
        tipo="buy",
        cantidad="10",
        precio="100",
        fx="0.90",
        fecha="2024-01-10",
    )
    assert D(t["fx"]) == D("0.90")

    filas = cliente.get(f"/api/v1/portfolios/{cartera}/transactions", headers=cab).json()
    assert D(filas[0]["fx"]) == D("0.90"), "no es el 0,80 de hoy"
    assert filas[0]["divisa"] == "USD", "la divisa sale del valor si no se pasa"


def test_sin_fx_se_toma_el_del_dia_de_fx_rate(cliente):
    cab = _cabeceras(cliente, "fxtabla@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    t = _mover(
        cliente,
        cab,
        cartera,
        ticker="AAPL",
        tipo="buy",
        cantidad="10",
        precio="100",
        fecha="2024-06-01",
    )
    assert D(t["fx"]) == FX_USD_EUR, "1 / 1,25, invirtiendo el convenio EUR -> divisa"


def test_sin_ningun_cambio_conocido_la_transaccion_se_rechaza(cliente):
    """Y no se guarda con un 1 implicito: un 1 entre BRL y EUR no falla, solo da
    un P&L equivocado que nadie mira."""
    cab = _cabeceras(cliente, "fxausente@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    r = cliente.post(
        f"/api/v1/portfolios/{cartera}/transactions",
        json={
            "ticker": "ABEV3.SA",
            "tipo": "buy",
            "cantidad": "10",
            "precio": "100",
            "fecha": "2024-06-01",
        },
        headers=cab,
    )
    assert r.status_code == 422
    assert "tipo de cambio" in r.json()["detail"]


# --- Lo que no se sabe se declara -----------------------------------------


def test_un_valor_sin_precio_se_declara_y_no_se_valora_a_coste(cliente):
    """Valorar a coste finge que no se ha movido, que es justo lo que no se
    sabe."""
    cab = _cabeceras(cliente, "sinprecio@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    _mover(
        cliente,
        cab,
        cartera,
        ticker="ACX.MC",
        tipo="buy",
        cantidad="10",
        precio="150",
        fecha="2024-02-01",
    )

    v = _valorar(cliente, cab, cartera)
    assert v["sin_valorar"] == ["ACX.MC"]
    (pos,) = v["posiciones"]
    assert pos["valor"] is None and pos["no_realizado"] is None
    assert D(v["totales"]["valor"]) == D("0"), "el coste no se cuela como valor"


def test_el_score_medio_se_pondera_por_peso_y_no_es_la_media_aritmetica(cliente):
    """Una posicion del 37 % no puede pesar lo mismo que una del 63 %.

    Con AAPL a 80 y ACS.MC a 20:
      valores      = 30*210*0,80 = 5.040 EUR  y  100*30 = 3.000 EUR
      ponderada    = (5.040*80 + 3.000*20) / 8.040 = 57,61
      aritmetica   = (80 + 20) / 2               = 50

    El test fija las dos: sin la segunda afirmacion, una media aritmetica
    pasaria igual el dia que las dos posiciones pesen parecido.
    """
    cab = _cabeceras(cliente, "score@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    _mover(
        cliente,
        cab,
        cartera,
        ticker="AAPL",
        tipo="buy",
        cantidad="30",
        precio="150",
        fx="0.90",
        fecha="2024-01-10",
    )
    _mover(
        cliente,
        cab,
        cartera,
        ticker="ACS.MC",
        tipo="buy",
        cantidad="100",
        precio="20",
        fecha="2024-02-01",
    )

    medio = _valorar(cliente, cab, cartera)["score_medio"]
    assert medio["valor"] == pytest.approx(57.61, abs=0.01), "ponderada por peso"
    assert medio["valor"] != pytest.approx(50.0, abs=0.01), "no es la media aritmetica"


def test_lo_que_no_tiene_score_no_se_imputa_a_50_y_la_cobertura_lo_declara(cliente):
    """AENA.MC tiene precio pero no score.

    Si se imputara un 50 neutro (lo que D-8 prohibe), la media saldria
    (5.040*80 + 1.500*50) / 6.540 = 73,12 en lugar de 80. El test fija las dos
    cosas: la media de los que SI tienen score, y la cobertura al lado, porque
    un 80 publicado a secas se lee como el de toda la cartera.
    """
    cab = _cabeceras(cliente, "cobertura@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    _mover(
        cliente,
        cab,
        cartera,
        ticker="AAPL",
        tipo="buy",
        cantidad="30",
        precio="150",
        fx="0.90",
        fecha="2024-01-10",
    )
    _mover(
        cliente,
        cab,
        cartera,
        ticker="AENA.MC",
        tipo="buy",
        cantidad="10",
        precio="140",
        fecha="2024-02-01",
    )

    medio = _valorar(cliente, cab, cartera)["score_medio"]
    assert medio["valor"] == pytest.approx(80.0), "solo los que tienen score"
    assert medio["valor"] != pytest.approx(73.12, abs=0.01), "no se imputa un 50 neutro"
    assert medio["cobertura"] == pytest.approx(5040 / 6540, abs=1e-4)
    assert medio["fecha_datos"] == str(CORTE)


def test_exposicion_y_diversificacion_salen_del_valor_de_mercado(cliente):
    cab = _cabeceras(cliente, "exposicion@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    _mover(
        cliente,
        cab,
        cartera,
        ticker="AAPL",
        tipo="buy",
        cantidad="30",
        precio="150",
        fx="0.90",
        fecha="2024-01-10",
    )
    _mover(
        cliente,
        cab,
        cartera,
        ticker="ACS.MC",
        tipo="buy",
        cantidad="100",
        precio="20",
        fecha="2024-02-01",
    )

    v = _valorar(cliente, cab, cartera)
    peso_aapl = 5040 / 8040
    peso_acs = 3000 / 8040

    assert v["exposicion_pais"]["US"] == pytest.approx(peso_aapl, abs=1e-4)
    assert v["exposicion_pais"]["ES"] == pytest.approx(peso_acs, abs=1e-4)
    assert v["exposicion_sector"]["tecnologia"] == pytest.approx(peso_aapl, abs=1e-4)
    assert v["exposicion_sector"]["industrial"] == pytest.approx(peso_acs, abs=1e-4)

    div = v["diversificacion"]
    assert div["posiciones"] == 2
    esperado = peso_aapl**2 + peso_acs**2
    assert div["hhi"] == pytest.approx(esperado, abs=1e-4)
    assert div["posiciones_efectivas"] == pytest.approx(1 / esperado, abs=1e-2)


def test_la_asignacion_objetivo_se_guarda_y_la_desviacion_se_deriva(cliente):
    """El objetivo es lo unico que se guarda ademas de las transacciones: es una
    decision, no una consecuencia. La desviacion si se deriva."""
    cab = _cabeceras(cliente, "objetivo@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    _mover(
        cliente,
        cab,
        cartera,
        ticker="AAPL",
        tipo="buy",
        cantidad="30",
        precio="150",
        fx="0.90",
        fecha="2024-01-10",
    )
    _mover(
        cliente,
        cab,
        cartera,
        ticker="ACS.MC",
        tipo="buy",
        cantidad="100",
        precio="20",
        fecha="2024-02-01",
    )

    r = cliente.put(
        f"/api/v1/portfolios/{cartera}/objetivo",
        json={"pesos": {"AAPL": 0.5, "ACS.MC": 0.5}},
        headers=cab,
    )
    assert r.status_code == 200, r.text

    posiciones = {p["ticker"]: p for p in _valorar(cliente, cab, cartera)["posiciones"]}
    assert posiciones["AAPL"]["objetivo"] == pytest.approx(0.5)
    assert posiciones["AAPL"]["desviacion"] == pytest.approx(5040 / 8040 - 0.5, abs=1e-4)


def test_un_objetivo_que_no_suma_uno_se_rechaza(cliente):
    cab = _cabeceras(cliente, "objetivomal@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    r = cliente.put(
        f"/api/v1/portfolios/{cartera}/objetivo",
        json={"pesos": {"AAPL": 0.5, "ACS.MC": 0.2}},
        headers=cab,
    )
    assert r.status_code == 422


# --- Puerta de plan y de propiedad -----------------------------------------


def test_el_limite_de_carteras_del_plan_es_un_409_y_no_un_403(cliente):
    """409 y no 403: 403 dice "no puedes"; aqui si puedes, pero ya has gastado
    lo tuyo. Uno se arregla cambiando de plan y el otro borrando algo."""
    cab = _cabeceras(cliente, "cupo@pruebas.example.com")
    _cartera(cliente, cab, "Primera")

    r = cliente.post("/api/v1/portfolios", json={"nombre": "Segunda"}, headers=cab)
    assert r.status_code == 409, "FREE tiene una sola cartera"
    assert "maximo" in r.json()["detail"]


def test_la_cartera_de_otro_no_se_puede_ni_confirmar_que_existe(cliente):
    """404 y no 403: un 403 sobre la cartera 41 confirma que la cartera 41
    existe, que es justo lo que quien pregunta no tiene derecho a saber."""
    ana = _cabeceras(cliente, "ana@pruebas.example.com")
    suya = _cartera(cliente, ana)

    luis = _cabeceras(cliente, "luis@pruebas.example.com")
    for peticion in (
        cliente.get(f"/api/v1/portfolios/{suya}", headers=luis),
        cliente.get(f"/api/v1/portfolios/{suya}/transactions", headers=luis),
        cliente.delete(f"/api/v1/portfolios/{suya}", headers=luis),
        cliente.patch(f"/api/v1/portfolios/{suya}", json={"nombre": "mia"}, headers=luis),
    ):
        assert peticion.status_code == 404, peticion.text

    assert cliente.get(f"/api/v1/portfolios/{suya}", headers=ana).status_code == 200


def test_sin_sesion_no_se_ve_ninguna_cartera(cliente):
    assert cliente.get("/api/v1/portfolios").status_code == 401
    assert cliente.post("/api/v1/portfolios", json={"nombre": "x"}).status_code == 401


def test_un_ticker_desconocido_se_rechaza_con_su_motivo(cliente):
    cab = _cabeceras(cliente, "desconocido@pruebas.example.com")
    cartera = _cartera(cliente, cab)
    r = cliente.post(
        f"/api/v1/portfolios/{cartera}/transactions",
        json={
            "ticker": "NOEXISTE",
            "tipo": "buy",
            "cantidad": "1",
            "precio": "1",
            "fecha": "2024-06-01",
        },
        headers=cab,
    )
    assert r.status_code == 422
    assert "NOEXISTE" in r.json()["detail"]
