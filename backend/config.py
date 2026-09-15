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
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    entorno: str = "desarrollo"
    debug: bool = False

    database_url: str = "postgresql+psycopg://lalonja:lalonja@localhost:5432/lalonja"
    redis_url: str = "redis://localhost:6379/0"

    # Sin valor por defecto utilizable a proposito: que un despliegue sin
    # JWT_SECRET falle al arrancar y no cuando alguien se autentique.
    jwt_secret: str = ""
    jwt_algoritmo: str = "HS256"
    jwt_minutos: int = 30

    cors_origenes: list[str] = ["http://localhost:3000"]

    # Directorio de datos del nucleo (Parquet). El nucleo lo gestiona; la API
    # solo necesita saber donde esta para informar de frescura en /health/data.
    datos_dir: Path = RAIZ / "datos"

    @property
    def es_produccion(self) -> bool:
        return self.entorno == "produccion"


@lru_cache
def settings() -> Settings:
    s = Settings()
    if s.es_produccion and not s.jwt_secret:
        raise RuntimeError("JWT_SECRET es obligatorio en produccion")
    return s
