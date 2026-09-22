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

# Mientras el trabajo siga en la rama de desarrollo, hay que pedirla
# explicitamente: `main` no tiene ni el frontend desplegable ni el compose de
# produccion, asi que un despliegue desde ahi falla sin decir por que.
git checkout claude/saas-investment-analysis-ai-rix1km
```

En un servidor con menos de 2 GB de RAM, la construccion del frontend puede
morir por falta de memoria (`next build` es lo que mas consume). Si pasa, un
fichero de intercambio lo resuelve:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
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
"${cp[@]}" exec api python scripts/calculate_signals.py
```

A partir de ahí el `worker` la mantiene al día: descarga cada mercado tras su
cierre y puntúa el universo entero tras el último, sobre las 19:30 de São Paulo.

### 5b. Recalcular hacia atrás, cuando entran valores nuevos

Los scores tienen fecha. Si se da de alta un mercado —o se amplía uno— después
del último cálculo, esos valores **tienen datos y no aparecen en los rankings**
hasta que se vuelva a puntuar: `/rankings?mercado=es` devuelve `n: 0` con la
base llena. Pasó el 22/09/2026 con España, Alemania e India.

No hace falta esperar al cierre de la tarde:

```bash
"${cp[@]}" exec api python scripts/calculate_scores.py
"${cp[@]}" exec api python scripts/calculate_signals.py
```

Y para comprobar que ha surtido efecto, que es lo que de verdad cierra la
operación:

```bash
curl -s https://$DOMINIO/api/v1/rankings | grep -o '"fecha_datos":"[^"]*"'
curl -s "https://$DOMINIO/api/v1/rankings?mercado=es" | grep -o '"n":[0-9]*'
```

La primera tiene que dar la fecha de hoy y la segunda, un número mayor que cero.

### Alternativa: Cloudflare Tunnel (sin IP pública)

Sirve para desplegar en una máquina que no tiene IP pública: un portátil, un
mini-PC, una Raspberry Pi o un VPS detrás de NAT. El túnel sale *desde* la
máquina hacia Cloudflare, así que no hay que abrir puertos en el router ni
tener IP fija, y el certificado deja de ser cosa nuestra: lo termina Cloudflare
en su borde.

De paso, la máquina no expone **nada** a Internet: en esta variante ni siquiera
Caddy publica el 80 y el 443.

El coste es el obvio: **el sitio solo está disponible mientras esa máquina esté
encendida.**

1. En Cloudflare, **Zero Trust → Networks → Tunnels → Create a tunnel**,
   tipo *Cloudflared*. Copia el token que muestra y ponlo en `.env` como
   `CLOUDFLARE_TUNNEL_TOKEN`. Es un secreto: permite publicar en tu dominio.
2. En ese mismo túnel, **Public Hostnames**, añade dos rutas:

   | Subdomain | Domain               | Service            |
   |-----------|----------------------|--------------------|
   | *(vacío)* | `lalonja-trading.com`| `http://caddy:80`  |
   | `www`     | `lalonja-trading.com`| `http://caddy:80`  |

   El servicio apunta a Caddy, no a `web` ni a `api`: es Caddy quien decide que
   `/api` va a la API y el resto al frontend.
3. Despliega:

   ```bash
   ./despliegue/desplegar.sh --tunel
   ```

Cloudflare crea los registros DNS solo, así que aquí **no** hay que tocar nada
de nubes grises ni naranjas: eso solo aplica al despliegue con Caddy haciendo el
TLS.

El paso 5 (primera carga de datos) se aplica igual, añadiendo
`-f docker-compose.tunel.yml` a los comandos.

### Por qué no todo en Cloudflare

Es la pregunta razonable, y la respuesta es que Cloudflare puede con el frontend
pero no con el motor:

- **No hay Postgres gestionado.** D1 es SQLite, e Hyperdrive no aloja una base
  de datos: acelera la conexión a una tuya alojada en otro sitio. El esquema usa
  particionado declarativo, `COPY` y `UPSERT` de Postgres, más Alembic.
- **El pipeline no cabe en un Worker.** Es pandas sobre cientos de miles de
  filas; los Workers están pensados para milisegundos de CPU.
- **Los Containers se duermen por inactividad** y requieren plan de pago. Para
  Postgres, que tiene que estar siempre vivo, es el modelo equivocado.

Cloudflare vende CDN y cómputo efímero; esto necesita un proceso largo con
estado. Lo que sí aporta, y es mucho, es DNS, TLS y el túnel.

### Copias de seguridad

`despliegue/copia_seguridad.sh`. Se instala como temporizador de systemd y corre
a diario:

```bash
cp despliegue/systemd/lalonja-copia.* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now lalonja-copia.timer
systemctl start lalonja-copia.service   # la primera, ahora, para verla funcionar
```

Comprobar: `systemctl list-timers lalonja-copia.timer` y
`journalctl -u lalonja-copia.service -n 50`.

**La verificación va dentro del script y no es opcional.** Un volcado que nadie
ha restaurado nunca no es una copia de seguridad: es un fichero. El caso que
importa —`pg_dump` que termina con éxito y produce algo irrecuperable— no lo
detecta ningún `echo $?`. Cada copia:

1. Se vuelca con `pg_dump -Fc`.
2. Se comprueba que no está vacía.
3. **Se restaura de verdad** en una base de usar y tirar.
4. **Se cuentan las filas** (tablas, valores, precios). Esto separa «el fichero
   se deja leer» de «los datos están»: un volcado de un esquema vacío se
   restaura sin un solo error.
5. Solo entonces se rotan las antiguas. Al revés, una copia mala podría empujar
   fuera a la última buena.

Si algo de eso falla, el script sale con error, **conserva el volcado para
diagnosticar y no rota nada**.

Deja también `ultima-copia-correcta` con la fecha de la última copia verificada:
sin esa marca, un temporizador que dejó de ejecutarse no se distingue de uno que
funciona.

Retención: 14 copias (`LALONJA_BACKUP_RETENCION`). Destino:
`/var/backups/lalonja` (`LALONJA_BACKUP_DIR`).

#### Restaurar

```bash
./despliegue/copia_seguridad.sh --restaurar /var/backups/lalonja/lalonja-FECHA.dump
```

Pide escribir el nombre de la base para confirmar antes de sobrescribir nada.

#### Lo que esto todavía NO cubre

Las copias viven **en el mismo disco que la base de datos**. Eso protege de un
borrado accidental o de una migración que sale mal, que son los casos
frecuentes, pero **no de perder el servidor**. Sacarlas de la máquina es el
siguiente paso: Cloudflare R2 tiene 10 GB gratis y encaja bien, a cambio de
gestionar un token.

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
