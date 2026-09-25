"""Autenticacion, planes y limitacion de peticiones (FASE 12).

Lo que se comprueba aqui no es que el login funcione —eso es lo facil— sino las
propiedades que se rompen en silencio:

- que no se pueda averiguar QUE CORREOS existen, ni por la respuesta ni por el
  tiempo que tarda;
- que un token de refresco no valga como token de acceso;
- que cerrar sesion REVOQUE de verdad;
- que un enlace de reinicio sirva UNA vez;
- que los limites de plan se lean de un unico sitio.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from backend.db.session import sesion as dependencia_sesion
from backend.main import crear_app

CONTRASENA = "una-contrasena-larga-de-prueba"


@pytest.fixture
def cliente(bd_con_referencia, monkeypatch):
    """Cliente con base de datos y con el limitador y la lista negra en memoria.

    Se sustituye Redis por un diccionario en lugar de levantar uno: lo que estos
    tests comprueban es la LOGICA —que se revoca, que se agota el cupo—, no que
    Redis sepa contar. El comportamiento con Redis caido tiene su propio test.
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

    app = crear_app()

    def sesion_de_prueba():
        with sa.orm.Session(bd_con_referencia) as s:
            yield s

    app.dependency_overrides[dependencia_sesion] = sesion_de_prueba
    yield TestClient(app)

    with sa.orm.Session(bd_con_referencia) as s:
        s.execute(sa.text("DELETE FROM user_account WHERE email LIKE '%@pruebas.example.com'"))
        s.commit()


def _registrar(cliente, correo: str = "alguien@pruebas.example.com") -> dict:
    r = cliente.post("/api/v1/auth/register", json={"email": correo, "contrasena": CONTRASENA})
    assert r.status_code == 201, r.text
    return r.json()


# --- Registro y login ------------------------------------------------------


def test_registro_y_login(cliente):
    tokens = _registrar(cliente)
    assert tokens["acceso"] and tokens["refresco"]

    r = cliente.post(
        "/api/v1/auth/login",
        json={"email": "alguien@pruebas.example.com", "contrasena": CONTRASENA},
    )
    assert r.status_code == 200

    yo = cliente.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['acceso']}"})
    assert yo.status_code == 200
    assert yo.json()["email"] == "alguien@pruebas.example.com"
    assert yo.json()["plan"] == "free", "todos empiezan en FREE"


def test_el_correo_se_normaliza_a_minusculas(cliente):
    """Sin esto, `Ana@x.com` y `ana@x.com` son dos cuentas y la de recuperar
    contrasena no encuentra la suya."""
    _registrar(cliente, "MAYUSCULAS@pruebas.example.com")

    r = cliente.post(
        "/api/v1/auth/login",
        json={"email": "mayusculas@pruebas.example.com", "contrasena": CONTRASENA},
    )
    assert r.status_code == 200


def test_una_contrasena_corta_se_rechaza_con_su_motivo(cliente):
    r = cliente.post(
        "/api/v1/auth/register", json={"email": "corta@pruebas.example.com", "contrasena": "abc"}
    )
    assert r.status_code == 422


def test_la_contrasena_no_se_guarda_en_claro(cliente, bd_con_referencia):
    """Lo obvio, comprobado: un hash que no lo es no se distingue mirando la API."""
    _registrar(cliente, "hash@pruebas.example.com")
    with sa.orm.Session(bd_con_referencia) as s:
        guardado = s.execute(
            sa.text(
                "SELECT password_hash FROM user_account WHERE email = 'hash@pruebas.example.com'"
            )
        ).scalar()
    assert guardado is not None
    assert CONTRASENA not in guardado
    assert guardado.startswith("$argon2id$"), "tiene que ser Argon2id, no otro algoritmo"


# --- No se puede averiguar quien tiene cuenta ------------------------------


def test_el_login_no_distingue_correo_inexistente_de_contrasena_mala(cliente):
    """Dos respuestas distintas convertirian el login en un buscador de clientes."""
    _registrar(cliente, "existe@pruebas.example.com")

    inexistente = cliente.post(
        "/api/v1/auth/login",
        json={"email": "nadie@pruebas.example.com", "contrasena": CONTRASENA},
    )
    mala = cliente.post(
        "/api/v1/auth/login",
        json={"email": "existe@pruebas.example.com", "contrasena": "otra-contrasena-larga"},
    )

    assert inexistente.status_code == mala.status_code == 401
    assert inexistente.json() == mala.json()


def test_pedir_un_reinicio_responde_igual_exista_o_no_la_cuenta(cliente):
    _registrar(cliente, "reinicio@pruebas.example.com")

    a = cliente.post("/api/v1/auth/password-reset", json={"email": "reinicio@pruebas.example.com"})
    b = cliente.post("/api/v1/auth/password-reset", json={"email": "nadie@pruebas.example.com"})

    assert a.status_code == b.status_code == 202
    assert a.json() == b.json()


def test_registrar_un_correo_ya_dado_de_alta_no_lo_confirma(cliente):
    """409 hace falta para que el cliente sepa que no se creo, pero el mensaje
    no dice 'ese correo ya existe'."""
    _registrar(cliente, "repetido@pruebas.example.com")
    r = cliente.post(
        "/api/v1/auth/register",
        json={"email": "repetido@pruebas.example.com", "contrasena": CONTRASENA},
    )
    assert r.status_code == 409
    assert "existe" not in r.json()["detail"].lower()


# --- Los tokens tienen proposito -------------------------------------------


def test_un_token_de_refresco_no_sirve_como_token_de_acceso(cliente):
    """Sin la comprobacion de proposito, el token de vida larga —el que se
    guarda en disco— valdria para llamar a cualquier endpoint."""
    tokens = _registrar(cliente, "proposito@pruebas.example.com")

    r = cliente.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['refresco']}"})
    assert r.status_code == 401


def test_sin_credenciales_y_con_credenciales_malas_dan_401(cliente):
    assert cliente.get("/api/v1/auth/me").status_code == 401
    assert (
        cliente.get("/api/v1/auth/me", headers={"Authorization": "Bearer basura"}).status_code
        == 401
    )


def test_cerrar_sesion_revoca_el_refresco(cliente):
    """Un JWT firmado vale hasta que caduca. Sin lista negra, cerrar sesion es
    un boton que no hace nada."""
    tokens = _registrar(cliente, "salir@pruebas.example.com")

    assert (
        cliente.post("/api/v1/auth/logout", json={"refresco": tokens["refresco"]}).status_code
        == 204
    )
    r = cliente.post("/api/v1/auth/refresh", json={"refresco": tokens["refresco"]})
    assert r.status_code == 401


def test_refrescar_rota_el_token_y_el_viejo_deja_de_valer(cliente):
    """Si alguien roba un refresco y lo usa, el legitimo deja de funcionar y el
    robo se nota. Sin rotacion, los dos conviven sin que nadie se entere."""
    tokens = _registrar(cliente, "rotacion@pruebas.example.com")

    nuevo = cliente.post("/api/v1/auth/refresh", json={"refresco": tokens["refresco"]})
    assert nuevo.status_code == 200

    repetido = cliente.post("/api/v1/auth/refresh", json={"refresco": tokens["refresco"]})
    assert repetido.status_code == 401, "el refresco usado tiene que quedar revocado"


# --- Reinicio de contrasena ------------------------------------------------


def test_el_enlace_de_reinicio_sirve_una_sola_vez(cliente):
    """Un enlace que viaja por correo y vale treinta minutos enteros por mas
    veces que se use es un enlace que, filtrado, sigue abriendo la cuenta."""
    from backend.seguridad import Proposito, emitir

    tokens = _registrar(cliente, "unsolo@pruebas.example.com")
    yo = cliente.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['acceso']}"}
    ).json()
    token, _ = emitir(yo["id"], Proposito.REINICIO)

    nueva = "otra-contrasena-larga-valida"
    primera = cliente.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "contrasena": nueva}
    )
    assert primera.status_code == 200

    segunda = cliente.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "contrasena": "tercera-contrasena-larga"},
    )
    assert segunda.status_code == 400

    # Y la contrasena cambiada es la de la PRIMERA vez.
    assert (
        cliente.post(
            "/api/v1/auth/login", json={"email": "unsolo@pruebas.example.com", "contrasena": nueva}
        ).status_code
        == 200
    )


def test_un_token_de_acceso_no_sirve_para_cambiar_la_contrasena(cliente):
    tokens = _registrar(cliente, "cruzado@pruebas.example.com")
    r = cliente.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": tokens["acceso"], "contrasena": "otra-contrasena-larga"},
    )
    assert r.status_code == 400


# --- Limitacion de peticiones ----------------------------------------------


def test_el_login_se_limita_por_intentos(cliente):
    """Diez intentos por cinco minutos. Sin esto, probar contrasenas sale gratis."""
    _registrar(cliente, "fuerzabruta@pruebas.example.com")
    codigos = [
        cliente.post(
            "/api/v1/auth/login",
            json={"email": "fuerzabruta@pruebas.example.com", "contrasena": "mala-contrasena-x"},
        ).status_code
        for _ in range(12)
    ]
    assert 429 in codigos, "tendria que haber cortado antes del intento 12"
    assert codigos.index(429) >= 10, "y no antes de agotar los 10 permitidos"


def test_si_redis_no_responde_se_rechaza_en_vez_de_dejar_pasar(bd_con_referencia, monkeypatch):
    """Fallar cerrado.

    Un limitador que se apaga solo cuando su dependencia cae es justo lo que no
    quieres el dia que alguien tumba Redis a proposito: la barra libre para
    probar contrasenas llega precisamente cuando menos se mira.
    """
    import backend.limites as limites

    def revienta(clave, ventana):
        raise limites._SinRedis("caido")

    monkeypatch.setattr(limites, "_contar", revienta)
    app = crear_app()

    def sesion_de_prueba():
        with sa.orm.Session(bd_con_referencia) as s:
            yield s

    app.dependency_overrides[dependencia_sesion] = sesion_de_prueba
    c = TestClient(app)

    r = c.post(
        "/api/v1/auth/login",
        json={"email": "x@pruebas.example.com", "contrasena": CONTRASENA},
    )
    assert r.status_code == 503


# --- Planes ----------------------------------------------------------------


def test_los_limites_de_plan_se_leen_de_un_unico_sitio():
    """El criterio de aceptacion de la fase.

    Si aparece un segundo diccionario de limites, este test no lo detecta —nada
    lo haria— pero al menos fija que este es el sitio y que un plan desconocido
    cae al mas restrictivo.
    """
    from backend.db.models.enums import SubscriptionPlan
    from backend.limites import LIMITES, al_menos, limites_de

    assert set(LIMITES) == {p.value for p in SubscriptionPlan}
    for plan in SubscriptionPlan:
        assert limites_de(plan.value) is LIMITES[plan.value]

    assert limites_de("plan-que-no-existe") is LIMITES["free"], "cae al mas restrictivo"
    assert limites_de("free").carteras < limites_de("pro").carteras < limites_de("premium").carteras
    assert al_menos("premium", SubscriptionPlan.FREE)
    assert not al_menos("free", SubscriptionPlan.PREMIUM)


def test_free_no_gasta_tokens_de_ia():
    """§50 pone el control de coste como restriccion, no como aspiracion."""
    from backend.limites import limites_de

    assert limites_de("free").explicaciones_ia_al_dia == 0
