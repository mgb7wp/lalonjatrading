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

## Producción

Un VPS pequeño (2 vCPU / 4 GB, ~6-10 €/mes) sostiene los seis servicios. Esa es
la restricción de coste de §50 del encargo.

### Qué se levanta

| Servicio   | Puerto público | Qué hace                                   |
|------------|----------------|--------------------------------------------|
| `caddy`    | 80, 443        | TLS (Let's Encrypt) y proxy inverso        |
| `web`      | —              | Next.js, servido en `/`                    |
| `api`      | —              | FastAPI, servido en `/api/*` y `/docs`     |
| `worker`   | —              | Pipeline diario (APScheduler)              |
| `postgres` | —              | Base de datos                              |
| `redis`    | —              | Caché                                      |

Solo Caddy se asoma a Internet. En el compose de producción, Postgres, Redis y
la API dejan de publicar puertos: en un VPS con IP pública, un `5432:5432` es
una base de datos abierta al mundo, y los escáneres la encuentran en horas.

### 1. Servidor

Cualquier proveedor con Ubuntu 24.04 vale (Hetzner, DigitalOcean, OVH...).

```bash
ssh root@IP_DEL_SERVIDOR
curl -fsSL https://get.docker.com | sh          # Docker + Compose v2 al día
apt install -y git
git clone https://github.com/mgb7wp/lalonjatrading.git
cd lalonjatrading
```

### 2. Configuración

```bash
cp .env.produccion.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET
nano .env
```

`DOMINIO`, `ACME_EMAIL`, `POSTGRES_PASSWORD` y `JWT_SECRET` son obligatorios; el
script de despliegue se niega a continuar si falta alguno.

### 3. DNS en Cloudflare

En el panel de Cloudflare, en **DNS → Records**:

| Tipo | Nombre | Contenido        | Proxy       |
|------|--------|------------------|-------------|
| A    | `@`    | IP del servidor  | **DNS only** |
| A    | `www`  | IP del servidor  | **DNS only** |

**La nube tiene que estar gris, no naranja, la primera vez.** Caddy pide el
certificado a Let's Encrypt con el reto HTTP-01, que consiste en servir un
fichero en el puerto 80 del dominio. Con la nube naranja, Cloudflare intercepta
esa petición y Caddy se queda reintentando indefinidamente: el sitio no levanta
y el log no dice nada más claro que "obtaining certificate".

Una vez el sitio responda por HTTPS, se puede activar el proxy (nube naranja) si
se quiere caché y protección DDoS. Al hacerlo, en **SSL/TLS → Overview** hay que
poner el modo en **Full (strict)**. Con "Flexible" Cloudflare habla con el
servidor por HTTP mientras Caddy redirige a HTTPS, y el resultado es un bucle de
redirecciones.

### 4. Desplegar

```bash
./despliegue/desplegar.sh
```

Comprueba `.env` y la versión de Compose, construye, levanta y espera a que la
API responda. Es idempotente: se ejecuta igual en cada actualización.

Para actualizar:

```bash
git pull && ./despliegue/desplegar.sh
```

### 5. Primera carga de datos

El servidor arranca con la base vacía: `/markets` devolverá los mercados pero
con cero valores. La ingesta inicial se lanza a mano una vez:

```bash
cp=(docker compose -f docker-compose.yml -f docker-compose.produccion.yml)
"${cp[@]}" exec api python scripts/update_market_data.py
"${cp[@]}" exec api python scripts/calculate_scores.py
```

A partir de ahí el `worker` la mantiene al día.

### Qué se ve hoy

Conviene no llamarse a engaño: el frontend actual es el MVP de la FASE 6 —una
página con el estado del servicio y la tabla de mercados—. La interfaz de verdad
es la FASE 17. Lo que este despliegue demuestra es que la tubería entera
funciona de punta a punta con TLS y dominio propio, no que el producto esté
terminado.

### Pendiente

- Backups de Postgres verificados — un backup que nunca se ha restaurado no es un backup
- Monitorización y alertas sobre `/health` y `/health/data`
- Rotación de secretos
- Despliegue automático desde CI en lugar de `git pull` por SSH
- **Cambio de proveedor de datos a uno con licencia comercial** (riesgo RD-1 de
  [PROJECT_PLAN.md](PROJECT_PLAN.md)): yfinance sirve para desarrollar y
  backtestear, no para facturar
