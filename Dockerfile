# Imagen unica para API y worker: mismo codigo, distinto comando. Dos imagenes
# se desincronizan en cuanto una se reconstruye y la otra no, y el sintoma es un
# worker escribiendo scores con una version del motor distinta de la que la API
# cree estar sirviendo.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Las dependencias en una capa aparte de la de codigo: cambiar un .py no obliga
# a recompilar pandas.
COPY pyproject.toml ./
COPY core/estrategia/__init__.py core/estrategia/__init__.py
RUN pip install --no-cache-dir ".[backend,workers]" || true

COPY . .
RUN pip install --no-cache-dir -e ".[backend,workers]"

# Sin root: si alguien encuentra una ejecucion remota, que no la encuentre como
# root.
RUN useradd --create-home --uid 10001 lonja && chown -R lonja:lonja /app
USER lonja

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
