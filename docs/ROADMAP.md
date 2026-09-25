# Roadmap

Fases, entregables y criterio de aceptación. El orden sigue el de §56 del
encargo, reordenado por una razón concreta: el motor cuantitativo **ya existe y
está probado** (ver [PROJECT_PLAN.md](PROJECT_PLAN.md) §0), así que las fases
4 a 7 del encargo —indicadores, análisis fundamental, scoring, backtesting— no
son construcción desde cero sino extracción, extensión y conexión.

Una fase no se da por terminada si sus tests no pasan y su documentación no está
actualizada. No hay estimaciones en días: dependen de dedicación y no aportan.

**23/09/2026 — la plataforma pasa a `main`.** Se integran en ella las
correcciones del motor 0.4.1 a 0.5.0 (registro de cambios de `ESTRATEGIA.md`):
reparto de huecos global entre mercados, deslizamiento contado una vez,
calentamiento con histórico previo, percentiles sin huecos, EV con precio sin
ajustar, descargas robustas, sectores, corte fijo entre diseño y validación. Los
perfiles de puntuación pasan a la versión 1.1.0. La plataforma es, de momento,
de uso propio; las tareas siguientes, por orden, están en [`PLAN.md`](../PLAN.md).

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

> **Corrección, 21/09/2026.** Esta fase se dio por cerrada con la ingesta
> escrita y probada, pero **nadie la ejecutaba**: `workers/runner.py` se
> limitaba a `signal.pause()`, aunque `docker-compose.yml` prometiera un
> pipeline diario y `pyproject.toml` declarara APScheduler. El efecto se vio en
> producción —dos mercados con datos y tres vacíos— y tardó semanas en salir,
> porque los dos que se habían cargado a mano funcionaban perfectamente. El
> planificador está ahora en `workers/planificador.py` y `workers/runner.py`,
> con sus horas sacadas de los calendarios reales. La lección, escrita donde se
> pueda tropezar con ella: **una fase que produce datos no está cerrada hasta
> que algo la dispara sola.**
>
> **Segunda corrección, 22/09/2026.** El planificador funcionaba —las horas de
> producción coincidían con las calculadas desde los calendarios— pero cubría
> media tubería: `ejecutar_mercado` encadenaba ingesta e indicadores y se
> paraba ahí. `workers/pipeline/scores.py` y `senales.py` existían, tenían su
> `ejecutar()`, y **no los llamaba nadie**. Con los precios ya al día,
> `/rankings` devolvía `fecha_datos` de cinco días antes, la web servía el
> precio de hoy con el score de la semana pasada, y la India —recién cargada,
> con precios y fundamentales— daba `n: 0` en su ranking: para el motor no
> existía.
>
> Puntuar es ahora una tarea propia, **una sola y después del último cierre**,
> porque el ranking de §25 compara los cinco mercados y lee los scores de UNA
> fecha: puntuar tras cada cierre dejaría la tabla global incompleta once horas
> al día. La lección es la misma de arriba, una capa más abajo, y por eso vale
> la pena escribirla otra vez: **comprobar que la tarea existe no es comprobar
> que hace el trabajo entero.**

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

## FASE 6 — Motor de scoring ✅ COMPLETADA

- `core/estrategia/scoring.py`: cuatro pilares ortogonales y nueve sub-scores
- `config/modelos.yaml`: los cinco perfiles de §18 como datos, cargados en
  `model_version`
- `scripts/calculate_scores.py` y la etapa `workers/pipeline/scores.py`

**Aceptación cumplida:** los cinco modelos puntúan los 59 valores de EE. UU. y
Brasil; **reejecutar da la misma huella exacta** en la tabla `score`; los pesos
viven en configuración y hay un test que comprueba que cambiarlos cambia el
orden. 287 tests.

Los resultados cuadran con la realidad: META y NVDA con crecimiento alto y
valoración cara, PETR4 barata y sin crecimiento, KO y PG con riesgo bajo.

**Cuatro fallos, y el peor no era de código:**

- **La base mezclaba datos sintéticos y reales.** Las pruebas con
  `--proveedor sintetico` dejaron precios inventados en fechas que los datos
  reales aún no cubrían; la recarga real no los pisó y quedaron conviviendo.
  Exxon aparecía a 1.215 $ junto a sus cierres reales de 165, y **el ranking se
  calculó con eso**. La columna `source` decía la verdad en cada fila, pero
  ninguna consulta la miraba. Ahora hay una barrera que lo impide.
- **Las nueve magnitudes de §14 se calculaban y no se escribían.** Estaban en el
  contrato desde la FASE 5 y no en el mapeo de escritura: 1.394 filas con las
  nueve columnas a cero. El contrato vigila la frontera del proveedor; nada
  vigilaba la de la base de datos. Ahora sí.
- **ExxonMobil no tenía fundamentales.** Su ticker resuelve a un CIK nuevo —se
  reorganizó— que solo ha presentado trimestrales; sus 19 ejercicios están en el
  CIK de siempre. Misma familia que los cambios de ticker en Brasil: un
  identificador que cambia y rompe el enlace en silencio.
- **Un valor dado de baja seguía puntuando.** La carga de referencia es un
  UPSERT, así que no tocaba lo que desaparecía del YAML: Eletrobras seguía
  activa tras renombrarse. Ahora se desactiva lo ausente, sin borrarlo.

---

## FASE 7 — Backtesting ✅ COMPLETADA

Conectar el motor existente al feature store y añadir las métricas que faltan
(Sortino, profit factor, turnover, periodo medio de tenencia). Registro de
experimentos (§23).

**Aceptación:** backtest reproducible desde una instantánea sellada; costes,
deslizamiento y lotes aplicados; comparación contra benchmark; los tests
anti-sesgo en verde.

- [x] **Métricas que faltaban.** Sortino, profit factor, rotación anual y días
      medios en cartera, en `metricas.py`, en el `Resumen` y en los dos
      informes.

      Sortino y profit factor devuelven `no disponible`, no `0.0`, cuando no
      están definidos —una estrategia sin una sola pérdida— porque el cero es el
      peor valor posible para la mejor situación posible, y en un ranking la
      pondría la última.

      La rotación se divide entre dos para que "rotar la cartera una vez" dé 1 y
      no 2, y **solo cuenta operaciones cerradas**: lo que sigue abierto al
      final del backtest no aparece, así que en periodos cortos el número se
      queda bajo.
- [x] **Registro de experimentos (§23).** Tabla `backtest_run` y
      `backend/db/experimentos.py`.

      La propiedad que lo hace útil: `fingerprint` es `UNIQUE`, así que repetir
      el mismo backtest incrementa `run_count` en vez de crear fila, y contar
      filas cuenta experimentos **distintos**. Cambiar un peso deja una fila
      nueva: el coste de buscar queda anotado, se quiera o no.

      `period_kind` convierte «el periodo de validación está cerrado hasta el
      final» en una consulta de un segundo en lugar de una intención.
- [x] **Backtest desde la base de datos.** `backend/adapters/desde_bd.py`
      construye la `Instantanea` del motor leyendo de Postgres, y
      `scripts/run_backtest.py` la ejecuta.

      La flecha de dependencias no se toca: el motor **sigue sin saber que
      existe una base de datos** (§4 de ARCHITECTURE.md). La traducción vive en
      `backend`, igual que la de escritura.

      Dos decisiones deliberadas: trae **también los valores dados de baja**
      —filtrar por `active` sería reconstruir el universo de hoy y aplicarlo al
      pasado, sesgo de supervivencia puro (D-13)—, y se **niega a leer una base
      que mezcle datos sintéticos y reales**, que es el guardarraíl de la FASE 6
      aplicado al extremo de la lectura.

      El script **anota el experimento solo**, en la misma ejecución: un
      registro que hay que acordarse de rellenar a mano no se rellena, y
      entonces no sirve para lo único que existe.
- [x] **Comparación contra benchmark en el informe.** Anualizada de la
      estrategia y de la referencia, exceso, **alfa de Jensen**, beta,
      correlación y drawdown de ambas, en los dos informes.

      Se calcula alfa y no solo el exceso porque ganar un 12% con beta 1,5 en un
      mercado que subió un 10% no es haber batido a nadie: es haber llevado más
      riesgo. El exceso es lo que nota quien invierte; el alfa es el mérito. Hay
      un test con una estrategia que hace exactamente el doble que el mercado:
      su exceso es positivo, su beta sale 2 y su alfa, cero.

      **Corregido de paso un sesgo real:** `curva_referencia` rellena hacia
      atrás (`bfill`) para poder pintar la línea completa, así que el tramo
      anterior al lanzamiento del ETF aparecía como una referencia plana al 0%.
      Medir el alfa sobre ese relleno le regalaba a la estrategia todo ese
      periodo. La comparación arranca ahora en la primera sesión con dato real y
      el informe lo dice cuando recorta.

---

## FASE 8 — Machine Learning 🔄 INFRAESTRUCTURA LISTA, BLOQUEADA POR D-7

**Estado medido, no recordado:** `ml.condiciones.medir()` lo comprueba contra la
base de datos. A 22/09/2026: **138 valores de 1.000 (13 %)** y **20 años de
histórico**, por encima de los 15 exigidos desde que se recargó el 21/09/2026.

De las dos condiciones ya se cumple una. **Lo único que sigue bloqueando la
fase es el tamaño del universo**, y eso lo mueve la lista de tickers, no el
código: ampliar los cinco mercados vale más que añadir mercados nuevos, porque
la cohorte de percentiles es `mercado × sector` y cinco cohortes pequeñas más
no dan lo que da una cohorte profunda.

Y una advertencia que no desaparece al cumplir D-7: los cinco *benchmarks* son
índices de precio (`benchmark_is_total_return: false` en los cinco), que es la
decisión **D-5**. Entrenar contra ellos sesga el objetivo a favor de las
empresas que reparten dividendo. Medir «13 % del universo» es fácil; esto no lo
mide nadie solo.

Lo que hay construido y probado:

- [x] **`ml/particion.py` — walk-forward purgado con embargo.** Es la pieza que
      decide si un backtest de modelo significa algo.

      Una observación aquí no es un punto, es un **intervalo**: preguntar el 1 de
      enero «¿batirá al índice en tres meses?» da una etiqueta que no se conoce
      hasta abril. Con la partición ingenua, esa observación entrena mientras su
      resultado cae dentro del periodo de prueba — el modelo ve el futuro
      mientras «aprende».

      Hay un test que construye la partición ingenua y **comprueba que sí
      filtra**, para que el test de que no hay fuga no esté pasando por
      casualidad.

      Sobre el embargo, dicho claro: en walk-forward estricto **no muerde nunca**,
      porque no hay entrenamiento posterior a la prueba. Se implementa para la
      variante de validación cruzada y hay un test que lo demuestra mordiendo
      allí. Decir «protegido por embargo» donde no toca nada sería una
      tranquilidad falsa.
- [x] **`ml/condiciones.py` — D-7 ejecutable.** Mientras la decisión viva solo en
      un documento, el día que alguien tenga ganas de entrenar se salta sin
      querer. `exigir()` lanza una excepción, no un aviso: un aviso en el log se
      lee una vez y se ignora la siguiente.
- [x] **`ml/seleccion.py` — la puerta de aceptación.** Un modelo sustituye al
      baseline solo si lo bate fuera de muestra, después de costes, por un margen
      y **en la mayoría de los pliegues**. Esto último es lo que atrapa el caso
      que más engaña: ganar de media gracias a un único periodo afortunado
      mientras se pierde en cuatro de cinco.

      Es código y no una norma escrita porque una norma se cumple cuando uno está
      tranquilo; después de tres semanas peleando con un modelo, «bate por 0,3
      dentro de muestra» empieza a parecer suficiente.
- [ ] **Targets, features y entrenamiento.** No se escriben todavía, y no por
      falta de tiempo: con 138 valores y ventanas solapadas de tres meses hay
      decenas de observaciones independientes, menos que los parámetros de
      cualquier modelo útil. Lo que salga de ahí memoriza el periodo.

      Además, los targets `outperform_*` piden un benchmark de **retorno total**
      (D-5) y los cinco que hay son índices de precio: entrenar contra ellos
      premiaría sistemáticamente a las empresas que pagan dividendo.

**Para desbloquear** hacen falta datos, no código: ampliar el universo hacia los
1.000 valores y descargar 15 años en lugar de 8 (`--anos 15`).

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

## FASE 9 — Señales ✅ COMPLETADA

Motor de §25: score + variación + probabilidad + momentum + riesgo + valoración +
régimen. Umbrales configurables. Detección de régimen de mercado (§26).
Metadatos MAR (autor, metodología, fecha, versión) desde el primer día.

**Aceptación:** ningún umbral en el código; motivo estructurado en cada señal;
la señal cambia al cambiar el régimen.

`core/estrategia/senales.py`, `workers/pipeline/senales.py` y
`scripts/calculate_signals.py`.

**Cómo se decide.** El score fija una señal *base*; después se aplican
**limitadores**, cada uno capaz de rebajarla pero nunca de subirla, y la señal
se queda con el motivo del que de verdad mordió.

La alternativa —sumar o promediar los siete componentes— produce compensaciones
absurdas: un riesgo pésimo queda tapado por un fundamental excelente y la señal
sale igual de buena. Un limitador no se compensa con nada, y además deja
explicado el porqué.

**El régimen mira tres cosas, no una**: tendencia, drawdown y volatilidad. Un
índice puede estar sobre su media viniendo de caer un 25% con la volatilidad al
triple, y eso no es un mercado alcista por mucho que el precio supere una línea.
`DESCONOCIDO` se trata como adverso: si un índice deja de actualizarse —un fallo
de datos— no puede empezar a producir compras fuertes en silencio.

**El vocabulario de motivos es cerrado** porque el informe se construye
contando. La pregunta a responder es «por qué no hubo ni una compra esta
semana», y con texto libre no se agrupa.

Dos fallos que encontraron los tests, no la lectura: la etapa elegía la última
versión de modelo con ese nombre en vez de la que tenía los scores de esa fecha
—habría emitido señales contra una versión sin puntuar, devolviendo cero sin
explicar por qué—; y el test del motivo no distinguía esta implementación de la
ingenua hasta que se añadió el caso de un limitador que se evalúa y no muerde.
Ese caso se comprobó mutando el código: con la versión ingenua falla, y los
otros catorce pasan.

---

## FASE 10 — API de análisis ✅ COMPLETADA

`GET /stocks/{ticker}/analysis` con todos los componentes de §27, cada bloque con
su disponibilidad y frescura. Explicabilidad de §28: factores positivos y
negativos, y qué ha cambiado en 30 días descompuesto por pilar.

**Aceptación:** el endpoint responde para un valor de cada mercado; un pilar no
disponible se declara como tal y **no** se rellena.

`backend/api/v1/stocks.py`.

**Cada bloque se envuelve** en `{disponible, motivo, frescura, datos}`. Un
`null` suelto no distingue «no lo sabemos» de «vale cero», y esa diferencia es
justo la que decide si alguien puede fiarse del número. Un pilar ausente sale
declarado con su motivo; imputar la media convertiría «no lo sabemos» en «es del
montón», que es otra afirmación y además falsa.

El bloque de **predicción se declara ausente en vez de omitirse**: D-7 aplaza el
modelo estadístico, y quien consuma la API tiene que poder ver que ese bloque
existe y por qué está vacío.

**El corte temporal es el punto delicado.** El parámetro `fecha` responde a «qué
se sabía aquel día», y es el sitio exacto donde RT-2 avisa de que el sesgo de
anticipación se reintroduce al añadir la capa SaaS: un endpoint que lee la tabla
de precios sin corte devuelve el futuro sin que nadie lo note. Todas las
consultas filtran por esa fecha, los fundamentales por `publication_date` y no
por `period_end` —lo que importa es cuándo se supo—, y hay un test con un precio
plantado el día siguiente al corte que falla si aparece.

Un cambio a 30 días que no se puede calcular se declara `no_comparable` en lugar
de devolver 0: un cero diría «no se movió», que es una afirmación sobre datos
que no existen.

---

## FASE 11 — Rankings y screener 🔄 CASI

Los diez rankings de §32 (incluidos «most improved» y «biggest drops», que
necesitan el historial de la FASE 6) y el screener de §31 con todos sus
operadores. Screeners guardados. Caché de rankings.

**Aceptación:** top 20 por mercado; screener con filtros combinados por debajo de
un segundo sobre el universo completo; deduplicación por empresa (D-12).

- [x] **Los diez rankings** (`backend/api/v1/rankings.py`), con `mas_mejorado` y
      `mayor_caida` comparando dos fotos del score. Sin foto anterior devuelven
      vacío en lugar del ranking por score: eso sería responder otra pregunta
      sin avisar.
- [x] **Deduplicación por empresa (D-12).** Si el ADR y la acción local aparecen
      los dos, quien construya una cartera con ese top se concentra sin darse
      cuenta. Se conserva la línea **principal**, no la de más score — no son
      intercambiables: distinta divisa, distinto huso, distinta liquidez.

      El test se comprobó mutando el código: con la regla del score fallan tres
      tests. Antes de eso el test existía pero **no discriminaba**, porque el
      ADR tenía menos score que la local y ambas reglas coincidían.
- [x] **Screener de §31** con los ocho operadores. Los campos van por **lista
      blanca**: resolverlos con `getattr` convertiría una petición en acceso
      arbitrario al esquema. Un operador mal usado da 400, no un 500.
- [x] La respuesta distingue `n` de `total`: «20 resultados» no dice si hay 20 o
      400.
- [ ] **Screeners guardados.** Dependen de usuarios: `saved_screener` tiene
      `user_id` y la autenticación es la FASE 12.
- [ ] **Caché de rankings.** Con 138 valores no hace falta todavía; medirlo
      antes de añadir una capa que hay que invalidar.

---

## FASE 12 — Usuarios ✅ COMPLETADA

Registro, login, recuperación de contraseña, sesiones, perfil. Planes
FREE/PRO/PREMIUM modelados y aplicados por dependencia, aunque todos empiecen en
FREE. Sin pagos todavía.

**Aceptación:** `SECURITY.md` escrito; rate limiting activo; ningún secreto en el
repositorio; los límites de plan se comprueban en un único sitio.

`backend/seguridad.py`, `backend/limites.py`, `backend/api/deps.py`,
`backend/api/v1/auth.py` y [SECURITY.md](SECURITY.md).

**Argon2id** con el perfil de OWASP, y recifrado automático al entrar cuando los
parámetros suben: así se encarece el hash sin pedirle a nadie que cambie de
contraseña.

**Cada token declara su propósito** (`acceso`, `refresco`, `reinicio`) y se
verifica al leerlo. Sin eso, el token de vida larga valdría para llamar a
cualquier endpoint y el que viaja por correo serviría para todo. El refresco
**rota**: si alguien roba uno y lo usa, el legítimo deja de funcionar y el robo
se nota.

**No se puede averiguar quién tiene cuenta.** Misma respuesta para «no existe» y
«contraseña incorrecta», y **mismo tiempo**: cuando el correo no existe se
verifica igualmente contra un hash señuelo, porque si uno inexistente responde en
2 ms y uno real en los 90 ms que cuesta Argon2, el reloj delata cuáles existen.

**El limitador falla cerrado.** Si Redis no responde se rechaza con 503 en vez de
dejar pasar: un limitador que se apaga cuando su dependencia cae da barra libre
para probar contraseñas justo el día que alguien tumba Redis a propósito.

Pendiente y escrito como tal en `SECURITY.md`: verificación de correo, segundo
factor, auditoría de accesos y rotación de `JWT_SECRET`. El envío del enlace de
reinicio depende de la FASE 15; en producción **no se emite**, porque existir a
medias sería peor que no existir.

---

## FASE 13 — Carteras ✅ COMPLETADA

Crear cartera, posiciones, transacciones con precio y comisiones. Valor actual,
P&L, asignación, diversificación, score medio, exposición por sector y país.
**Derivado de transacciones, nunca denormalizado.**

**Aceptación:** el P&L cuadra con un caso calculado a mano, incluidas comisiones
y divisa; corregir una transacción antigua corrige todo lo que cuelga de ella.

`backend/carteras.py` (el motor, sin base de datos) y
`backend/api/v1/portfolios.py` (los endpoints).

**Lo único que se escribe es la transacción.** No hay endpoint para «pon la
cantidad de AAPL a 30». Posiciones, coste medio, P&L, pesos y exposición salen de
recorrer las transacciones en cada consulta, y por eso el criterio de aceptación
se cumple por construcción: corregir una compra de hace ocho meses corrige el
P&L realizado de todas las ventas posteriores sin ningún paso de recálculo,
porque no existe ninguno que llamar.

`portfolio_position` sobrevive **solo** para `target_weight`, que sí es una
decisión de alguien y no una consecuencia. Sus columnas `quantity` y
`average_price` no se leen ni se escriben: son exactamente la denormalización
que esta fase prohíbe.

**FIFO y no coste medio**, porque es la convención fiscal española para valores
homogéneos y un P&L realizado que no coincide con el que hay que declarar sirve
de poco. Sobre el mismo caso, el coste medio da 5.718,04 € donde FIFO da
6.147,92 €: 429,88 € de diferencia. Hay un test que comprueba que **no** sale el
otro número.

**El cambio se congela al escribir.** El tipo de una operación es el del día en
que se ejecutó, guardado con ella; recalcularlo con el de hoy reescribiría la
historia de la cartera cada mañana. Si quien la registra aporta el suyo manda ese
—lo que se pagó de verdad es lo que puso el broker—; si no, se busca en
`fx_rate`. Si no hay ninguno, la transacción **se rechaza** en lugar de guardarse
con un 1 implícito: un 1 entre USD y EUR no falla, solo da un P&L equivocado.

**El corte temporal también vale aquí** (RT-2). `?fecha=` deja fuera precios,
scores y transacciones posteriores. Sin eso, «cómo iba mi cartera en marzo» se
contesta con precios de hoy.

**Lo que no se sabe se declara.** Un valor sin precio va a `sin_valorar` y no se
valora a coste, que fingiría que no se ha movido. El score medio va ponderado por
peso y **con su cobertura al lado**; lo que no tiene score no se imputa a 50
(D-8). La diversificación se mide con HHI y posiciones efectivas: cuatro
posiciones con el 85 % en una dan 1,35, que es el número que dice la verdad.

La cartera de otro responde **404 y no 403**: un 403 sobre la cartera 41
confirmaría que la cartera 41 existe.

Los cuatro criterios se comprobaron mutando el código —media aritmética, imputar
un 50, quitar el corte, no invertir el convenio de cambio— y cada mutación tumba
su test.

**Limitación conocida:** `portfolio_transaction.security_id` es obligatorio, así
que una comisión de custodia que no pertenece a ningún valor hay que imputarla a
uno. El motor sabe tratarla (`Cartera.gastos`); falta hacer la columna anulable,
que es una migración de otra fase.

---

## FASE 14 — Watchlists ✅ COMPLETADA

Con score, variación de score, variación de precio, señal y probabilidad por
valor (§35).

`backend/api/v1/watchlists.py`. Crear listas, añadir y quitar valores, y la
vista de vigilancia con las cinco columnas.

**Una consulta por columna, no una por valor.** Lo natural sería reutilizar los
ayudantes de `stocks.py` en un bucle; con una lista PREMIUM de 250 valores eso
son más de mil consultas para pintar una pantalla. Aquí son cinco consultas
tenga la lista tres valores o doscientos cincuenta, y hay un test que cuenta las
consultas y falla si el número crece con el tamaño de la lista.

**Una variación que no se puede calcular sale `None` con su motivo, no cero.**
Un cero afirma «no se movió», que es una afirmación sobre datos que no existen.
Misma regla que en §27 y en las carteras.

**La probabilidad de §35 se declara bloqueada por D-7** en lugar de omitirse. La
columna está en la respuesta y trae escrito por qué viene vacía: quien consuma
la API tiene que poder ver que el dato está previsto, no encontrarse un hueco y
suponer que se le olvidó a alguien.

**Aquí NO se deduplica por empresa.** En los rankings, tener la acción local y
su ADR es un defecto (D-12): la misma empresa ocupa dos puestos. En una
watchlist es una elección — si alguien ha puesto las dos líneas, quiere ver las
dos — y quitarle una sería decidir por él.

La foto anterior se busca desde la última fecha puntuada y no desde hoy: si el
último cálculo es de hace una semana, comparar contra hace 30 días naturales
mediría 37 días y no 30.

Cinco mutaciones comprobadas: variación a cero, una consulta por valor, un
`None` ordenando como un cero, quitar el corte temporal y omitir la
probabilidad. **La del orden sobrevivió la primera vez**: con solo scores
positivos, tratar un `None` como cero da el mismo orden que tratarlo como
ausente. Hubo que ordenar por variación de score —que sí puede ser negativa—
para que el test distinguiera una implementación de la otra.

---

## FASE 15 — Alertas

Los ocho tipos de §36, evaluados en el pipeline diario. Email primero;
arquitectura de canales preparada para push/Telegram/WhatsApp.

**Aceptación:** una alerta no se dispara dos veces por el mismo hecho
(idempotencia); el usuario puede desactivarlas.

---

## FASE 16 — Explicaciones con IA ✅ COMPLETADA

Capa LLM sobre JSON estructurado, con las cuatro reglas duras de
ARCHITECTURE.md §12 y caché por `(security, fecha, hash_score)`.

**Aceptación:** test que verifica que el LLM responde «Información no
disponible» ante un hueco; validador que **rechaza** la respuesta si contiene
cifras que no estaban en la entrada.

**Entregado:** `backend/explicaciones.py` (entrada, hash, prompt, validador y
cliente de Claude), `GET /api/v1/stocks/{ticker}/explanation` y la pestaña
«Análisis IA» de la ficha, que deja de ser un hueco con motivo. 33 tests en
`tests/test_explicaciones.py`.

**Las reglas no se confían al prompt; cada una tiene un mecanismo.** El prompt
las pide, pero lo que las garantiza es código que se ejecuta después:

1. *No calcula.* La entrada lleva las cifras ya redondeadas a un decimal, tal
   como se pueden decir. Todo lo demás lo caza la regla 3.
2. *«Información no disponible».* Los huecos viajan en la entrada con su
   motivo, nunca como un `null` suelto que invite a rellenarlo. El validador
   exige la frase exacta en la sección que corresponde a un hueco (cambios a 30
   días sin score anterior, señal ausente) y rechaza cualquier frase que nombre
   un pilar ausente sin declararlo ausente. Las preguntas quedan fuera de esa
   comprobación: preguntar por lo que no se sabe es su papel.
3. *El validador de cifras.* Se extraen todas las cifras del texto —con coma o
   punto decimal, con separador de miles— y cada una tiene que poder leerse en
   la entrada: tal cual, en valor absoluto («cayó 5 puntos» por un −5) o
   redondeada a 0, 1 o 2 decimales. Una resta entre dos cifras de la entrada
   **no** pasa, aunque sea correcta: una resta mal hecha sería igual de
   convincente. Si falla, se reintenta una vez diciendo al modelo qué cifra
   sobraba; si vuelve a fallar, **no se publica ni se guarda**.
4. *Caché.* La clave es el hash de la entrada completa más la versión del
   prompt, no sólo del score: si cambia la señal, cambia lo que hay que contar;
   si cambia el prompt, las explicaciones viejas dejan de servir. La fecha de
   la clave es la del score, así que dos cortes con el mismo score comparten
   explicación.

**La entrada se publica con la respuesta** (`entrada`), y la pestaña la enseña
bajo el texto: «la IA no inventa» pasa de ser una promesa a algo que el lector
comprueba.

**Coste.** FREE no tiene explicaciones (403, SECURITY.md). En PRO y PREMIUM el
cupo diario cuenta **generaciones**, no lecturas: servir desde la caché es
gratis y no gasta cupo. Se descuenta antes de llamar, porque un intento
rechazado también se ha pagado, y falla cerrado sin Redis como el limitador.
La pestaña pide la explicación sólo al abrirla, no en cada visita a la ficha.

**Sin clave no se rompe nada.** Sin `ANTHROPIC_API_KEY` la API arranca y el
bloque se declara «no configurado». Un fallo o una negativa del modelo son un
bloque no disponible, no un 500.

**Modelo.** `claude-opus-5` por defecto (`LLM_MODELO`), con salida
estructurada por esquema JSON y el *fallback* de servidor ante una negativa;
el modelo que de verdad sirvió cada explicación queda en `llm_model`.

**Lo que no se ha probado:** una llamada real al modelo. Los tests usan un
redactor falso que se porta mal a propósito —inventa una cifra, rellena un
hueco—, que es lo que la aceptación pide demostrar. Cómo redacta el modelo de
verdad, y cuántas veces lo rechaza el validador, hay que medirlo en producción:
cada rechazo queda en el log con sus motivos.

---

## FASE 17 — Frontend MVP ✅ COMPLETADA · rediseñada 21/09/2026

> **Rediseño desde Claude Design, 21/09/2026.** Toda la interfaz pasó al diseño
> exportado en `LaLonja Trading.dc.html`: terminal oscuro, Sora para el texto,
> IBM Plex Mono para toda cifra, un único acento en oro. Lo que sigue describe
> la primera versión; las decisiones de fondo —score en un solo tono, glifo
> junto al color, cada hueco con su motivo— se conservaron todas, porque el
> diseño nuevo pedía lo mismo.
>
> Tres cosas que el diseño traía y **no** se implementaron tal cual:
>
> - El sistema `Broadsheet` que el export enlaza **no se usa**: el diseño no
>   emplea ni uno de sus tokens ni de sus clases y lo anula entero. Es
>   andamiaje del exportador.
> - Las cifras de la portada («48.000 empresas», «datos desde 2005») eran
>   falsas. Ahora se leen de `/markets`.
> - Seis funciones dibujadas no tenían backend —IA, noticias, valoración por
>   descuento de flujos, comparables, calendario de resultados y alertas—. La
>   IA ya lo tiene (FASE 16); las otras cinco mantienen su bloque **con el
>   motivo escrito**, ni rellenas con datos de ejemplo ni borradas.
>
> Se pierde el modo claro: el diseño no define variante clara y mantener las dos
> obligaría a inventarse la mitad de los valores.


Las nueve páginas de §39, funcionales y sin diseño elaborado. Dashboard (§40) y
página de valor (§41). Disclaimers visibles (§44).

**Aceptación:** un usuario puede registrarse, buscar un valor, ver su análisis,
crear una cartera y añadir a watchlist, sin tocar la API a mano. **Cumplida**, y
comprobada dirigiendo un navegador de verdad por ese recorrido.

- [x] **Panel (§40)**: estado, mercados, mejor puntuados, los que más han
      mejorado y los que más han caído.
- [x] **Página de valor (§41)**: score por pilares y sub-scores, qué sostiene y
      qué lastra, cambio a 30 días, señal con sus metadatos MAR, fundamentales
      y técnico. Cada bloque dice si falta y por qué.
- [x] **Rankings** (las diez vistas, filtrables por mercado) y **screener**.
- [x] **Aviso legal (§44)** en todas las páginas, no escondido en un enlace.
- [x] **Registro y sesión**, **carteras** (crear, operar, ver valoración) y
      **seguimiento** (§35 completo), más un **buscador** de valores por ticker,
      nombre o ISIN.

**El token nunca pisa el navegador.** Va en una cookie `httpOnly` y las llamadas
a la API las hace el servidor de Next; lo que escribe pasa por acciones de
servidor. La alternativa —el JWT en `localStorage`— convierte cualquier XSS en
un robo de sesión, incluido el de una dependencia comprometida. El coste es que
no hay `fetch` desde el cliente; a cambio los formularios funcionan aunque el
JavaScript no haya cargado.

El token se renueva en el **middleware**, que es el único sitio que puede
escribir cookies: un componente de servidor puede leerlas pero no ponerlas. Se
refresca solo cuando la cookie de acceso ha caducado, no «por si acaso», porque
el refresco rota y renovar de más multiplica las ocasiones de pisarse. Queda
escrita la limitación: dos navegaciones simultáneas justo al caducar pueden
echar al usuario.

**Tres fallos que solo aparecieron al levantarlo y mirarlo:**

- Las tarjetas de la cartera usaban `<span>` para etiqueta y cifra. Los `span`
  son en línea, así que la cifra se pintaba **al lado** de su etiqueta en vez de
  debajo, y las cuatro tarjetas se desbordaban unas sobre otras. Compilaba
  perfectamente. Es el mismo fallo que el relleno del medidor de la primera
  mitad de esta fase.
- La barra de navegación medía **778 px en una pantalla de 390**: con sesión
  pasa de tres enlaces a siete más el correo. Ahora envuelve, y el correo se
  oculta en móvil.
- «Has alcanzado el máximo de 1 **carteras** de tu plan». El plan gratuito tiene
  cupo de uno, así que ese es el mensaje que más gente iba a leer.

Y una hipótesis **descartada**: los errores 418 de React que aparecían en el
recorrido parecían venir de un `<form>` dentro de un `<p>`. Volviendo a ponerlo
no se reproducen: venían de que la API estaba caída y el render fallaba. El
`<div>` se queda porque el markup era inválido igual, pero no arregló lo que
parecía.

Recorrido comprobado de punta a punta con Chromium: registrarse, crear cartera,
chocar con el cupo del plan, buscar un valor, verlo, seguirlo, registrar una
compra con comisiones, verla en la valoración y cerrar sesión. Sin errores de
página ni de consola, en claro y oscuro, y sin desbordamiento horizontal a
390 px.

**Decisiones visuales que no son de gusto:**

El score va en un medidor de **un solo tono**, claro a oscuro, y no en un
semáforo. Pintar de rojo un 20 y de verde un 80 convertiría un percentil —«está
por debajo de sus comparables»— en un juicio de valor que el número no hace. Ese
juicio lo emite el motor de señales, llega aparte y va etiquetado.

Las señales y el régimen usan **colores de estado reservados, siempre con glifo
y texto**. Dos de los cuatro estados no llegan a 3:1 de contraste sobre la
superficie clara, y además una recomendación de inversión tiene que poder leerse
sin interpretar un color.

El modo oscuro se **elige**: sus valores son pasos propios sobre la superficie
oscura, no un negativo del claro.

**Tres fallos que solo aparecieron al renderizar y mirar**, no al compilar: el
relleno del medidor era un `<span>` en línea, así que `height: 100%` no le
aplicaba y las barras salían vacías; el screener pintaba la columna de score dos
veces al filtrar por `overall`; y `select`, `input` y `button` calculan su altura
distinto y salían escalonados en la fila de filtros.

---

## FASE 18 — Despliegue y comercialización 🔄 PARCIAL

Despliegue en VPS, backups, monitorización, `DEPLOYMENT.md`.

- [x] **Desplegado y en el aire**: `lalonja-trading.com`, en un VPS de Hetzner,
      vía Cloudflare Tunnel. Siete contenedores (`postgres`, `redis`, `api`,
      `worker`, `web`, `caddy`, `cloudflared`).

      La máquina **no publica un solo puerto** al exterior: el túnel sale desde
      ella hacia Cloudflare, así que ni Postgres ni la API ni Caddy escuchan en
      la IP pública. El TLS lo termina Cloudflare.

      Lo que se ve hoy es el MVP de la FASE 6 —estado del servicio y tabla de
      mercados—; la interfaz de verdad sigue siendo la FASE 17. Lo que demuestra
      es que la tubería entera funciona de punta a punta.
- [x] `DEPLOYMENT.md` con las dos vías (túnel y IP pública con Let's Encrypt).
- [x] **Backups de Postgres verificados.** `despliegue/copia_seguridad.sh` y
      temporizador de systemd, a diario.

      La verificación va dentro: cada copia se **restaura de verdad** en una
      base de usar y tirar y se **cuentan las filas** antes de darla por buena y
      antes de rotar las anteriores. Un volcado de un esquema vacío se restaura
      sin un solo error, así que comprobar el código de salida de `pg_dump` no
      demuestra nada.

      Probado en los cuatro caminos contra un Postgres real: copia correcta,
      copia vacía (rechazada), rotación y restauración real.
- [ ] **Sacar las copias de la máquina.** Hoy viven en el mismo disco que la
      base: protegen de un borrado accidental, no de perder el servidor.
- [ ] Monitorización y alertas sobre `/health` y `/health/data`.
- [ ] Despliegue automático desde CI en lugar de `git pull` por SSH.

Y las dos decisiones que no son técnicas y bloquean el cobro:

1. **Migrar a proveedor con licencia comercial** (RD-1). yfinance no es
   comercializable.
2. **Revisión legal** antes de activar personalización (D-6) y para cumplir los
   requisitos de MAR en las recomendaciones generales.

---

## Después del MVP

Por orden de valor, no de facilidad. El objetivo declarado del proyecto es que
el motor saque buenas conclusiones de buenos datos, así que el orden es: que el
dato que ya hay llegue entero al motor, que el sistema diga la verdad sobre él,
y sólo entonces que haya más.

0. **Un respaldo de precios.** No estaba en esta lista y debería: hoy los cinco
   mercados cuelgan de yfinance, una sola fuente no oficial, sin SLA y sin
   alternativa desde que Stooq quedó descartado (RD-1). Es el punto 6 del plan
   de `DATA_SOURCES.md`. Candidatas: Tiingo, Twelve Data, o el plan de pago de
   EODHD, que resolvería a la vez el respaldo y los fundamentales de España e
   India.
1. **Deslistadas y composición histórica de índices** (RD-4). Es lo que convierte
   el backtest en evidencia en lugar de en indicio.
2. **Ampliar universo** a 1.000+ valores. Es lo **único** que queda para
   desbloquear la FASE 8: D-7 pide además 15 años en dos mercados y eso ya
   está, desde que el histórico subió a 20 años el 21/09/2026.
3. **Copiloto conversacional** (§30): pregunta → filtros → nuestra API → respuesta.
4. **Análisis de cartera con IA** (§34), sólo en su parte descriptiva.
5. **Más mercados** (UK, FR, IT, PT, CA, JP, AU, MX): una fila en `market`, su
   calendario y sus tickers.
6. **ETFs y REITs** (§4).
7. **FASE 2 de UX/UI** (§57), con el motor ya asentado.
