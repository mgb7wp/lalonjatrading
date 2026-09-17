"""Dependencias compartidas: quien pide, con que plan y con que limites.

La puerta de plan esta AQUI y en ningun otro sitio. Es el criterio de aceptacion
de la fase, y no es burocracia: repartida por los endpoints, el dia que PRO pase
de 5 a 10 carteras hay que encontrar los siete sitios donde estaba escrita, y el
que se olvide sera el que nadie mire.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import User
from ..db.models.enums import SubscriptionPlan
from ..db.session import sesion
from ..limites import Limites, al_menos, limites_de
from ..seguridad import Proposito, TokenInvalido, leer

BD = Annotated[Session, Depends(sesion)]

#: `auto_error=False` para poder distinguir "no has mandado credenciales" de
#: "las has mandado y no valen". Con el automatico, las dos salen igual y quien
#: integra la API pierde media tarde.
_portador = HTTPBearer(auto_error=False, scheme_name="Bearer")

NO_AUTENTICADO = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="hace falta iniciar sesion",
    headers={"WWW-Authenticate": "Bearer"},
)


def usuario_actual(
    bd: BD,
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_portador)] = None,
) -> User:
    if credenciales is None:
        raise NO_AUTENTICADO
    try:
        cuerpo = leer(credenciales.credentials, Proposito.ACCESO)
    except TokenInvalido as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token invalido o caducado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    usuario = bd.scalars(select(User).where(User.id == int(cuerpo["sub"]))).first()
    if usuario is None or not usuario.is_active:
        # Mismo error para "no existe" y "esta desactivado": distinguirlos
        # confirmaria que una cuenta existe a quien tenga un token viejo.
        raise NO_AUTENTICADO
    return usuario


Actual = Annotated[User, Depends(usuario_actual)]


def limites_actuales(usuario: Actual) -> Limites:
    """Los limites del plan de quien pide. La UNICA puerta a `LIMITES`."""
    return limites_de(usuario.subscription_plan)


MisLimites = Annotated[Limites, Depends(limites_actuales)]


def requiere_plan(minimo: SubscriptionPlan):
    """Dependencia que exige un plan minimo.

    Se usa asi:  `dependencies=[Depends(requiere_plan(SubscriptionPlan.PRO))]`
    """

    def dependencia(usuario: Actual) -> User:
        if not al_menos(usuario.subscription_plan, minimo):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"esta funcion necesita el plan {minimo.value} o superior",
            )
        return usuario

    return dependencia


def comprobar_cupo(actuales: int, maximo: int, que: str) -> None:
    """Un cupo alcanzado es 409, no 403.

    403 significa "no puedes"; aqui si puedes, pero ya has gastado lo tuyo. La
    diferencia importa para quien integra: uno se arregla cambiando de plan y el
    otro borrando algo.
    """
    if actuales >= maximo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"has alcanzado el maximo de {maximo} {que} de tu plan",
        )
