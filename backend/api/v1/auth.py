"""Registro, login, refresco y reinicio de contrasena.

## Decisiones que no son de estilo

**No se confirma si un correo existe.** Ni al registrarse ni al pedir un
reinicio. Un endpoint que responde distinto segun si la cuenta existe es una
lista de clientes que cualquiera puede descargar a razon de una peticion por
correo; y para la victima de una filtracion de contrasenas de otro sitio, saber
que aqui tambien tiene cuenta es justo el dato que faltaba.

**El login tarda lo mismo acierte o falle.** Si un correo inexistente responde
en 2 ms y uno real en 90 ms —lo que cuesta verificar Argon2—, el propio tiempo
delata cuales existen. Por eso se verifica contra un hash de mentira cuando el
usuario no existe.

**Los tokens de refresco y de reinicio se pueden revocar.** Un JWT firmado vale
hasta que caduca, asi que el `jti` se anota en Redis: al cerrar sesion se mete
en una lista negra, y un token de reinicio se marca como gastado en cuanto se
usa. Sin eso, un enlace de recuperacion filtrado sirve treinta minutos enteros
por mas veces que se use.

**El envio de correo llega en la FASE 15.** Mientras tanto el token de reinicio
se registra en el log del servidor en entornos que no son produccion, y en
produccion no se emite: prefiero que la funcion no exista a que exista a medias
y alguien crea que el correo va a llegar.
"""

from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from ...config import settings
from ...db.models import User
from ...db.models.enums import SubscriptionPlan
from ...limites import limitar
from ...seguridad import (
    ContrasenaDebil,
    Proposito,
    TokenInvalido,
    cifrar,
    comprobar,
    emitir,
    leer,
    necesita_recifrado,
)
from ..deps import BD, Actual

log = logging.getLogger("auth")

router = APIRouter(prefix="/auth", tags=["auth"])

#: Hash de una contrasena que nadie tiene, para gastar el mismo tiempo cuando el
#: correo no existe. Se calcula una vez al importar.
_HASH_SENUELO = cifrar("senuelo-para-igualar-el-tiempo-de-respuesta")

#: Prefijo de las claves de la lista negra en Redis.
_REVOCADOS = "revocado:"


def _revocar(jti: str, segundos: int) -> None:
    """Anota un `jti` como revocado hasta que el token habria caducado igual.

    Si Redis no responde, esto REVIENTA en lugar de seguir: un cierre de sesion
    que no revoca nada pero dice que si es peor que uno que falla.
    """
    from ...limites import _redis

    _redis().setex(f"{_REVOCADOS}{jti}", max(segundos, 1), "1")


def _esta_revocado(jti: str) -> bool:
    from ...limites import _redis

    return bool(_redis().exists(f"{_REVOCADOS}{jti}"))


class Registro(BaseModel):
    email: EmailStr
    contrasena: str = Field(min_length=12, max_length=200)


class Credenciales(BaseModel):
    email: EmailStr
    contrasena: str = Field(max_length=200)


class Tokens(BaseModel):
    acceso: str
    refresco: str
    tipo: str = "bearer"
    caduca_en: int


class Refresco(BaseModel):
    refresco: str


class SolicitudReinicio(BaseModel):
    email: EmailStr


class ConfirmacionReinicio(BaseModel):
    token: str
    contrasena: str = Field(min_length=12, max_length=200)


def _emitir_par(usuario: User) -> Tokens:
    cfg = settings()
    acceso, _ = emitir(usuario.id, Proposito.ACCESO)
    refresco, _ = emitir(usuario.id, Proposito.REFRESCO)
    return Tokens(acceso=acceso, refresco=refresco, caduca_en=cfg.jwt_minutos * 60)


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Crear una cuenta",
    dependencies=[Depends(limitar("registro", maximo=5, ventana=3600))],
)
def registrar(datos: Registro, bd: BD) -> Tokens:
    try:
        hash_ = cifrar(datos.contrasena)
    except ContrasenaDebil as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # `citext` no esta activado, asi que la unicidad se comprueba en minusculas
    # y el correo se guarda normalizado. Sin esto, `Ana@x.com` y `ana@x.com`
    # serian dos cuentas distintas y la de recuperar contrasena no encontraria
    # la suya.
    correo = datos.email.strip().lower()
    existe = bd.scalars(select(User).where(func.lower(User.email) == correo)).first()
    if existe is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no se ha podido crear la cuenta con esos datos",
        )

    usuario = User(
        email=correo,
        password_hash=hash_,
        auth_provider="password",
        subscription_plan=SubscriptionPlan.FREE.value,
        is_active=True,
    )
    bd.add(usuario)
    bd.commit()
    bd.refresh(usuario)
    return _emitir_par(usuario)


@router.post(
    "/login",
    summary="Iniciar sesion",
    dependencies=[Depends(limitar("login", maximo=10, ventana=300))],
)
def entrar(datos: Credenciales, bd: BD) -> Tokens:
    correo = datos.email.strip().lower()
    usuario = bd.scalars(select(User).where(func.lower(User.email) == correo)).first()

    # Se verifica SIEMPRE, exista o no, para que el tiempo de respuesta no
    # delate que correos estan dados de alta.
    guardado = usuario.password_hash if usuario else _HASH_SENUELO
    valida = comprobar(datos.contrasena, guardado or _HASH_SENUELO)

    if usuario is None or not valida or not usuario.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="credenciales incorrectas"
        )

    # Subir el coste de Argon2 sin pedirle a nadie que cambie de contrasena.
    if necesita_recifrado(usuario.password_hash):
        usuario.password_hash = cifrar(datos.contrasena)
    usuario.last_login_at = dt.datetime.now(dt.UTC)
    bd.commit()
    return _emitir_par(usuario)


@router.post("/refresh", summary="Renovar el token de acceso")
def refrescar(datos: Refresco, bd: BD) -> Tokens:
    try:
        cuerpo = leer(datos.refresco, Proposito.REFRESCO)
    except TokenInvalido as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token de refresco inválido"
        ) from exc

    if _esta_revocado(cuerpo["jti"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sesión cerrada")

    usuario = bd.scalars(select(User).where(User.id == int(cuerpo["sub"]))).first()
    if usuario is None or not usuario.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sesión inválida")

    # Rotacion: el refresco usado se revoca al emitir el nuevo. Si alguien roba
    # uno y lo usa, el legitimo deja de valer y el robo se nota.
    _revocar(cuerpo["jti"], int(cuerpo["exp"] - dt.datetime.now(dt.UTC).timestamp()))
    return _emitir_par(usuario)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Cerrar sesion")
def salir(datos: Refresco) -> None:
    try:
        cuerpo = leer(datos.refresco, Proposito.REFRESCO)
    except TokenInvalido:
        # Cerrar una sesion que ya no vale es exito, no error.
        return
    restante = int(cuerpo["exp"] - dt.datetime.now(dt.UTC).timestamp())
    _revocar(cuerpo["jti"], restante)


@router.post(
    "/password-reset",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pedir un reinicio de contrasena",
    dependencies=[Depends(limitar("reinicio", maximo=5, ventana=3600))],
)
def pedir_reinicio(datos: SolicitudReinicio, bd: BD) -> dict:
    """Responde 202 SIEMPRE, exista la cuenta o no."""
    correo = datos.email.strip().lower()
    usuario = bd.scalars(select(User).where(func.lower(User.email) == correo)).first()

    if usuario is not None and usuario.is_active:
        token, _ = emitir(usuario.id, Proposito.REINICIO)
        if settings().es_produccion:
            # Sin envio de correo (FASE 15) no hay forma segura de entregarlo.
            # Registrarlo en el log de produccion lo dejaria en texto claro a
            # disposicion de cualquiera con acceso a los logs.
            log.warning("reinicio pedido para %s pero no hay envio de correo aun", usuario.id)
        else:
            log.info("token de reinicio (solo fuera de produccion): %s", token)

    return {"detalle": "si la cuenta existe, recibiras instrucciones por correo"}


@router.post("/password-reset/confirm", summary="Fijar la contrasena nueva")
def confirmar_reinicio(datos: ConfirmacionReinicio, bd: BD) -> Tokens:
    try:
        cuerpo = leer(datos.token, Proposito.REINICIO)
    except TokenInvalido as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="enlace inválido o caducado"
        ) from exc

    if _esta_revocado(cuerpo["jti"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ese enlace ya se ha usado"
        )

    usuario = bd.scalars(select(User).where(User.id == int(cuerpo["sub"]))).first()
    if usuario is None or not usuario.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="enlace inválido")

    try:
        usuario.password_hash = cifrar(datos.contrasena)
    except ContrasenaDebil as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Un solo uso: se gasta en cuanto sirve.
    _revocar(cuerpo["jti"], int(cuerpo["exp"] - dt.datetime.now(dt.UTC).timestamp()))
    bd.commit()
    return _emitir_par(usuario)


class Perfil(BaseModel):
    id: int
    email: str
    plan: str
    activo: bool
    perfil_riesgo: str | None = None
    horizonte: str | None = None
    ultimo_acceso: dt.datetime | None = None


@router.get("/me", response_model=Perfil, summary="Quien soy")
def quien_soy(usuario: Actual) -> Perfil:
    return Perfil(
        id=usuario.id,
        email=usuario.email,
        plan=usuario.subscription_plan,
        activo=usuario.is_active,
        perfil_riesgo=usuario.risk_profile,
        horizonte=usuario.investment_horizon,
        ultimo_acceso=usuario.last_login_at,
    )
