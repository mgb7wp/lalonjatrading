"""Configuracion de la plataforma, toda por entorno.

Dos configuraciones conviven a proposito y no se mezclan:

- La de **estrategia** (pesos, umbrales, universo, costes) vive en
  `config/*.yaml`, versionada, porque forma parte del modelo: un backtest no es
  reproducible si sus parametros dependen del entorno donde corre.
- La de **despliegue** (esta) vive en variables de entorno, porque cambia entre
  la maquina de uno y produccion y porque contiene secretos.

Meter la primera aqui haria irreproducible el motor; meter la segunda en el YAML
acabaria con una clave de API en el repositorio.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    entorno: str = "desarrollo"

    database_url: str = "postgresql+psycopg://lalonja:lalonja@localhost:5432/lalonja"
    redis_url: str = "redis://localhost:6379/0"

    # Sin valor por defecto utilizable a proposito: que un despliegue sin
    # JWT_SECRET falle al arrancar y no cuando alguien se autentique.
    jwt_secret: str = ""
    jwt_algoritmo: str = "HS256"
    jwt_minutos: int = 30

    cors_origenes: list[str] = ["http://localhost:3000"]

    # Capa LLM (FASE 16). Sin clave, la API arranca igual y las explicaciones se
    # declaran no disponibles: un despliegue sin IA es un despliegue valido, no
    # uno roto. El modelo se puede cambiar sin tocar codigo.
    anthropic_api_key: str = ""
    llm_modelo: str = "claude-opus-5"
    llm_timeout_segundos: float = 60.0

    @property
    def es_produccion(self) -> bool:
        return self.entorno == "produccion"


def version() -> str:
    """La version instalada del paquete (`pyproject.toml`). La publican la
    documentacion de la API y `/health`; antes la primera llevaba un numero
    escrito a mano que se habia quedado dos versiones atras."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as version_de

    try:
        return version_de("lalonja")
    except PackageNotFoundError:
        return "desconocida"


@lru_cache
def settings() -> Settings:
    s = Settings()
    if s.es_produccion and not s.jwt_secret:
        raise RuntimeError("JWT_SECRET es obligatorio en produccion")
    return s
