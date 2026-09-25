# Normas del proyecto para Claude Code

## Quién usa esto
- **El dueño no es programador.** Explícale los resultados en español y en lenguaje llano: qué ha cambiado, por qué importa y qué tiene que hacer él, si tiene que hacer algo.
- **Qué es el proyecto:** La Lonja (`lalonja-trading.com`). De momento es de **uso propio**: el dueño opera en eToro con 1.000 € de capital inicial, primero en simulado.
- **Idiomas:**
  - el motor (`core/estrategia/`), sus mensajes y la documentación van en español;
  - la plataforma (`backend/`, `workers/`, `ml/`, `frontend/`) va en inglés. La traducción entre los dos está en `docs/GLOSARIO.md` (decisión D-14).

## El plan
- **`PLAN.md` es la lista de tareas.** Cuando te pidan "haz la tarea X", léela allí antes de empezar.
- **Al terminar una tarea,** márcala en la sección "Hecho" de `PLAN.md`. Si cambia el estado de una fase, actualiza también `docs/ROADMAP.md`.
- **Una tarea por cambio.** No mezcles tareas salvo que te lo pidan.

## Jerarquía de documentos
1. **`ESTRATEGIA.md`** es la fuente de verdad de la estrategia. Si el código y el documento no coinciden, manda el documento.
2. **`SUPUESTOS.md`** recoge cómo se resolvió lo que el documento no decide.
3. **`docs/PROJECT_PLAN.md`** tiene las decisiones de la plataforma (D-1 a D-14) y sus riesgos.

## Reglas que no se saltan
- **Parámetros:** todos viven en `config/`. Nada de números sueltos en el código.
- **Cambios que alteran resultados:**
  - una fila en el registro de cambios de `ESTRATEGIA.md`;
  - su explicación en `SUPUESTOS.md` si es una interpretación;
  - si cambian los scores, una versión nueva en `config/modelos.yaml`.
- **Periodo de validación:**
  - no ejecutes `backtest --periodo validacion` ni `--periodo todo` sin permiso explícito del dueño. En `scripts/run_backtest.py` son `validacion` y `completo`, y tampoco se usan sin ese permiso. Tampoco lo mires por otra vía.
  - cada consulta lo gasta.
  - empieza en `validacion.fecha_corte` (2020-09-01), que es fija.
- **Anticipación:** los tests de `tests/test_anti_sesgo.py` son condición de entrada. Si uno falla, ningún resultado vale. Lo mismo para cualquier cálculo de la plataforma que use fechas: nada puede usar un dato publicado después del día que se calcula.
- **Capas:** el motor no importa nada de la plataforma (`tests/test_arquitectura.py`), y dentro del motor se respeta el orden que comprueba `tests/test_motor.py`.
- **Recomendaciones personalizadas** (qué comprar o vender según la cartera del usuario): van detrás de `PERSONALIZATION_ENABLED` (decisión D-6).
- **Datos sintéticos:** nunca publiques un informe hecho con ellos.
- **Secretos:** nunca subas claves al repositorio (`EODHD_API_KEY`, `ANTHROPIC_API_KEY`, `JWT_SECRET`, tokens de Cloudflare). Van en `.env` o en variables de entorno.

## Cómo trabajar
- **Instalación:** `pip install -e ".[backend,workers,dev]"` (Python 3.11 o superior). El frontend está en `frontend/` (Node 20).
- **Antes de dar algo por terminado**, lo mismo que el CI (`.github/workflows/ci.yml`):
  - `ruff check .`
  - `ruff format --check .`
  - `pytest`
- **Cada arreglo lleva su test.**
- **Tests de base de datos:** necesitan un Postgres de usar y tirar en `TEST_DATABASE_URL`. Sin él se saltan, y el CI los ejecuta.
- **Configuración de los tests:** usan su propia copia, `tests/config_prueba/`, no `config/`.
  - Un test que compruebe la coherencia de `config/` usa la fixture `cfg_real`.
  - Si el código exige una clave nueva de configuración, añádela también a la copia de los tests.
- **Sin red:** `estrategia --proveedor sintetico ...`. La opción `--proveedor` va antes del subcomando. Sin ella se usa el reparto de fuentes de `reglas.yaml`, que pide datos reales.
- **Datos reales:** desde la nube, Yahoo Finance suele devolver el error 429. Lo que necesite descargar datos se ejecuta en el servidor.
- **Servidor** (Hetzner, detrás de Cloudflare Tunnel):
  - no tienes acceso. Da al dueño los comandos exactos para pegar;
  - el procedimiento está en `docs/DEPLOYMENT.md`, y el servidor usa `main`.
- **Ramas:** trabaja en la rama indicada para la sesión y no fusiones en `main` sin que el dueño lo pida.
