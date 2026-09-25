"""Aplicacion FastAPI.

Fabrica (`crear_app`) en lugar de una instancia global para que los tests puedan
construir una aplicacion limpia con otra configuracion, sin que el orden de los
imports decida nada.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import router as router_v1
from .config import settings

DESCRIPCION = """
Analisis cuantitativo de mercados. Los scores salen de un motor deterministico y
reproducible; la IA generativa solo los explica y nunca produce un numero.

**Esto no es asesoramiento financiero.** La plataforma publica informacion y
analisis general. No emite recomendaciones personalizadas ni tiene en cuenta la
situacion particular de quien la consulta.
"""


def crear_app() -> FastAPI:
    cfg = settings()
    app = FastAPI(
        title="La Lonja Trading API",
        description=DESCRIPCION,
        version="0.3.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origenes,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(router_v1, prefix="/api/v1")
    return app


app = crear_app()
