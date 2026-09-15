# Despliegue

Cómo se levanta el proyecto en local y qué hace falta para ponerlo en un
servidor. El despliegue de producción completo es FASE 18; esto cubre lo que ya
existe.

## Desarrollo

### Con Docker (recomendado)

```bash
cp .env.example .env
# genera un secreto de verdad, aunque sea para desarrollo:
python -c "import secrets; print(secrets.token_urlsafe(48))"   # -> JWT_SECRET

docker compose up --build
```

Levanta cuatro servicios: `postgres`, `redis`, `api` y `worker`.

- API: <http://localhost:8000/api/v1/health>
- Documentación OpenAPI: <http://localhost:8000/docs>

El frontend va aparte porque en desarrollo compensa tenerlo fuera del
contenedor (recarga instantánea, sin rebuild):

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev        # http://localhost:3000
```

### Sin Docker

El motor cuantitativo **no necesita ni base de datos ni Docker**, y eso es
deliberado: es la regla de dependencias de [ARCHITECTURE.md](ARCHITECTURE.md) §4.

```bash
pip install -e ".[dev]"                 # solo el motor
estrategia --proveedor sintetico backtest --periodo diseno
```

Para la plataforma:

```bash
pip install -e ".[backend,workers,dev]"
uvicorn backend.main:app --reload
```

Sin Postgres levantado la API arranca igualmente y `/health` informa de que la
base de datos no responde. Está escrito así a propósito: un health check que se
cae con su dependencia no sirve para diagnosticar nada.

## Tests

```bash
pytest -q                       # todo
pytest tests/test_anti_sesgo.py # los que más importan
ruff check . && ruff format --check .
```

Los tests no tocan la red ni una base de datos: el motor corre sobre el
proveedor sintético, que es determinista. Un test que fallara sólo los martes
porque el mercado hizo algo raro no serviría para nada.

## Configuración

Dos configuraciones que no se mezclan:

| Qué | Dónde | Por qué ahí |
|---|---|---|
| Parámetros de estrategia (pesos, umbrales, universo, costes) | `config/*.yaml`, versionado | Un backtest no es reproducible si sus parámetros dependen del entorno |
| Despliegue y secretos (BD, Redis, claves, JWT) | variables de entorno / `.env` | Cambian entre máquinas y no pueden estar en el repositorio |

`.env` está en `.gitignore`. `.env.example` es la plantilla y sí se versiona.
En producción la API **se niega a arrancar sin `JWT_SECRET`**, para que el fallo
ocurra al desplegar y no la primera vez que alguien se autentique.

## Producción (FASE 18)

Objetivo de coste: un VPS de ~10 €/mes, que es la restricción de §50 del
encargo. El `docker-compose` de cuatro servicios cabe ahí.

Pendiente de esa fase:

- Reverse proxy con TLS (Caddy o Traefik: renuevan el certificado solos)
- Backups de Postgres verificados — un backup que nunca se ha restaurado no es un backup
- Migraciones Alembic en el arranque del despliegue, no a mano
- Monitorización y alertas sobre `/health` y `/health/data`
- Rotación de secretos
- **Cambio de proveedor de datos a uno con licencia comercial** (riesgo RD-1 de
  [PROJECT_PLAN.md](PROJECT_PLAN.md)): yfinance sirve para desarrollar y
  backtestear, no para facturar
