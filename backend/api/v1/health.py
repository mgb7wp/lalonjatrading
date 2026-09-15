"""Comprobaciones de salud (§46 del encargo).

`/health` responde a "esta el sistema en pie". `/health/data` respondera a la
pregunta que de verdad importa en una plataforma de datos —que datos hay, de
cuando, de que fuente y con que huecos— y llega en la FASE 3, cuando haya
ingesta que medir. Hasta entonces declara que no esta implementado en lugar de
devolver un verde que no significa nada.

Nota sobre el codigo de estado: `/health` devuelve 200 aunque una dependencia
este caida, y lo dice en el cuerpo. Un 503 haria que un balanceador sacara del
servicio a una API que todavia puede servir de cache, y ademas dejaria sin
respuesta a quien pregunta *que* esta caido.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel

from ...config import settings
from ...db import session as db

router = APIRouter(prefix="/health", tags=["health"])

Estado = Literal["ok", "degradado", "caido"]


class Dependencia(BaseModel):
    nombre: str
    estado: Estado
    detalle: str = ""


class Salud(BaseModel):
    estado: Estado
    version: str
    entorno: str
    dependencias: list[Dependencia]


@router.get("", response_model=Salud, summary="Estado del servicio")
def salud() -> Salud:
    cfg = settings()
    deps: list[Dependencia] = []

    ok_db, error_db = db.comprobar()
    deps.append(
        Dependencia(
            nombre="postgres",
            estado="ok" if ok_db else "caido",
            detalle="" if ok_db else error_db,
        )
    )

    # El nucleo cuantitativo tambien es una dependencia: si su configuracion no
    # valida, la API puede responder pero no puede analizar nada.
    try:
        from estrategia import config as core_config

        c = core_config.cargar()
        n = len(c.reglas.universo.mercados)
        deps.append(Dependencia(nombre="core", estado="ok", detalle=f"{n} mercados configurados"))
    except Exception as e:  # noqa: BLE001
        deps.append(Dependencia(nombre="core", estado="caido", detalle=f"{type(e).__name__}: {e}"))

    caidas = [d for d in deps if d.estado == "caido"]
    if not caidas:
        estado: Estado = "ok"
    elif len(caidas) == len(deps):
        estado = "caido"
    else:
        estado = "degradado"

    return Salud(estado=estado, version=_version(), entorno=cfg.entorno, dependencias=deps)


@router.get(
    "/data",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Frescura y cobertura de los datos (FASE 3)",
)
def salud_datos() -> dict[str, str]:
    return {
        "detalle": "pendiente de la FASE 3 (ingesta). Ver docs/ROADMAP.md",
    }


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("lalonja")
    except PackageNotFoundError:
        return "desconocida"
