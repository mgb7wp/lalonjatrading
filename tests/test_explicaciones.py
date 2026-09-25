"""Explicaciones con IA (FASE 16, §12).

La aceptación de la fase pide dos cosas, y las dos se comprueban aquí contra un
redactor falso que se porta mal a propósito, no contra la buena voluntad de un
modelo de verdad:

- ante un hueco, la respuesta dice «Información no disponible»; y si no lo
  dice, no se publica;
- el validador RECHAZA una respuesta con cifras que no estaban en la entrada.

Un test que llamara al modelo real probaría que hoy se porta bien. Estos
prueban que, el día que no lo haga, el texto no llega a nadie.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import json
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from backend import explicaciones as ia
from backend.db.models import Explanation, ModelVersion, Score, Security, Signal, User
from backend.db.models.enums import Cohort, ModelKind, SignalType

CONTRASENA = "una-contrasena-larga-de-prueba"
CORTE = dt.date(2025, 3, 31)
ANTES = CORTE - dt.timedelta(days=35)


# ---------------------------------------------------------------------------
# Entrada de referencia y redactores falsos
# ---------------------------------------------------------------------------


def _entrada(con_cambios: bool = True, con_senal: bool = True, a_favor: bool = True) -> dict:
    """Lo que construiría el endpoint para un valor típico."""
    return ia.construir_entrada(
        valor={"ticker": "AAPL", "name": "Apple", "market_id": "us", "sector": "tecnologia"},
        score={
            "fecha": CORTE,
            "modelo": "equilibrado",
            "overall": 75.0,
            "cohorte": "market_sector",
            "n_cohorte": 30,
            "pilares": {"fundamental": 82.5, "technical": 64.0, "sentiment": None, "risk": 22.0},
            "pilares_no_disponibles": {"sentiment": "sin datos suficientes en la cohorte"},
            "subscores": {"growth": 91.0, "valuation": 18.0},
        },
        explicacion={
            "a_favor": (
                [
                    {"nombre": "growth", "valor": 91.0, "nivel": "subscore"},
                    {"nombre": "fundamental", "valor": 82.5, "nivel": "pilar"},
                ]
                if a_favor
                else []
            ),
            "en_contra": [
                {"nombre": "valuation", "valor": 18.0, "nivel": "subscore"},
                {"nombre": "risk", "valor": 22.0, "nivel": "pilar"},
            ],
            "cambio_30d": {"overall": -5.0, "fundamental": 3.25} if con_cambios else {},
            "cambio_no_comparable": ["sentiment"],
        },
        senal=(
            {
                "fecha": CORTE,
                "senal": "buy",
                "motivo": "score_alto",
                "regimen": "alcista",
            }
            if con_senal
            else None
        ),
        motivo_sin_senal=None if con_senal else "no se ha emitido ninguna señal para este valor",
        dias_cambio=30,
    )


def _honesta(entrada: dict) -> dict:
    """Lo que devolvería un modelo que cumple las cuatro reglas."""
    senal = entrada["senal"]
    resumen = (
        f"{entrada['valor']['nombre']} tiene un score de {entrada['score']['total']:g} sobre "
        f"100: mejor que ese porcentaje de las {entrada['score']['empresas_en_cohorte']} "
        "empresas de su cohorte. "
    )
    resumen += (
        f"La señal es de {senal['senal']}."
        if senal["disponible"]
        else f"Señal: {ia.NO_DISPONIBLE}."
    )
    return {
        "resumen": resumen,
        "a_favor": [
            f"{f['factor']} en el percentil {f['percentil']:g}." for f in entrada["a_favor"]
        ],
        "en_contra": [
            f"{f['factor']} en el percentil {f['percentil']:g}." for f in entrada["en_contra"]
        ],
        "cambios": (
            [
                f"{k}: {abs(v):g} puntos {'menos' if v < 0 else 'más'}."
                for k, v in entrada["cambios_30d"]["variacion_en_puntos"].items()
            ]
            if entrada["cambios_30d"]["disponible"]
            else [ia.NO_DISPONIBLE]
        ),
        "preguntas": ["¿Es sostenible el crecimiento?", "¿Por qué cotiza caro frente a su sector?"],
    }


def _leer_entrada(mensaje: str) -> dict:
    cuerpo = mensaje.split("\n\n", 1)[1]
    cuerpo = cuerpo.split("\n\nTu respuesta anterior", 1)[0]
    return json.loads(cuerpo)


class Falso:
    """Redactor falso. `estropear` transforma la respuesta honesta."""

    modelo = "falso-1"

    def __init__(self, estropear=None, veces_mal: int = 99):
        self.estropear = estropear
        self.veces_mal = veces_mal
        self.mensajes: list[str] = []

    def redactar(self, sistema: str, mensaje: str):
        assert ia.NO_DISPONIBLE in sistema, "el prompt tiene que nombrar la frase exacta"
        self.mensajes.append(mensaje)
        salida = _honesta(_leer_entrada(mensaje))
        if self.estropear and len(self.mensajes) <= self.veces_mal:
            salida = self.estropear(salida)
        return salida, self.modelo


# ---------------------------------------------------------------------------
# Regla 3: el validador de cifras
# ---------------------------------------------------------------------------


def test_una_respuesta_fiel_pasa():
    e = _entrada()
    v = ia.validar(_honesta(e), e)
    assert v.valida, v.problemas


def test_una_cifra_inventada_rechaza_la_respuesta_entera():
    e = _entrada()
    salida = _honesta(e)
    salida["a_favor"].append("Sus ventas crecieron un 12 % el último año.")
    v = ia.validar(salida, e)
    assert not v.valida
    assert any("«12»" in p for p in v.problemas)


def test_una_cifra_calculada_tambien_es_inventada():
    """El LLM no calcula: 82,5 − 22 = 60,5 no estaba en la entrada, aunque se
    deduzca de ella. Una resta mal hecha pasaría igual de convincente."""
    e = _entrada()
    salida = _honesta(e)
    salida["resumen"] += " Fundamental supera a Riesgo en 60,5 puntos."
    assert not ia.validar(salida, e).valida


def test_convertir_a_porcentaje_tambien_es_inventar():
    e = _entrada()
    salida = _honesta(e)
    salida["resumen"] += " Eso es un 0,75 en tanto por uno."
    assert not ia.validar(salida, e).valida


@pytest.mark.parametrize(
    "frase",
    [
        "El score total es 75.",  # 75.0 dicho como entero
        "Fundamental en 82,5.",  # decimal con coma
        "Fundamental en 82.5.",  # decimal con punto
        "El total cayó 5 puntos.",  # un -5 dicho sin signo
        "Fundamental subió 3,2 puntos.",  # 3,25 → la entrada redondea a 1 decimal
        "Datos del 31 de marzo de 2025.",  # cifras de la fecha de la entrada
        "Sobre una escala de 0 a 100.",
    ],
)
def test_las_formas_naturales_de_decir_una_cifra_de_la_entrada_pasan(frase):
    e = _entrada()
    salida = _honesta(e)
    salida["resumen"] += " " + frase
    v = ia.validar(salida, e)
    assert v.valida, v.problemas


def test_mil_con_punto_de_miles_no_se_confunde_con_uno_coma():
    """«1.234» se lee de las dos maneras y basta con que una esté; pero si
    ninguna está, se rechaza."""
    e = _entrada()
    salida = _honesta(e)
    salida["resumen"] += " Tiene 1.234 empleados."
    assert not ia.validar(salida, e).valida


# ---------------------------------------------------------------------------
# Regla 2: «Información no disponible»
# ---------------------------------------------------------------------------


def test_un_hueco_de_cambios_se_declara_con_la_frase_exacta():
    e = _entrada(con_cambios=False)
    assert e["cambios_30d"]["disponible"] is False
    salida = _honesta(e)
    assert salida["cambios"] == [ia.NO_DISPONIBLE]
    assert ia.validar(salida, e).valida


def test_rellenar_el_hueco_de_cambios_se_rechaza():
    e = _entrada(con_cambios=False)
    salida = _honesta(e)
    salida["cambios"] = ["El score se ha mantenido estable."]
    v = ia.validar(salida, e)
    assert not v.valida
    assert any("cambios" in p for p in v.problemas)


def test_sin_senal_el_resumen_lo_dice():
    e = _entrada(con_senal=False)
    assert ia.validar(_honesta(e), e).valida
    salida = _honesta(e)
    salida["resumen"] = "Apple tiene un score de 75 y una señal de compra."
    assert not ia.validar(salida, e).valida


def test_hablar_de_un_pilar_ausente_sin_declararlo_se_rechaza():
    """Sentimiento no tiene dato. «El sentimiento es favorable» lo inventa;
    «Sentimiento: Información no disponible» lo declara."""
    e = _entrada()
    assert "Sentimiento" in e["no_disponible"]
    salida = _honesta(e)
    salida["a_favor"].append("El sentimiento del mercado es favorable.")
    assert not ia.validar(salida, e).valida

    salida = _honesta(e)
    salida["a_favor"].append(f"Sentimiento: {ia.NO_DISPONIBLE}.")
    assert ia.validar(salida, e).valida


def test_un_pilar_ausente_no_viaja_como_cifra():
    """Un `null` en la entrada invita a rellenarlo; por eso sale de las cifras y
    entra en `no_disponible` con su motivo."""
    e = _entrada()
    assert "Sentimiento" not in e["score"]["pilares"]
    assert e["no_disponible"]["Sentimiento"]


def test_factores_a_favor_sin_ninguno_en_la_entrada_se_rechazan():
    e = _entrada(a_favor=False)
    salida = _honesta(e)
    salida["a_favor"] = ["La empresa tiene una marca muy fuerte."]
    assert not ia.validar(salida, e).valida


def test_una_forma_que_no_es_la_del_esquema_se_rechaza():
    e = _entrada()
    assert not ia.validar("texto suelto", e).valida
    salida = _honesta(e)
    del salida["preguntas"]
    assert not ia.validar(salida, e).valida
    salida = _honesta(e)
    salida["consejo"] = "Compre."
    assert not ia.validar(salida, e).valida


# ---------------------------------------------------------------------------
# Redacción: reintento con motivo, y nada que no pase
# ---------------------------------------------------------------------------


def _inventa(salida: dict) -> dict:
    salida = copy.deepcopy(salida)
    salida["resumen"] += " El beneficio creció un 37 %."
    return salida


def test_un_rechazo_se_reintenta_diciendo_por_que():
    falso = Falso(_inventa, veces_mal=1)
    r = ia.redactar(falso, _entrada())
    assert len(falso.mensajes) == 2
    assert "«37»" in falso.mensajes[1], "el segundo intento tiene que saber qué falló"
    assert "37" not in r.resumen


def test_si_ningun_intento_pasa_no_hay_explicacion():
    falso = Falso(_inventa)
    with pytest.raises(ia.ExplicacionRechazada) as exc:
        ia.redactar(falso, _entrada())
    assert len(falso.mensajes) == ia.INTENTOS
    assert any("37" in p for p in exc.value.problemas)


# ---------------------------------------------------------------------------
# Regla 4: la clave de caché
# ---------------------------------------------------------------------------


def test_el_hash_es_estable_y_cambia_con_la_entrada():
    a, b = _entrada(), _entrada()
    assert ia.hash_entrada(a) == ia.hash_entrada(b)
    b["score"]["total"] = 76.0
    assert ia.hash_entrada(a) != ia.hash_entrada(b)
    # La señal también cuenta: si cambia, cambia lo que hay que contar.
    assert ia.hash_entrada(_entrada()) != ia.hash_entrada(_entrada(con_senal=False))


# ---------------------------------------------------------------------------
# El endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def cliente(bd_con_referencia, monkeypatch):
    """Tres valores:

    - AAPL:   score ahora y hace 35 días, y señal  -> explicación completa
    - ACS.MC: score sólo ahora, sin señal         -> huecos en cambios y señal
    - ACX.MC: nada                                -> no hay nada que explicar
    """
    import backend.api.v1.auth as auth
    import backend.limites as limites
    from backend.api.v1 import explicaciones as endpoint
    from backend.db.session import sesion as dependencia_sesion
    from backend.main import crear_app

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
                    Security.ticker.in_(["AAPL", "ACS.MC", "ACX.MC"])
                )
            ).all()
        )
        mv = ModelVersion(name="equilibrado", version="0.0.16-ia", kind=ModelKind.RULES.value)
        s.add(mv)
        s.flush()

        def score(ticker, fecha, overall, **pilares):
            s.add(
                Score(
                    security_id=ids[ticker],
                    date=fecha,
                    model_version_id=mv.id,
                    overall=Decimal(overall),
                    cohort_used=Cohort.MARKET_SECTOR.value,
                    n_cohort=30,
                    available_pillars=list(pilares),
                    **{k: Decimal(v) for k, v in pilares.items()},
                )
            )

        score("AAPL", ANTES, "70", fundamental="80", technical="60", risk="25")
        score("AAPL", CORTE, "75", fundamental="82.5", technical="64", risk="22", growth="91")
        # Un score POSTERIOR al corte: si se colara, cambiaría la explicación.
        score("AAPL", CORTE + dt.timedelta(days=5), "12", fundamental="10")
        s.add(
            Signal(
                security_id=ids["AAPL"],
                date=CORTE,
                model_version_id=mv.id,
                signal=SignalType.BUY.value,
                reason="score_alto",
                author="motor",
            )
        )
        score("ACS.MC", CORTE, "40", fundamental="40")
        s.commit()
        version_id = mv.id
        valores = list(ids.values())

    estado: dict = {"redactor": Falso()}
    app = crear_app()

    def sesion_de_prueba():
        with sa.orm.Session(bd_con_referencia) as s:
            yield s

    app.dependency_overrides[dependencia_sesion] = sesion_de_prueba
    app.dependency_overrides[endpoint.redactor] = lambda: estado["redactor"]
    c = TestClient(app)
    c.estado = estado
    c.contadores = contadores
    yield c

    with sa.orm.Session(bd_con_referencia) as s:
        s.execute(sa.delete(Explanation).where(Explanation.security_id.in_(valores)))
        s.execute(sa.text("DELETE FROM user_account WHERE email LIKE '%@pruebas.example.com'"))
        s.execute(sa.delete(Signal).where(Signal.model_version_id == version_id))
        s.execute(sa.delete(Score).where(Score.model_version_id == version_id))
        s.execute(sa.delete(ModelVersion).where(ModelVersion.id == version_id))
        s.commit()


def _cabeceras(cliente, correo: str, plan: str = "pro") -> dict:
    r = cliente.post("/api/v1/auth/register", json={"email": correo, "contrasena": CONTRASENA})
    assert r.status_code == 201, r.text
    if plan != "free":
        from backend.db.session import sesion as dependencia_sesion

        bd = next(cliente.app.dependency_overrides[dependencia_sesion]())
        bd.execute(sa.update(User).where(User.email == correo).values(subscription_plan=plan))
        bd.commit()
        bd.close()
    return {"Authorization": f"Bearer {r.json()['acceso']}"}


def _pedir(cliente, cab, ticker="AAPL", espera=200, **params):
    params.setdefault("fecha", str(CORTE))
    r = cliente.get(f"/api/v1/stocks/{ticker}/explanation", params=params, headers=cab)
    assert r.status_code == espera, r.text
    return r.json()


def test_sin_sesion_no_hay_explicacion(cliente):
    _pedir(cliente, {}, espera=401)


def test_el_plan_gratuito_no_tiene_explicaciones(cliente):
    cab = _cabeceras(cliente, "gratis@pruebas.example.com", plan="free")
    r = _pedir(cliente, cab, espera=403)
    assert "pro" in r["detail"]
    assert not cliente.estado["redactor"].mensajes, "ni una llamada al modelo"


def test_la_explicacion_se_genera_con_lo_que_se_sabia_al_corte(cliente):
    cab = _cabeceras(cliente, "completa@pruebas.example.com")
    e = _pedir(cliente, cab)["explicacion"]
    assert e["disponible"], e
    d = e["datos"]
    assert d["desde_cache"] is False
    assert d["fecha_score"] == str(CORTE)
    assert d["entrada"]["score"]["total"] == 75.0, "el score posterior al corte no entra"
    assert "75" in d["resumen"]
    assert d["modelo_llm"] == "falso-1"
    assert d["cambios"] and ia.NO_DISPONIBLE not in d["cambios"]


def test_la_segunda_vez_sale_de_la_cache_sin_llamar_ni_gastar_cupo(cliente):
    cab = _cabeceras(cliente, "cache@pruebas.example.com")
    primera = _pedir(cliente, cab)["explicacion"]["datos"]
    gastado = sum(cliente.contadores.values())
    segunda = _pedir(cliente, cab)["explicacion"]["datos"]
    # Otro corte con el mismo score: la misma explicación.
    tercera = _pedir(cliente, cab, fecha=str(CORTE + dt.timedelta(days=2)))["explicacion"]["datos"]

    assert len(cliente.estado["redactor"].mensajes) == 1
    assert segunda["desde_cache"] and tercera["desde_cache"]
    assert segunda["resumen"] == primera["resumen"] == tercera["resumen"]
    assert sum(cliente.contadores.values()) == gastado, "servir de caché no gasta cupo"


def test_ante_un_hueco_responde_informacion_no_disponible(cliente):
    """El criterio de aceptación de la fase: ACS.MC no tiene score de hace 30
    días ni señal, y la explicación lo dice con la frase exacta."""
    cab = _cabeceras(cliente, "hueco@pruebas.example.com")
    d = _pedir(cliente, cab, ticker="ACS.MC")["explicacion"]["datos"]
    assert d["entrada"]["cambios_30d"]["disponible"] is False
    assert d["cambios"] == [ia.NO_DISPONIBLE]
    assert ia.NO_DISPONIBLE in d["resumen"]


def test_un_modelo_que_rellena_el_hueco_no_se_publica_ni_se_guarda(cliente):
    def rellena(salida):
        salida["cambios"] = ["El score se ha mantenido estable el último mes."]
        return salida

    cliente.estado["redactor"] = Falso(rellena)
    cab = _cabeceras(cliente, "rellena@pruebas.example.com")
    e = _pedir(cliente, cab, ticker="ACS.MC")["explicacion"]
    assert e["disponible"] is False
    assert e["datos"] is None
    assert "descartado" in e["motivo"]
    with _bd(cliente) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Explanation)) == 0


def test_un_modelo_que_inventa_cifras_no_se_publica_ni_se_guarda(cliente):
    cliente.estado["redactor"] = Falso(_inventa)
    cab = _cabeceras(cliente, "inventa@pruebas.example.com")
    e = _pedir(cliente, cab)["explicacion"]
    assert e["disponible"] is False
    assert "37" not in json.dumps(e, ensure_ascii=False)
    with _bd(cliente) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Explanation)) == 0


def test_sin_score_no_se_llama_al_modelo(cliente):
    cab = _cabeceras(cliente, "sinscore@pruebas.example.com")
    e = _pedir(cliente, cab, ticker="ACX.MC")["explicacion"]
    assert e["disponible"] is False
    assert "score" in e["motivo"]
    assert not cliente.estado["redactor"].mensajes


def test_sin_clave_de_ia_se_declara_y_no_se_rompe(cliente):
    cliente.estado["redactor"] = None
    cab = _cabeceras(cliente, "sinclave@pruebas.example.com")
    e = _pedir(cliente, cab)["explicacion"]
    assert e["disponible"] is False
    assert "no está configurada" in e["motivo"]


def test_un_fallo_del_modelo_es_un_bloque_no_disponible(cliente):
    class Caido:
        modelo = "caido"

        def redactar(self, sistema, mensaje):
            raise ia.ErrorRedactor("sin conexión")

    cliente.estado["redactor"] = Caido()
    cab = _cabeceras(cliente, "caido@pruebas.example.com")
    e = _pedir(cliente, cab)["explicacion"]
    assert e["disponible"] is False
    assert "no ha respondido" in e["motivo"]


def test_el_cupo_diario_se_respeta(cliente, monkeypatch):
    import backend.limites as limites

    pro = limites.LIMITES["pro"]
    monkeypatch.setitem(limites.LIMITES, "pro", dataclasses.replace(pro, explicaciones_ia_al_dia=1))
    cab = _cabeceras(cliente, "cupo@pruebas.example.com")
    _pedir(cliente, cab)  # gasta la única
    _pedir(cliente, cab)  # caché: no gasta
    r = _pedir(cliente, cab, ticker="ACS.MC", espera=429)
    assert "explicaciones" in r["detail"]


def _bd(cliente):
    from backend.db.session import sesion as dependencia_sesion

    class _Ctx:
        def __enter__(self):
            self.gen = cliente.app.dependency_overrides[dependencia_sesion]()
            return next(self.gen)

        def __exit__(self, *exc):
            self.gen.close()

    return _Ctx()
