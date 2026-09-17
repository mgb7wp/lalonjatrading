"""Limitacion de peticiones y limites de plan.

## Un solo sitio, que es el criterio de aceptacion de la fase

Los limites de plan viven en `LIMITES` y se aplican con una unica dependencia.
Repartidos por los endpoints, el dia que PRO pase de 10 a 20 carteras habra que
encontrar los siete sitios donde estaba escrito, y el que se olvide sera el que
nadie mire.

## Por que el limitador vive en Redis y no en memoria

Con dos procesos de uvicorn, un contador en memoria permite el doble de intentos
del que dice permitir, y con cuatro, el cuadruple. El limite deja de significar
lo que pone. Redis lo comparte.

**Si Redis no esta, se falla cerrado**: se rechaza la peticion en lugar de
dejarla pasar. Un limitador que se apaga solo cuando su dependencia cae es
exactamente lo que no quieres el dia que alguien tumba Redis a proposito. El
coste es que un fallo de Redis tira el login; el beneficio es que no se
convierte en barra libre para probar contrasenas.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from .config import settings
from .db.models.enums import SubscriptionPlan

log = logging.getLogger("limites")

#: Orden de los planes. Lo usa la puerta de plan para "este endpoint pide PRO o
#: mas", que es lo que se quiere decir casi siempre.
ORDEN_PLANES = (SubscriptionPlan.FREE, SubscriptionPlan.PRO, SubscriptionPlan.PREMIUM)


@dataclass(frozen=True, slots=True)
class Limites:
    """Lo que puede hacer cada plan. Todos empiezan en FREE (§50)."""

    carteras: int
    watchlists: int
    valores_por_watchlist: int
    alertas: int
    screeners_guardados: int
    peticiones_por_minuto: int
    explicaciones_ia_al_dia: int


LIMITES: dict[str, Limites] = {
    SubscriptionPlan.FREE.value: Limites(
        carteras=1,
        watchlists=1,
        valores_por_watchlist=10,
        alertas=3,
        screeners_guardados=3,
        peticiones_por_minuto=60,
        # Cero, y no uno: cada explicacion cuesta dinero de verdad en tokens, y
        # §50 pone el control de coste como restriccion, no como aspiracion.
        explicaciones_ia_al_dia=0,
    ),
    SubscriptionPlan.PRO.value: Limites(
        carteras=5,
        watchlists=5,
        valores_por_watchlist=50,
        alertas=25,
        screeners_guardados=25,
        peticiones_por_minuto=300,
        explicaciones_ia_al_dia=50,
    ),
    SubscriptionPlan.PREMIUM.value: Limites(
        carteras=25,
        watchlists=25,
        valores_por_watchlist=250,
        alertas=100,
        screeners_guardados=100,
        peticiones_por_minuto=1200,
        explicaciones_ia_al_dia=500,
    ),
}


def limites_de(plan: str) -> Limites:
    """Los limites de un plan. Un plan desconocido cae a FREE, no a "sin limite".

    Equivocarse hacia el lado restrictivo cuesta una queja; hacia el otro, una
    factura.
    """
    return LIMITES.get(plan, LIMITES[SubscriptionPlan.FREE.value])


def al_menos(plan_usuario: str, minimo: SubscriptionPlan) -> bool:
    try:
        return ORDEN_PLANES.index(SubscriptionPlan(plan_usuario)) >= ORDEN_PLANES.index(minimo)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Limitador de peticiones
# ---------------------------------------------------------------------------


class _SinRedis(RuntimeError):
    pass


_cliente = None


def _redis():
    global _cliente
    if _cliente is None:
        import redis

        _cliente = redis.Redis.from_url(settings().redis_url, socket_timeout=1)
    return _cliente


def _contar(clave: str, ventana: int) -> int:
    """Incrementa el contador de la ventana y devuelve cuantas van.

    Ventana fija y no deslizante: es una linea de codigo frente a un sorted set,
    y para frenar fuerza bruta sobra. Su defecto conocido es que permite el
    doble del limite justo en el cambio de ventana; para un login con 5 intentos
    por minuto, eso son 10 intentos en un instante, no una barra libre.
    """
    try:
        r = _redis()
        cubo = int(time.time()) // ventana
        k = f"limite:{clave}:{cubo}"
        tuberia = r.pipeline()
        tuberia.incr(k)
        tuberia.expire(k, ventana * 2)
        return int(tuberia.execute()[0])
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de Redis cuenta igual
        raise _SinRedis(str(exc)) from exc


def _identidad(peticion: Request) -> str:
    """Quien hace la peticion, a efectos del limite.

    `X-Forwarded-For` se usa solo porque delante hay un proxy inverso nuestro
    (Caddy) y, en produccion, Cloudflare. Sin proxy delante seria una cabecera
    que cualquiera puede escribir, y el limitador se saltaria cambiandola en
    cada peticion.
    """
    reenviado = peticion.headers.get("x-forwarded-for")
    if reenviado:
        return reenviado.split(",")[0].strip()
    return peticion.client.host if peticion.client else "desconocido"


def limitar(nombre: str, maximo: int, ventana: int = 60):
    """Dependencia de FastAPI que limita por IP.

    `nombre` separa los contadores: gastar los intentos de login no puede dejar
    a nadie sin poder registrarse.
    """

    def dependencia(peticion: Request) -> None:
        clave = f"{nombre}:{_identidad(peticion)}"
        try:
            n = _contar(clave, ventana)
        except _SinRedis as exc:
            log.error("limitador sin Redis, se rechaza la peticion: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="servicio de limitacion no disponible; intentalo en un momento",
            ) from exc
        if n > maximo:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"demasiadas peticiones: maximo {maximo} cada {ventana} segundos",
                headers={"Retry-After": str(ventana)},
            )

    return dependencia
