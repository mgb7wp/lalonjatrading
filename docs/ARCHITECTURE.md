# Arquitectura

Cómo está montada la plataforma y, sobre todo, **por qué** cada frontera está
donde está. Las decisiones de fondo y su justificación están en
[PROJECT_PLAN.md](PROJECT_PLAN.md); aquí se describe el resultado.

---

## 1. La idea en una frase

Un motor cuantitativo determinista y reproducible produce los números; todo lo
demás —base de datos, API, workers, frontend, LLM— los transporta, los guarda o
los explica. **Ninguna capa exterior calcula un score.**

---

## 2. Separación de conceptos (§5 del encargo)

Esta separación no es filosofía: está materializada en módulos y tablas
distintas, y cruzarla rompe tests.

| Concepto | Qué es | Dónde vive |
|---|---|---|
| **Dato** | Hecho objetivo de un proveedor externo | `core/datos/`, tablas `price`, `fundamental_snapshot` |
| **Indicador** | Cálculo matemático sobre datos | `core/indicadores.py` |
| **Feature** | Variable preparada para un modelo, con su versión | `ml/features/`, Parquet versionado |
| **Modelo** | Algoritmo (reglas o estadístico) con versión y parámetros | `core/scoring/`, `ml/models/`, tabla `model_version` |
| **Score** | Salida cuantitativa del modelo, 0-100 percentil de cohorte | tabla `score` |
| **Señal** | Interpretación del score con umbrales configurables | tabla `signal` |
| **Explicación** | Redacción del score en lenguaje natural | tabla `explanation` (cacheada) |
| **Recomendación** | Conclusión personalizada para un usuario | **desactivada** (flag, ver D-6) |

Un score nunca se guarda sin su `model_version`. Una explicación nunca se guarda
sin el hash del score que explica. Eso es lo que permite responder, seis meses
después, a «por qué este valor puntuó 87 aquel día».

---

## 3. Flujo de datos

```
┌──────────────┐
│ Proveedores  │  yfinance · Stooq · SEC EDGAR · CVM · ECB · EODHD(pago)
└──────┬───────┘
       │  cada uno declara sus Capacidades (no es documentación: el informe las lee)
┌──────▼───────┐
│  Enrutador   │  asigna una fuente dueña a cada tipo de dato
│  + CONTRATO  │  ← ningún dato entra sin pasarlo. Punto único de control.
└──────┬───────┘
       │
┌──────▼────────────────────────────┐
│ Almacén                           │
│  · Parquet particionado (bulk)    │
│  · Postgres (registro + servicio) │
└──────┬────────────────────────────┘
       │
┌──────▼───────────┐
│ VistaPuntual(F)  │  ← ÚNICA puerta hacia el pasado. No devuelve nada posterior a F.
└──────┬───────────┘
       │
   ┌───▼────────┐   ┌──────────────┐   ┌───────────┐
   │Indicadores │──▶│   Features   │──▶│  Modelos  │
   └────────────┘   └──────────────┘   └─────┬─────┘
                                             │
                                    ┌────────▼────────┐
                                    │  Scores (0-100) │
                                    └────────┬────────┘
                                             │  + cambio de score + prob. + riesgo + régimen
                                    ┌────────▼────────┐
                                    │  Motor de señal │
                                    └────────┬────────┘
                                             │
                    ┌────────────────────────▼─────────────────────┐
                    │ API REST (FastAPI)  ── caché Redis ──        │
                    └───────┬──────────────────────────┬───────────┘
                            │                          │
                  ┌─────────▼────────┐      ┌──────────▼─────────┐
                  │ Frontend Next.js │      │ Capa LLM (explica) │
                  └──────────────────┘      └────────────────────┘
```

La flecha que importa: **el LLM está al final y sólo lee**. No hay ninguna
flecha de vuelta desde el LLM hacia los scores.

---

## 4. Estructura del repositorio

```
core/                  Motor cuantitativo. Sin Postgres, sin HTTP, sin red salvo proveedores.
  datos/               proveedor.py (interfaz) · contrato.py · enrutador.py · almacen.py
                       registro.py · yfinance_proveedor.py · eodhd_proveedor.py · sintetico.py
  indicadores.py       series vectorizadas, ventanas hacia atrás
  fundamental.py       ratios, mínimos, percentiles por cohorte
  tecnico.py           lectura técnica por valor y fecha
  scoring/             pilares, sub-scores, agregación, versiones de modelo
  senales/             umbrales configurables, régimen de mercado
  backtest.py          motor propio, con costes e impuestos
  metricas.py          CAGR, Sharpe, Sortino, drawdown, win rate, turnover
  calendario.py        cinco calendarios reales (exchange-calendars)
  riesgo.py costes.py cartera.py ordenes.py salidas.py seleccion.py
  tipos.py             enumeraciones y dataclasses compartidas (hoja del grafo de imports)

backend/               FastAPI
  api/v1/              routers: auth, stocks, rankings, screener, portfolios,
                       watchlists, alerts, models, health
  db/                  modelos SQLAlchemy, migraciones Alembic, repositorios
  auth/                hashing, JWT, dependencias de seguridad
  services/            orquestación: analysis_service, ranking_service, screener_service
  adapters/            frontera core(es) ↔ plataforma(en). Traduce nombres y tipos.
  llm/                 cliente, plantillas de prompt, validador anti-invención

workers/               jobs programados (APScheduler), idempotentes
  pipeline/            ingest · indicators · features · scores · signals · rankings · alerts
  runner.py            registro de ejecuciones en pipeline_run

ml/                    feature store, entrenamiento, evaluación, registro
  features/            definición versionada de features
  training/            splits temporales purgados con embargo, walk-forward
  registry/            metadatos de cada versión de modelo

frontend/              Next.js + TypeScript, MVP funcional sin diseño elaborado
scripts/               update_market_data.py · calculate_scores.py · verify_sources.py
config/                reglas.yaml · universo.yaml · implementacion.yaml · impuestos_transaccion.yaml
docs/                  esta carpeta
tests/                 unit · integration · ml · anti_sesgo · backtest
```

### La regla de dependencias

```
frontend → backend → core
              ↓
           workers → core
              ↓
             ml → core
```

`core/` **no importa nada** de `backend/`, `workers/`, `ml/` ni `frontend/`.
Consecuencias prácticas: se puede correr un backtest sin levantar Postgres, y
los tests del motor no necesitan base de datos. Hay un test de arquitectura que
falla si alguien rompe esa dirección.

---

## 5. Modelo de datos

Esquema completo y migraciones en [DATABASE.md](DATABASE.md) (se escribe en
FASE 2). Aquí, las decisiones estructurales.

### Entidades de referencia

`market`, `exchange`, `country`, `currency`, `trading_calendar`, `security`,
`asset_type`. **Ningún mercado está en el código**: añadir Francia es una fila en
`market`, un calendario y sus tickers. Esa es la exigencia de §3.

`security` lleva `isin`, `company_id`, `fecha_alta`, `fecha_baja` y
`es_linea_principal`. Los tres últimos son lo que permite evaluar el universo
*a fecha* (D-13) y deduplicar ADRs (D-12).

### Series temporales

`price` particionada por año, clave natural `(security_id, date)`, carga por
`COPY`. `fundamental_snapshot` con clave `(security_id, period_end, period)` y
—esto es lo importante— `publication_date`, `publication_date_origin` y
`pit_origin ∈ {captured, reconstructed}`. Sin `publication_date` no se puede
saber qué se sabía cuándo, y el contrato rechaza la fila.

### Trazabilidad

| Tabla | Para qué |
|---|---|
| `model_version` | nombre, versión, fecha de entrenamiento, features, periodo, benchmark, parámetros, métricas |
| `feature_snapshot` | puntero a Parquet inmutable + hash + `feature_set_version` |
| `score` | pilares y sub-scores, `cohort_used`, `n_cohort`, `model_version_id` |
| `model_prediction` | probabilidad, horizonte, benchmark, `model_version_id` |
| `signal` | señal, confianza, horizonte, motivo estructurado, metadatos MAR |
| `pipeline_run` | ejecución, etapa, estado, filas afectadas, errores |
| `data_quality_check` | fuente, dataset, comprobación, resultado, severidad |

Un score sin `model_version_id` no se puede insertar: hay una FK no nula. Es la
manera de que «model drift sin control» (§8) sea imposible por construcción y no
por disciplina.

### Usuario y cartera

`user`, `portfolio`, `portfolio_position`, `transaction`, `watchlist`,
`watchlist_item`, `alert`, `alert_event`, `saved_screener`. El valor actual y el
P&L **se derivan de `transaction`**, no se guardan denormalizados: una posición
es el resultado de sus transacciones, y así una corrección de una compra antigua
arregla todo lo que cuelga de ella.

---

## 6. Capa de datos: contrato y proveedores

Ya construida y en producción en el motor actual.

**Interfaz.** `ProveedorPrecios` y `ProveedorFundamentales` están separadas a
propósito: tienen longitudes de histórico, cadencias y modos de fallar
distintos, y una sola interfaz obligaría a inventar la mitad que un proveedor no
ofrece.

**Capacidades.** Cada fuente declara qué sabe hacer (`anios_fundamentales`,
`fechas_publicacion_reales`, `cifras_reexpresadas`, `incluye_deslistadas`…). No
es documentación: el informe las lee para saber de qué avisar. Rellenarlas con
optimismo no mejora el sistema, hace que deje de avisar de sus propios límites.

**Contrato.** Se aplica en el enrutador —el único sitio por el que pasan todos
los datos—, así que no depende de que quien escriba un adaptador se acuerde.
La comprobación que más vale: **ninguna columna obligatoria puede venir entera a
nulo**. Un hueco suelto es un dato que falta, cosa normal; una columna entera
vacía es un mapeo roto. Esa regla existe porque un bug real (`ev` a nulo) dejó
media puntuación fundamental sin efecto, sin error y sin aviso.

**Fallo de proveedor (§48).** Reintento con backoff, timeout, fuente de respaldo
cuando el tipo de dato la tiene, caché, y marcado del dato como `stale` con su
antigüedad. Un proveedor caído degrada el servicio; no lo tumba.

---

## 7. La defensa contra el look-ahead bias

Es la pieza central y ya está construida y probada.

El resto de la aplicación **nunca recibe una serie entera**. Recibe una
`VistaPuntual` construida con una fecha de corte, que no devuelve nada posterior
a esa fecha. Los indicadores son todos ventanas hacia atrás, de modo que la
posición `i` sólo depende de posiciones `<= i`. La vista además **anota la fecha
máxima que ha tocado**, de forma que un test no sólo comprueba que el resultado
es correcto, sino que para calcularlo no se miró ni un día más allá del corte.

Para fundamentales, la visibilidad la fija `publication_date`, con retraso por
mercado cuando el proveedor no da la fecha real (India 105 días, Brasil 100,
resto 120 anual / 90 trimestral).

Un límite que conviene decir en voz alta: el almacén fija **cuándo** se conoció
un dato, no **qué versión** se conocía. Los fundamentales gratuitos vienen
reexpresados a hoy. Por eso cada fila lleva `pit_origin`, y el informe publica
el porcentaje de filas reconstruidas en vez de disimularlo.

Tests en `tests/test_anti_sesgo.py`: si uno falla, ningún backtest vale nada por
bueno que parezca.

---

## 8. Motor de scoring

**Pilares** (ortogonales, agregan al `overall_score`): `fundamental`, `tecnico`,
`sentimiento`, `riesgo`.
**Sub-scores** (descomponen un pilar, se publican, **no** agregan aparte):
crecimiento, calidad, valoración · momentum, tendencia, volatilidad, volumen.

Cada score es el **percentil de Hazen dentro de su cohorte** (mercado × sector),
con repliegue al bloque desarrollado/emergente si la cohorte baja de 8
elementos, registrando `cohort_used` y `n_cohort`. Un 87 significa «mejor que el
87 % de su cohorte ese día».

`riesgo` se puntúa invertido a propósito: **100 = menor riesgo relativo**.

Si un pilar no está disponible (típicamente `sentimiento`), **los pesos se
renormalizan sobre los disponibles** y la API lo declara. Nunca se imputa un 50
neutro: eso es inventar un dato que mueve el ranking.

Los pesos son un objeto de configuración, no constantes. Eso es lo que permite
los perfiles de §18 (Growth, Value, Balanced, Momentum, Low risk) sin tocar
código: son cinco filas en `model_version` con pesos distintos sobre los mismos
pilares.

---

## 9. Motor de señales

La señal **no** sale sólo del score (§25 lo pide explícitamente). Entran:

```
score · variación del score · probabilidad del modelo · momentum
· riesgo · valoración · régimen de mercado
```

Los umbrales viven en `config/reglas.yaml`, versionados junto al modelo. Cada
señal guarda un **motivo estructurado** (enumeración cerrada, no texto libre),
porque el informe se construye contando: sin vocabulario cerrado no se puede
responder a «por qué no salió ninguna compra esta semana».

El **régimen de mercado** (§26) se calcula por mercado a partir de tendencia del
índice, volatilidad y drawdown, y modula los umbrales.

---

## 10. Backtesting

Motor propio, ya construido. Incluye comisiones, deslizamiento por bloque
(desarrollado/emergente), impuestos de transacción por país, lotes mínimos
(B3 opera en lotes de 100), cinco calendarios reales y conversión a divisa base
con el tipo del día anterior para la decisión —el tipo de referencia del BCE se
publica por la tarde, así que decidir con el de hoy es usar un dato que aún no
existe—.

Métricas contra benchmark: CAGR, retorno total, alpha, Sharpe, Sortino, drawdown
máximo, volatilidad, win rate, profit factor, turnover, nº de operaciones,
periodo medio de tenencia. El Sharpe se reporta en rentabilidades **semanales**:
con cinco calendarios distintos las posiciones se congelan en festivos ajenos, y
eso hunde la volatilidad diaria medida e infla artificialmente el Sharpe diario.

Contra el data mining (§23): periodo de diseño (70 %) y de validación separados,
el de validación cerrado hasta el final, y registro de experimentos con
parámetros, universo, periodo y costes.

---

## 11. API

REST versionada bajo `/api/v1`, OpenAPI automática.

```
/auth/{register,login,refresh,password-reset}
/users/me
/markets · /exchanges
/stocks · /stocks/{ticker}
/stocks/{ticker}/{price,fundamentals,technical,score,history,signals,analysis}
/rankings · /screener · /screeners
/portfolios · /portfolios/{id}/{positions,transactions,analysis}
/watchlists · /alerts · /models
/health · /health/data
```

`GET /stocks/{ticker}/analysis` es el endpoint vertebral de §27: devuelve de una
vez security, precio, fundamentales, técnico, valoración, sentimiento, riesgo,
predicciones, score con sus pilares, señal y explicación, **cada bloque con su
estado de disponibilidad y su frescura**.

`GET /health/data` responde a la pregunta operativa que importa: qué datos hay,
de cuándo, de qué fuente y con qué huecos.

Seguridad: hashing Argon2, JWT de vida corta con refresh, validación con
Pydantic en toda entrada, rate limiting por usuario y por IP, CORS restrictivo,
secretos sólo por variables de entorno. Detalle en [SECURITY.md](SECURITY.md).

---

## 12. Capa LLM

Recibe **exclusivamente** un JSON estructurado con los scores ya calculados.
Reglas duras:

1. No calcula números. Redacta los que recibe.
2. Ante un dato ausente responde «Información no disponible». No interpola.
3. Un validador posterior rechaza la respuesta si contiene cifras que no
   estaban en la entrada.
4. Las explicaciones se cachean por `(security_id, date, score_hash)`: un score
   que no cambia no se vuelve a explicar, y así el coste no crece con el tráfico.

El copiloto de §30 traduce la pregunta del usuario a **filtros del screener** y
consulta nuestra propia API. No busca en internet y no es la fuente de verdad.
Lenguaje: probabilidades y horizontes, nunca certezas (§44).

---

## 13. Pipeline diario

Etapas: securities → precios → fundamentales → acciones corporativas →
indicadores → features → modelos → scores → señales → rankings → alertas → logs.

**Idempotente por construcción**: `UPSERT` sobre clave natural, `pipeline_run`
con estado por etapa para reanudar sin repetir, y sello de la `fecha_descarga`
de la instantánea en todo dato derivado. Reejecutar un día no duplica nada ni
cambia resultados.

Cada mercado se procesa tras **su** cierre, según su propio calendario y huso
horario. No hay un «cierre global».

---

## 14. Observabilidad

Logging estructurado en JSON: timestamp, servicio, operación, security, proveedor,
estado, error, `run_id`. `/health` (API, BD, Redis, workers) y `/health/data`
(frescura por mercado y tipo de dato, cobertura, huecos, último éxito por
proveedor). Los checks de calidad de datos se persisten en
`data_quality_check`, de modo que la degradación se ve como tendencia y no como
una sorpresa.

---

## 15. Despliegue

`docker-compose` con cuatro servicios: `postgres`, `redis`, `api`, `worker`
(+ `frontend` en desarrollo). Cabe en un VPS de ~10 €/mes, que es la restricción
de §50. Sin Celery hasta que haya una razón concreta: APScheduler dentro del
worker cubre el pipeline diario con mucho menos coste operativo.

Toda la configuración por entorno (`.env`, nunca en el repositorio;
`.env.example` versionado). Detalle en [DEPLOYMENT.md](DEPLOYMENT.md).
