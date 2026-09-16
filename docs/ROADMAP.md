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

## FASE 2 — Base de datos ✅ COMPLETADA

29 tablas en PostgreSQL 16, con migraciones Alembic.

- Referencia: country, currency, market, exchange, security (con ISIN,
  company_id, alta/baja, línea principal), index_composition
- Series: price (particionada por año), fundamental_snapshot (con
  `publication_date` y `pit_origin`), technical_indicator, fx_rate,
  corporate_action
- Trazabilidad: model_version, feature_snapshot, score, model_prediction,
  signal, explanation
- Usuario y cartera: user_account, portfolio, portfolio_position,
  portfolio_transaction, watchlist(+item), alert(+event), saved_screener
- Operación: pipeline_run, data_quality_check, data_freshness
- `config/referencia.yaml` + `backend/db/seed.py`: carga idempotente que **falla
  si un mercado de `reglas.yaml` no tiene metadatos**
- `/markets` pasa a leer de la tabla, con el mismo contrato de salida

**Aceptación cumplida:** la base de datos de pruebas se recrea y se migra desde
cero **en cada ejecución de la suite**, no una vez a mano; los 5 mercados y los
140 valores cargan y recargan sin duplicar; `autogenerate` no detecta deriva
entre modelos y esquema; `DATABASE.md` escrito; un `score` sin
`model_version_id` es rechazado por la base de datos, y hay un test que lo
comprueba.

122 tests (20 nuevos). Los de base de datos se saltan solos si no hay Postgres,
para que el motor siga corriendo en un portátil sin Docker.

Dos cosas que aparecieron por el camino y no estaban en el plan: Postgres trunca
los identificadores a 63 caracteres (hay un test que falla antes de que lo haga
la migración) y la convención de nombres duplicaba el prefijo en los `CHECK`.

---

## FASE 3 — Ingesta de datos ✅ COMPLETADA

- Puente enrutador → Postgres: `COPY` a una temporal y `UPSERT` sobre la clave
  natural, con `huella()` para comprobar que una recarga no cambia nada
- `backend/adapters/nucleo.py`: la costura núcleo(es) ↔ plataforma(en), en un
  solo sitio
- `workers/pipeline/ingesta.py`: etapas registradas en `pipeline_run`, fallo de
  un mercado aislado del resto, comprobaciones de calidad persistidas
- **Adaptador SEC EDGAR**: la única fuente del proyecto que puede emitir
  `pit_origin = captured`, quedándose con la primera publicación de cada periodo
- **Adaptador BCE** (FX oficial) y **Stooq** (respaldo de precios, con su duda
  sobre el ajuste por dividendos declarada en vez de disimulada)
- `scripts/verify_sources.py` y `scripts/update_market_data.py`
- `/health/data` con frescura, cobertura y rancidez por mercado

**Aceptación cumplida:** los 5 mercados cargan (105.395 precios, 700
fundamentales, 3.294 tipos de cambio con el proveedor sintético); **una recarga
forzada deja las tres tablas con huella idéntica**, comprobado en el script y en
un test; `/health/data` informa por mercado; el adaptador de EE. UU. emite
`capturado` y hay un test que lo prueba sobre una reexpresión.

144 tests (22 nuevos).

**Lo que NO está cerrado, y es de verdad:** ninguno de los tres adaptadores se ha
ejecutado nunca contra su API. El entorno bloquea `sec.gov`, `stooq.com` y
`data-api.ecb.europa.eu` con `403`. Lo probado es el parseo, contra respuestas
grabadas y contra el contrato. `verify_sources.py` existe precisamente para esa
primera ejecución con red, y hasta que se haga, las filas `POR VERIFICAR` de
DATA_SOURCES.md siguen siendo hipótesis.

Tres cosas que aparecieron al ejecutarlo y no estaban en el plan: `LIKE ...
EXCLUDING ALL` conserva el `NOT NULL` de una columna `BIGSERIAL` pero descarta su
secuencia, así que la temporal de fundamentales rechazaba todo; el umbral de
rancio tenía forma de precio y aplicado a fundamentales marcaba los cinco
mercados; y el proveedor sintético emite fundamentales con fecha de publicación
futura, que ahora se cuentan y se avisan en lugar de pasar por «último dato».

---

## FASE 4 — Indicadores ✅ COMPLETADA

`core/estrategia/catalogo.py`: **22 indicadores con registro**. Añadir uno es
escribir una función y decorarla — no hay que tocar el motor, ni la tabla, ni el
pipeline, ni acordarse de añadirlo a tres listas.

El catálogo cubre lo que enumera §13: las cuatro SMA, EMA, RSI, MACD y su señal,
ATR, ADX, estocástico, Bollinger, ROC, momentum 12-1, aceleración, volatilidad
anualizada, beta, drawdown máximo, distancia a máximos y mínimos de 52 semanas,
ratio de volumen y fuerza relativa frente al índice.

`workers/pipeline/indicadores.py` los calcula y los persiste en
`technical_indicator`, **siempre dentro de la misma ejecución que la descarga**:
un indicador es una derivación determinista de los precios, así que si éstos se
actualizan y aquéllos no, lo que sirve la API deja de corresponderse con la base
de datos y nada avisa.

**Aceptación cumplida:** 85 tests del catálogo. Tres de ellos recorren **todo el
registro**, que es la razón de fondo para tenerlo: un indicador nuevo queda
cubierto el día que se escribe, sin que su autor haga nada.

- **Ninguno mira hacia adelante**: recortar la serie por el final no cambia
  ningún valor anterior al corte. Se compara el prefijo completo, no sólo el
  último punto, porque un recursivo mal escrito puede acertar en el corte y
  fallar antes.
- **Ninguno declara menos histórico del que usa**: quedarse corto haría servir un
  número calculado sobre cuatro sesiones como si valiera lo mismo que uno
  calculado sobre doscientas.
- Todos devuelven un vector alineado con la serie.

Y valores conocidos uno a uno, incluidos dos invariantes fuertes: la beta de una
serie contra sí misma vale exactamente 1, y su fuerza relativa exactamente 0.

103.575 filas de indicadores para los cinco mercados en 13 segundos. Recalcular
no cambia un solo número.

**Dos cosas que aparecieron por el camino:**

El RSI de un precio quieto salía **100**. La fórmula de Wilder trata la ausencia
de bajadas como fuerza infinita, así que un valor cuya cotización se ha
congelado —deslistado, suspendido, o al que el proveedor dejó de dar datos—
aparecía como el de mayor momento de todo el mercado. Ahora es `NaN`: sin
movimiento no hay fuerza relativa que medir.

**Los índices de referencia se descargaban y se tiraban.** `^IBEX` y compañía no
estaban en `security`, así que el mapa de tickers de la ingesta los descartaba en
silencio — y sin sus precios no hay beta ni fuerza relativa. Ahora se dan de alta
como valores de tipo `index`, y se excluyen de los recuentos de `/markets`
porque no son analizables.

---

## FASE 5 — Análisis fundamental ✅ COMPLETADA

Alcance revisado con el usuario: **cero presupuesto en datos**, así que el
esfuerzo se concentra en los mercados con datos reales —EE. UU. y Brasil— y el
resto queda con pata técnica hasta que haya fuente.

- **Adaptador CVM**: Brasil pasa de 4 ejercicios reexpresados a 16 con las
  cifras de su momento. 28/28 valores, `pit_origin = captured`
- `core/estrategia/grupos.py`: **20 métricas en los cinco grupos de §14**,
  percentiladas por cohorte (mercado × sector) con repliegue y `n_cohorte`
- El contrato transporta las **nueve magnitudes** que §14 necesitaba
- **Fundamentales por mercado** en el enrutador, y la calidad se deduce del
  reparto en lugar de configurarse aparte

**Aceptación cumplida:** `n_cohorte` y `cohorte_usada` en cada nota; ningún
ratio se compara fuera de su cohorte; Brasil y EE. UU. con `capturado`. 268
tests.

**Sobre el tamaño.** §14 pide normalizar también por tamaño y la maquinaria lo
admite, pero **no se activa**: con 61 valores, partir cada sector por tamaño deja
cohortes de dos o tres empresas, y el propio proyecto fija en 8 el mínimo para
que un percentil signifique algo. Añadirlo ahora no daría una normalización
mejor, daría una peor disfrazada de más fina.

**Cuatro fallos que sólo aparecen con datos reales:**

- **El BPA de la CVM salía ×1000.** La escala `MIL` vale para importes, no para
  cifras por acción. Se propagaba a las acciones, al EV y a toda la valoración.
- **TIM salía con ingresos de cero.** Presenta una consolidada vacía y las
  cifras en la individual; ahora la base se elige por empresa.
- **Las acciones de McDonald's salían 716, no 716 millones.** Etiqueta XBRL con
  unidad `shares` y valor en millones. Daba un PER de 0,0 — la empresa aparecía
  como la más barata del mercado sin que fallara nada. Se derivan del beneficio
  y el BPA, que es inmune a la escala.
- **El contrato rompía la consulta de un valor suelto.** «Columna entera a nulo»
  no significa nada con una empresa: McDonald's no declara `GrossProfit`. La
  comprobación se aplica desde 5 valores.

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
