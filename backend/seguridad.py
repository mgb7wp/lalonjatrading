"""Contrasenas y tokens. El unico sitio donde se hace criptografia.

Esta concentrado aqui a proposito: lo que esta repartido se reimplementa mal.
Una segunda funcion de hash "para ese caso especial" es como aparece un sitio
donde las contrasenas se guardan con SHA-256.

## Por que Argon2id y no bcrypt

Argon2id es el ganador de la Password Hashing Competition y el que recomienda
OWASP. Frente a bcrypt, resiste ademas los ataques con hardware especializado:
bcrypt solo castiga el tiempo de CPU, y una GPU tiene miles de nucleos. Argon2
exige MEMORIA, que es lo que una GPU no puede multiplicar barato.

Los parametros salen del perfil que recomienda OWASP (19 MiB, 2 iteraciones,
1 hilo). Van nombrados y no por defecto para que se vean: son la diferencia
entre un hash caro y uno decorativo.

## Los tokens llevan proposito

Cada token dice para que sirve (`acceso`, `refresco`, `reinicio`). Sin eso, un
token de refresco vale como token de acceso y un token de reinicio de contrasena
—que se envia por correo, el canal menos seguro— sirve para llamar a cualquier
endpoint. Es una linea de codigo y evita una escalada entera.
"""

from __future__ import annotations

import datetime as dt
import enum
import secrets
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import settings

#: Perfil recomendado por OWASP para Argon2id.
_HASHER = PasswordHasher(memory_cost=19456, time_cost=2, parallelism=1)

#: Minima aceptable. Larga antes que retorcida: la longitud es lo que de verdad
#: encarece un ataque, y exigir simbolos empuja a la gente a `Passw0rd!`.
LONGITUD_MINIMA = 12

#: Cuanto viven los tokens. El de acceso, poco, porque viaja en cada peticion y
#: no se puede revocar; el de refresco, mas, porque se usa una vez cada mucho y
#: SI se puede revocar.
DIAS_REFRESCO = 30
MINUTOS_REINICIO = 30


class Proposito(enum.StrEnum):
    ACCESO = "acceso"
    REFRESCO = "refresco"
    REINICIO = "reinicio"


class TokenInvalido(Exception):
    """Firma mala, caducado, o con un proposito que no es el que se esperaba."""


class ContrasenaDebil(ValueError):
    """No cumple el minimo. El mensaje dice que falta, sin adivinanzas."""


def validar_contrasena(contrasena: str) -> None:
    if len(contrasena) < LONGITUD_MINIMA:
        raise ContrasenaDebil(
            f"la contrasena tiene que tener al menos {LONGITUD_MINIMA} caracteres"
        )
    # Una comprobacion de espacios en blanco a los lados, que es un error de
    # copiar y pegar que luego impide entrar sin que nadie entienda por que.
    if contrasena != contrasena.strip():
        raise ContrasenaDebil("la contrasena no puede empezar ni acabar con espacios")


def cifrar(contrasena: str) -> str:
    validar_contrasena(contrasena)
    return _HASHER.hash(contrasena)


def comprobar(contrasena: str, hash_guardado: str) -> bool:
    """Verifica sin filtrar por que ha fallado.

    Devuelve `False` tanto si la contrasena es otra como si el hash guardado
    esta corrupto. Distinguirlo hacia fuera no ayuda a nadie salvo a quien
    ataca.
    """
    try:
        return _HASHER.verify(hash_guardado, contrasena)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def necesita_recifrado(hash_guardado: str) -> bool:
    """Si el hash se hizo con parametros mas debiles que los de ahora.

    Sirve para subir el coste sin pedirle a nadie que cambie de contrasena: al
    entrar bien, se recifra con los parametros nuevos.
    """
    try:
        return _HASHER.check_needs_rehash(hash_guardado)
    except InvalidHashError:
        return True


def _ahora() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def emitir(
    sujeto: str | int,
    proposito: Proposito,
    *,
    vida: dt.timedelta | None = None,
    extra: dict | None = None,
) -> tuple[str, str]:
    """Devuelve `(token, jti)`.

    El `jti` se devuelve aparte porque quien llama necesita poder anotarlo para
    revocarlo despues. Sacarlo descodificando el token otra vez seria trabajo
    repetido y una ocasion mas de equivocarse.
    """
    cfg = settings()
    if not cfg.jwt_secret:
        raise RuntimeError("JWT_SECRET no configurado: no se pueden emitir tokens")

    if vida is None:
        vida = {
            Proposito.ACCESO: dt.timedelta(minutes=cfg.jwt_minutos),
            Proposito.REFRESCO: dt.timedelta(days=DIAS_REFRESCO),
            Proposito.REINICIO: dt.timedelta(minutes=MINUTOS_REINICIO),
        }[proposito]

    ahora = _ahora()
    jti = uuid.uuid4().hex
    cuerpo = {
        "sub": str(sujeto),
        "uso": str(proposito),
        "jti": jti,
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + vida).timestamp()),
        **(extra or {}),
    }
    return jwt.encode(cuerpo, cfg.jwt_secret, algorithm=cfg.jwt_algoritmo), jti


def leer(token: str, proposito: Proposito) -> dict:
    """Descodifica y EXIGE el proposito. Cualquier fallo es `TokenInvalido`."""
    cfg = settings()
    try:
        cuerpo = jwt.decode(
            token,
            cfg.jwt_secret,
            algorithms=[cfg.jwt_algoritmo],
            options={"require": ["exp", "sub", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenInvalido(str(exc)) from exc

    if cuerpo.get("uso") != str(proposito):
        # Sin esta comprobacion, un token de refresco vale como token de acceso
        # y uno de reinicio —que viaja por correo— sirve para todo.
        raise TokenInvalido(f"token de proposito '{cuerpo.get('uso')}', se esperaba '{proposito}'")
    return cuerpo


def token_opaco() -> str:
    """Secreto aleatorio para lo que no deba ser un JWT."""
    return secrets.token_urlsafe(32)
