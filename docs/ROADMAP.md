# Roadmap

Fases, entregables y criterio de aceptación. El orden sigue el de §56 del
encargo, reordenado por una razón concreta: el motor cuantitativo **ya existe y
está probado** (ver [PROJECT_PLAN.md](PROJECT_PLAN.md) §0), así que las fases
4 a 7 del encargo —indicadores, análisis fundamental, scoring, backtesting— no
son construcción desde cero sino extracción, extensión y conexión.

Una fase no se da por terminada si sus tests no pasan y su documentación no está
actualizada. No hay estimaciones en días: dependen de dedicación y no aportan.

---

## FASE 0 — Análisis y diseño ✅ COMPLETADA

Analizar el encargo, detectar inconsistencias, medir riesgos, fijar arquitectura.

**Entregables:** `PROJECT_PLAN.md`, `ARCHITECTURE.md`, `DATA_SOURCES.md`,
`ROADMAP.md`.
**Aceptación:** 14 decisiones registradas, 14 inconsistencias resueltas, riesgos
de datos y legales identificados con mitigación.

---

## FASE 1 — Esqueleto de plataforma ✅ COMPLETADA

Envolver el motor existente en una aplicación desplegable.

- `src/estrategia` → `core/estrategia`, sin tocar el paquete de Python: la
  carpeta marca la frontera, renombrar el paquete no aportaba nada
- `docker-compose`: postgres, redis, api, worker (+ healthchecks)
- FastAPI con `/health`, `/markets`, OpenAPI, configuración por entorno,
  `.env.example`
- Next.js mínimo que consulta ambos endpoints, con el aviso legal ya puesto
- CI (ruff + pytest + typecheck y build del frontend)
- `tests/test_arquitectura.py`: el núcleo no puede importar la plataforma

**Aceptación cumplida:** los 92 tests del motor siguen pasando, más 10 nuevos
(102 en total); `ruff check` y `ruff format --check` en verde; `/health` informa
de qué dependencia está caída en lugar de caerse con ella; `/markets` sale de
`config/*.yaml` y no del código.

Un hallazgo del camino: **`.env` no estaba en `.gitignore`**, que es justo lo que
§51 prohíbe. Arreglado aquí.

---

## FASE 2 — Base de datos

Modelo relacional completo con migraciones.

- Entidades de referencia: market, exchange, country, currency, calendar,
  security (con ISIN, company_id, alta/baja), asset_type
- Series: price (particionada), fundamental_snapshot (con `publication_date` y
  `pit_origin`), technical_indicator
- Trazabilidad: model_version, feature_snapshot, score, model_prediction, signal,
  pipeline_run, data_quality_check
- Usuario y cartera: user, portfolio, position, transaction, watchlist, alert
- Alembic; carga inicial de los 5 mercados desde YAML

**Aceptación:** migración desde cero en limpio; los 5 mercados y el universo
cargados; `DATABASE.md` escrito; imposible insertar un `score` sin
`model_version_id` (FK no nula).

---

## FASE 3 — Ingesta de datos

- Puente enrutador → Postgres con `UPSERT` idempotente y carga por `COPY`
- `scripts/verify_sources.py` y cierre de los `POR VERIFICAR` de DATA_SOURCES.md
- **Adaptador SEC EDGAR** (fundamentales EE. UU. con fecha de presentación real)
- **Adaptador BCE** (FX oficial) y **Stooq** (respaldo de precios)
- Persistencia de los checks de calidad en `data_quality_check`

**Aceptación:** `python scripts/update_market_data.py` carga los 5 mercados;
**ejecutarlo dos veces no cambia una sola fila**; `/health/data` informa de
frescura y huecos por mercado; EE. UU. con `pit_origin = captured`.

---

## FASE 4 — Indicadores

Ampliar `core/indicadores.py` desde los actuales (SMA, ATR de Wilder, momentum
12-1) al catálogo de §13: RSI, MACD, ADX, estocástico, Bollinger, ROC,
volatilidad, beta, drawdown, distancia a máximos/mínimos de 52 semanas, ratios
de volumen, aceleración, fuerza relativa vs. benchmark.

Registro de indicadores para que añadir uno sea declarar una función, no tocar
el motor.

**Aceptación:** cada indicador con test de valor conocido; todos vectorizados y
ventana hacia atrás; test que verifica que **ningún indicador mira hacia
adelante** (recortar la serie no cambia el valor en la fecha de corte).

---

## FASE 5 — Análisis fundamental

Ampliar `core/fundamental.py` a los grupos de §14 (crecimiento, rentabilidad,
salud financiera, calidad, valoración), normalizados por sector, mercado y
tamaño. **Adaptador CVM** (Brasil).

**Aceptación:** cohortes con su `n_cohort` registrado; ningún ratio comparado
entre sectores incompatibles; Brasil con `pit_origin = captured`.

---

## FASE 6 — Motor de scoring

Pilares y sub-scores según D-3, percentiles por cohorte según D-4,
renormalización de pesos cuando falta un pilar según D-8, historial de scores
(§24), y los cinco perfiles de §18 como filas de `model_version`.

**Aceptación:** `python scripts/calculate_scores.py` puebla `score`;
**reejecutar sobre la misma instantánea da exactamente los mismos números**; el
score descompone en pilares que suman; cambiar los pesos no requiere tocar
código.

---

## FASE 7 — Backtesting

Conectar el motor existente al feature store y añadir las métricas que faltan
(Sortino, profit factor, turnover, periodo medio de tenencia). Registro de
experimentos (§23).

**Aceptación:** backtest reproducible desde una instantánea sellada; costes,
deslizamiento y lotes aplicados; comparación contra benchmark; los tests
anti-sesgo en verde.

---

## FASE 8 — Machine Learning *(condicionada)*

**No arranca por calendario, sino cuando se cumplan las dos condiciones de D-7:**
universo ≥ 1.000 valores limpios **y** ≥ 15 años de histórico en dos mercados.
Hasta entonces el sistema funciona con el motor determinista, que es honesto y
explicable.

Cuando arranque: targets `outperform_{1,3,6,12}m` contra benchmark **de retorno
total** (D-5); baseline logístico antes que cualquier árbol; walk-forward
**purgado y con embargo** para que las ventanas solapadas no filtren; registro de
modelos.

**Aceptación:** un modelo sólo sustituye al baseline si lo bate **fuera de
muestra y después de costes**. Un resultado negativo se publica.

---

## FASE 9 — Señales

Motor de §25: score + variación + probabilidad + momentum + riesgo + valoración +
régimen. Umbrales configurables. Detección de régimen de mercado (§26).
Metadatos MAR (autor, metodología, fecha, versión) desde el primer día.

**Aceptación:** ningún umbral en el código; motivo estructurado en cada señal;
la señal cambia al cambiar el régimen.

---

## FASE 10 — API de análisis

`GET /stocks/{ticker}/analysis` con todos los componentes de §27, cada bloque con
su disponibilidad y frescura. Explicabilidad de §28: factores positivos y
negativos, y qué ha cambiado en 30 días descompuesto por pilar.

**Aceptación:** el endpoint responde para un valor de cada mercado; un pilar no
disponible se declara como tal y **no** se rellena.

---

## FASE 11 — Rankings y screener

Los diez rankings de §32 (incluidos «most improved» y «biggest drops», que
necesitan el historial de la FASE 6) y el screener de §31 con todos sus
operadores. Screeners guardados. Caché de rankings.

**Aceptación:** top 20 por mercado; screener con filtros combinados por debajo de
un segundo sobre el universo completo; deduplicación por empresa (D-12).

---

## FASE 12 — Usuarios

Registro, login, recuperación de contraseña, sesiones, perfil. Planes
FREE/PRO/PREMIUM modelados y aplicados por dependencia, aunque todos empiecen en
FREE. Sin pagos todavía.

**Aceptación:** `SECURITY.md` escrito; rate limiting activo; ningún secreto en el
repositorio; los límites de plan se comprueban en un único sitio.

---

## FASE 13 — Carteras

Crear cartera, posiciones, transacciones con precio y comisiones. Valor actual,
P&L, asignación, diversificación, score medio, exposición por sector y país.
**Derivado de transacciones, nunca denormalizado.**

**Aceptación:** el P&L cuadra con un caso calculado a mano, incluidas comisiones
y divisa; corregir una transacción antigua corrige todo lo que cuelga de ella.

---

## FASE 14 — Watchlists

Con score, variación de score, variación de precio, señal y probabilidad por
valor (§35).

---

## FASE 15 — Alertas

Los ocho tipos de §36, evaluados en el pipeline diario. Email primero;
arquitectura de canales preparada para push/Telegram/WhatsApp.

**Aceptación:** una alerta no se dispara dos veces por el mismo hecho
(idempotencia); el usuario puede desactivarlas.

---

## FASE 16 — Explicaciones con IA

Capa LLM sobre JSON estructurado, con las cuatro reglas duras de
ARCHITECTURE.md §12 y caché por `(security, fecha, hash_score)`.

**Aceptación:** test que verifica que el LLM responde «Información no
disponible» ante un hueco; validador que **rechaza** la respuesta si contiene
cifras que no estaban en la entrada.

---

## FASE 17 — Frontend MVP

Las nueve páginas de §39, funcionales y sin diseño elaborado. Dashboard (§40) y
página de valor (§41). Disclaimers visibles (§44).

**Aceptación:** un usuario puede registrarse, buscar un valor, ver su análisis,
crear una cartera y añadir a watchlist, sin tocar la API a mano.

---

## FASE 18 — Despliegue y comercialización

Despliegue en VPS, backups, monitorización, `DEPLOYMENT.md`.

Y las dos decisiones que no son técnicas y bloquean el cobro:

1. **Migrar a proveedor con licencia comercial** (RD-1). yfinance no es
   comercializable.
2. **Revisión legal** antes de activar personalización (D-6) y para cumplir los
   requisitos de MAR en las recomendaciones generales.

---

## Después del MVP

Por orden de valor, no de facilidad:

1. **Deslistadas y composición histórica de índices** (RD-4). Es lo que convierte
   el backtest en evidencia en lugar de en indicio.
2. **Ampliar universo** a 1.000+ valores, que además es la puerta de la FASE 8.
3. **Copiloto conversacional** (§30): pregunta → filtros → nuestra API → respuesta.
4. **Análisis de cartera con IA** (§34), sólo en su parte descriptiva.
5. **Más mercados** (UK, FR, IT, PT, CA, JP, AU, MX): una fila en `market`, su
   calendario y sus tickers.
6. **ETFs y REITs** (§4).
7. **FASE 2 de UX/UI** (§57), con el motor ya asentado.
