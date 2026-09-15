# Plan de proyecto — Plataforma SaaS de análisis de inversiones

Este documento es el resultado de la tarea 62 del encargo: analizar el
documento de producto, señalar lo que no encaja, medir los riesgos y fijar la
arquitectura antes de escribir código. No es un resumen del encargo; es la
lista de sitios donde el encargo y la realidad no coinciden, y qué se hace en
cada uno.

Documentos hermanos: [ARCHITECTURE.md](ARCHITECTURE.md) (cómo se monta),
[DATA_SOURCES.md](DATA_SOURCES.md) (de dónde salen los datos y qué se puede y
no se puede usar), [ROADMAP.md](ROADMAP.md) (en qué orden y con qué criterio de
aceptación).

---

## 0. El hallazgo que cambia el plan

El encargo dice «desarrollar desde cero». **Este repositorio no está vacío.**

Contiene `src/estrategia/`: 7.600 líneas de Python con 92 tests en verde que ya
resuelven, y resuelven bien, la parte más difícil de lo que pide el encargo:

| Lo que pide el encargo | Dónde está ya resuelto |
|---|---|
| §12 Prevenir look-ahead bias | `datos/almacen.py` (`VistaPuntual` con fecha de corte) + `tests/test_anti_sesgo.py` |
| §11 Calidad de datos | `datos/contrato.py` (contrato aplicado en el enrutador, no en cada adaptador) |
| §9 Abstracción de proveedores | `datos/proveedor.py`, `datos/enrutador.py`, `datos/registro.py` |
| §13 Indicadores técnicos | `indicadores.py` (vectorizados, ventanas hacia atrás) |
| §14 Fundamental score normalizado por cohorte | `fundamental.py` (percentiles de Hazen por mercado/bloque) |
| §22 Backtesting con costes | `backtest.py`, `costes.py`, `impuestos_transaccion.yaml` |
| §22 Métricas | `metricas.py` (CAGR, Sharpe, drawdown, por año/mercado/bloque) |
| §3 Multi-mercado + calendarios | `calendario.py` (`exchange-calendars`), 5 mercados |
| §52 Configuración externa | `config/*.yaml` con validación Pydantic |

Reescribir esto desde cero destruiría la parte del sistema que más caro cuesta
conseguir y más fácil es equivocar en silencio. El contrato de datos, por
ejemplo, existe porque un bug real —la columna `ev` entera a nulo— dejó la mitad
de la puntuación fundamental sin efecto sin que nada fallara ni avisara. Ese
conocimiento no se recupera reescribiendo.

**Decisión D-1: no se empieza de cero.** El motor actual se convierte en el
núcleo cuantitativo (`core/`) de la plataforma y el SaaS —Postgres, FastAPI,
workers, Next.js— se construye *alrededor*, no *en lugar de*. Lo que sí es nuevo
y hay que escribir entero: persistencia relacional, API, usuarios, carteras,
watchlists, alertas, rankings, screener, feature store, ML y frontend.

Lo que cambia respecto al encargo: el orden. La FASE 1 no es «montar un proyecto
vacío», es «envolver un motor que ya funciona». Eso acelera el MVP varios meses.

---

## 1. Inconsistencias detectadas en el encargo

### I-1. «Desde cero» contra un repositorio con motor funcionando
Resuelto en D-1.

### I-2. Los mercados no coinciden
El encargo pide USA, España, Brasil, India y pone Alemania en «futuro» (§3). El
código ya opera Alemania (`de`, sufijo `.DE`, `^GDAXI`, calendario XETR).

**Decisión D-2:** se mantienen los cinco. Quitar Alemania sería trabajo para
tener menos. El encargo se cumple —los cuatro pedidos están— y sale un mercado
gratis.

### I-3. Los pesos del score suman 100 % pero se solapan
§18 propone: Fundamental 25 %, Technical 20 %, Momentum 15 %, Quality 15 %,
Valuation 10 %, Sentiment 10 %, Risk 5 %.

El problema no es la suma, es que **momentum es parte de technical**, y
**quality y valuation son parte de fundamental**. Sumarlos como si fueran
independientes cuenta el momentum dos veces (dentro de `technical` y otra vez
aparte) y la calidad dos veces. Un valor con momentum fuerte se lleva 35 % del
score por el mismo hecho medido dos veces.

**Decisión D-3: taxonomía explícita de dos niveles.**

- **Pilares** (ortogonales, suman 100 %): `fundamental`, `tecnico`, `sentimiento`, `riesgo`.
- **Sub-scores** (descomponen un pilar, se publican pero **no** se suman aparte):
  `crecimiento`, `calidad`, `valoracion` dentro de fundamental; `momentum`,
  `tendencia`, `volatilidad`, `volumen` dentro de técnico.

La API devuelve los dos niveles —la explicabilidad de §28 los necesita— pero el
`overall_score` sólo agrega pilares. Los pesos viven en la definición del modelo
(§18 pide que sean configurables), no en el código.

### I-4. Un score 0-100 sin cohorte no significa nada
§15 y §18 piden normalizar «entre 0 y 100», pero un score absoluto tiene dos
defectos graves: en un mercado alcista sube todo el universo a la vez (el score
deja de discriminar) y compara un banco con una tecnológica, que §14 prohíbe
expresamente.

**Decisión D-4:** el score es siempre un **percentil transversal dentro de una
cohorte comparable** (mercado × sector, con repliegue a bloque
desarrollado/emergente si la cohorte es menor de 8, que es lo que ya hace
`fundamental.py`). `score = 87` significa «mejor que el 87 % de su cohorte en
esa fecha», y eso se escribe en la API y en la UI. Cada score guarda su
`cohorte_usada` y `n_cohorte`, para que una puntuación rara se pueda rastrear
hasta una cohorte demasiado pequeña.

### I-5. El benchmark de §19 introduce un sesgo silencioso
Se propone comparar el retorno de la acción contra `^IBEX`, `^GSPC`, `^BVSP`,
`^NSEI`. Pero la serie de la acción viene **ajustada por dividendos** (retorno
total) y esos índices son **de precio**, sin dividendos. Comparar uno contra
otro regala a cada acción la rentabilidad por dividendo del índice —del orden de
2-4 % anual en IBEX y Ibovespa—. Con `target = return_stock > return_benchmark`,
eso desplaza el target hacia el 1 sistemáticamente y **el modelo aprende de una
etiqueta sesgada**.

**Decisión D-5:** el benchmark del target debe ser de retorno total, o se le
resta al retorno de la acción el dividendo. Se documenta por mercado en
`DATA_SOURCES.md` qué versión del índice se usa y si es TR o de precio; si sólo
hay de precio, se deja constancia del sesgo residual en el informe del modelo en
vez de ignorarlo. El índice de *régimen* (§26) puede seguir siendo de precio: ahí
sólo se mira la tendencia.

### I-6. «STRONG_BUY / SELL» y el copiloto de §30 son, en la UE, otra cosa
§44 pide separar información de asesoramiento, y está bien visto. Pero dos piezas
del propio encargo cruzan la línea:

- §25 emite `STRONG_BUY`/`SELL` por valor. En la UE eso es una **recomendación de
  inversión** bajo el Reglamento de Abuso de Mercado (MAR art. 20 y Reg.
  Delegado 2016/958): obliga a identificar al autor, describir la metodología,
  fechar la recomendación, declarar conflictos de interés y conservar registro.
  Es viable, pero es trabajo de cumplimiento, no sólo un disclaimer.
- §30 y §34 quieren responder «qué acciones me convienen **según mi cartera y mi
  perfil**». Eso ya no es recomendación general: es **recomendación personalizada**,
  que bajo MiFID II es asesoramiento en materia de inversión y requiere
  autorización de la CNMV.

**Decisión D-6:** se separan desde el modelo de datos, no al final.
`Signal` y `Score` son análisis general (con metadatos de MAR desde el día uno:
autor, método, fecha, versión de modelo). Todo lo que combine el perfil o la
cartera del usuario con una sugerencia de acción vive tras un flag
`PERSONALIZATION_ENABLED=false` y no se comercializa sin revisión legal previa.
El análisis de cartera de §34 —«tienes un 48 % en tecnología», «el score medio ha
bajado de 78 a 69»— es descriptivo y **no** cruza la línea: eso sí entra en el MVP.
Lo que no entra es «vende X y compra Y».

No soy abogado y esto no es asesoramiento legal: es el motivo por el que la
arquitectura lo separa, para que la consulta legal sea barata cuando toque.

### I-7. §19 pide ML sobre una muestra que no da para ML
El universo actual son ~140 valores. Con 8 años de histórico y un target a 3
meses, las ventanas se solapan: hay ~32 periodos de 3 meses **independientes**.
Aunque haya 140 × 8 × 252 ≈ 280.000 filas, la información efectiva son decenas de
observaciones independientes por horizonte, y los valores del mismo mercado están
correlacionados entre sí. Un XGBoost sobre eso memoriza el periodo 2018-2025, no
aprende nada transferible.

**Decisión D-7:** el ML se pospone hasta que se cumplan dos condiciones, no una
fecha: (a) universo ≥ 1.000 valores con datos limpios, (b) ≥ 15 años de
histórico en al menos dos mercados. Hasta entonces el sistema funciona con el
motor determinista, que es honesto y explicable. Cuando entre ML, será con
validación *walk-forward* purgada y con embargo (para que las ventanas solapadas
no filtren información entre train y test) y con la regla de que un modelo sólo
sustituye al baseline si lo bate **fuera de muestra y después de costes**. Un
resultado negativo se publica, no se esconde.

### I-8. §16 pide un sentiment score sin fuente que lo alimente
No hay fuente gratuita, legal y con cobertura de ES/BR/IN para sentimiento de
noticias. El propio encargo lo anticipa y da la respuesta correcta: «NO inventar
datos».

**Decisión D-8:** el pilar `sentimiento` se modela entero (tablas, API, peso en
el modelo) pero nace con estado `unavailable`. Cuando un pilar no está
disponible, **los pesos se renormalizan sobre los pilares que sí lo están** y la
API lo declara (`pilares_disponibles`, `pilares_no_disponibles`). Lo que no se
hace nunca es puntuar 50 «porque es neutro»: eso es inventar un dato y mueve el
ranking.

### I-9. §37 pide idempotencia pero el diseño propuesto no la garantiza
Un pipeline es idempotente si reejecutarlo no duplica ni cambia resultados. Con
`INSERT` por fila eso no se cumple, y con proveedores que **revisan el pasado**
(Yahoo reajusta precios históricos hacia atrás) tampoco: el mismo día ejecutado
dos veces da números distintos.

**Decisión D-9:** (a) toda escritura es `UPSERT` sobre una clave natural
explícita; (b) cada ejecución del pipeline se registra en una tabla `pipeline_run`
con su estado por etapa, de modo que reanudar salta lo ya hecho; (c) los datos
derivados (indicadores, features, scores) llevan la `fecha_descarga` de la
instantánea que los produjo, que es lo que ya hace `Instantanea` y lo que permite
reproducir un score de hace tres meses.

### I-10. §8 FeatureSnapshot, tal como está descrito, no cabe cómodamente en Postgres
Guardar todas las features de todos los valores todos los días es, con 2.000
valores × 80 features × 252 días × 10 años, del orden de 400 millones de celdas.
Postgres lo aguanta, pero es la tabla equivocada para un acceso analítico
(«dame todas las features de 2019 para entrenar»).

**Decisión D-10: almacenamiento híbrido.** Postgres es el sistema de registro y
lo que sirve la API (entidades, precios, scores, señales, usuarios, carteras).
Las features y el histórico de entrenamiento viven en **Parquet particionado**
(como ya hace `datos/almacen.py`), consultado con DuckDB cuando haga falta SQL.
La trazabilidad de §8 se garantiza igual: cada `ModelPrediction` apunta a un
`feature_set_version` + hash del fichero de features, y ese fichero es inmutable.

### I-11. Celery + Redis + Next.js + FastAPI + Postgres contra «presupuesto reducido» (§50)
Cada pieza tiene coste operativo, no sólo económico.

**Decisión D-11:** se arranca con Postgres + un contenedor `worker` con
APScheduler, y Redis **sólo como caché**. Celery entra cuando haya una razón
concreta (paralelismo real entre mercados, reintentos con backoff persistente),
no antes. Un `docker-compose` de cuatro servicios cabe en un VPS de ~10 €/mes.

### I-12. §4 quiere ADRs, y los ADRs duplican empresas
Si el universo incluye a la vez `VALE3.SA` y `VALE` (el ADR), la misma empresa
aparece dos veces en el ranking y la cartera se concentra sin darse cuenta.

**Decisión D-12:** `Security` lleva `isin` y un `figi_compuesto`/`company_id`, y
el ranking deduplica por empresa quedándose con la línea de cotización principal
(la de mayor volumen en divisa base). Los ADRs entran en FASE 3, no antes.

### I-13. Falta en el encargo: pertenencia histórica al índice y valores deslistados
No aparece en ninguna sección, y es la fuente de sesgo de supervivencia más
grande que va a tener el sistema. Si el universo de hoy se aplica a 2018, se está
eligiendo con información del futuro: se backtestea sobre las empresas que
sobrevivieron.

**Decisión D-13:** `Security` lleva `fecha_alta`/`fecha_baja` y existe una tabla
`indice_composicion(indice, security_id, desde, hasta)`. El universo se evalúa
**a fecha**. El motor ya está preparado para esto. Mientras no haya fuente de
deslistadas, el informe publica el sesgo en lugar de disimularlo —que es lo que
ya hace hoy—.

### I-14. El idioma del código
El motor existente está íntegramente en español (identificadores y docstrings) y
está probado. El código nuevo mezclado daría un `Security.puntuacion_fundamental`.

**Decisión D-14:** el motor (`core/`) **no se traduce**: reescribir 7.600 líneas
probadas para cambiar nombres es riesgo puro sin beneficio. El código nuevo de
plataforma (esquema de BD, endpoints HTTP, frontend) va en inglés, que es la
convención del ecosistema y lo que espera cualquier desarrollador que se
incorpore. En la frontera hay una capa de adaptación explícita
(`backend/adapters/`) y un glosario en `docs/GLOSARIO.md`. Es una costura
deliberada y documentada, no un descuido.

---

## 2. Riesgos

### Riesgos de datos (los que pueden matar el producto)

| # | Riesgo | Impacto | Mitigación |
|---|---|---|---|
| RD-1 | **yfinance no es una fuente comercializable.** Es un scraper no oficial de Yahoo; sus condiciones no permiten redistribuir los datos en un producto de pago, no hay SLA y puede romperse cualquier día. | Bloquea la monetización, no el desarrollo | Desarrollar con ella; **antes de cobrar**, migrar a proveedor con licencia comercial (EODHD/FMP/Tiingo). La arquitectura de proveedores hace que sea cambiar una línea de configuración. Ver DATA_SOURCES.md. |
| RD-2 | **Fundamentales gratuitos con histórico corto** (~4 ejercicios) y **reexpresados**. | El backtest fundamental no puede empezar hasta el 4.º ejercicio; las reexpresiones introducen sesgo | Ya está medido y publicado por el informe (`origen_pit`). SEC EDGAR (EE. UU.) y CVM (Brasil) dan fechas de presentación reales y gratis: son la vía para eliminarlo en dos de los cuatro mercados. |
| RD-3 | **España e India no tienen fundamentales gratuitos fiables.** | Dos de los cuatro mercados pedidos quedan cojos | Aceptarlo y decirlo: esos mercados arrancan sólo con la pata técnica (`fundamental.activo: false` ya existe) hasta que haya proveedor de pago. No se inventa el hueco. |
| RD-4 | **Sesgo de supervivencia** (sin deslistadas). | Backtest optimista de forma sistemática | I-13. Publicar la magnitud; no prometer performance histórica hasta tener deslistadas. |
| RD-5 | Cambios de ticker, fusiones, splits mal aplicados. | Series rotas que parecen señales | El contrato ya caza OHLC incoherente y columnas vacías; añadir detección de saltos y reconciliación por ISIN. |

### Riesgos técnicos

| # | Riesgo | Mitigación |
|---|---|---|
| RT-1 | Sobreajuste al buscar parámetros hasta que el backtest salga bonito (§23). | Registro de experimentos obligatorio: cada backtest guarda parámetros, periodo, universo y resultado. El periodo de validación queda **cerrado** hasta el final (`validacion.fraccion_diseno: 0.70` ya lo hace). |
| RT-2 | Look-ahead reintroducido al añadir la capa SaaS (p. ej. un endpoint que lee la tabla de precios sin corte). | El acceso analítico pasa **siempre** por `VistaPuntual`. Test de arquitectura que falla si un módulo de scoring importa el almacén crudo. |
| RT-3 | Coste de LLM por petición. | Las explicaciones se cachean por `(security_id, fecha, hash_score)`. Un score que no cambia no se reexplica. |
| RT-4 | Volumen de precios (decenas de millones de filas) con ORM fila a fila. | Carga por `COPY`/`execute_values`, tabla particionada por año. SQLAlchemy para entidades, SQL directo para series. |
| RT-5 | El LLM inventa datos (§29). | El prompt recibe **sólo** JSON estructurado, con instrucción de responder «Información no disponible» ante un hueco, y un validador que rechaza la respuesta si menciona cifras que no estaban en la entrada. |

### Riesgos de producto y legales

| # | Riesgo | Mitigación |
|---|---|---|
| RP-1 | Recomendación personalizada = asesoramiento regulado (I-6). | D-6: separado por diseño y desactivado por defecto. |
| RP-2 | Recomendaciones generales bajo MAR sin los metadatos obligatorios. | Metadatos de autoría/metodología/fecha en `Signal` desde el día uno. |
| RP-3 | Publicar performance histórica de un backtest con los sesgos de RD-2/RD-4. | No publicar cifras de rentabilidad de cara al usuario hasta cerrar RD-4. El backtest es herramienta interna de validación antes que argumento de venta. |
| RP-4 | Prometer los 4 mercados con la misma profundidad cuando ES/IN van cojos (RD-3). | La UI muestra por mercado qué pilares están disponibles. |

---

## 3. Arquitectura final (resumen)

El detalle está en [ARCHITECTURE.md](ARCHITECTURE.md). Lo esencial:

```
Proveedores → Enrutador (+contrato) → Almacén (Parquet + Postgres)
                                          ↓
                                    VistaPuntual(fecha)      ← única puerta al pasado
                                          ↓
                            Indicadores → Features → Modelos
                                          ↓
                                   Scores → Señales
                                          ↓
                          API (FastAPI) → Explicación (LLM)
                                          ↓
                                   Frontend (Next.js)
```

La regla que no se rompe: **la IA generativa nunca produce un número**. Recibe
scores ya calculados y los redacta. Si el JSON de entrada no trae un dato, la
salida dice que no está disponible.

Estructura de directorios acordada:

```
core/        motor cuantitativo (el actual src/estrategia, sin dependencias web ni BD)
backend/     FastAPI: api/, db/, auth/, services/, adapters/
workers/     jobs programados (ingesta, indicadores, scores, señales, alertas)
ml/          feature store, entrenamiento, registro de modelos
frontend/    Next.js MVP
scripts/     entradas de línea de comandos (update_market_data.py, calculate_scores.py)
config/      YAML de reglas, universo, implementación
docs/        esta documentación
tests/       unitarios, integración, ML, anti-sesgo
```

`core/` no importa nada de `backend/`. Esa dirección única es lo que permite
seguir corriendo backtests sin levantar base de datos, y lo que impide que la
lógica de negocio se contamine de detalles de transporte.

---

## 4. Decisiones registradas

| ID | Decisión | Motivo |
|---|---|---|
| D-1 | Reutilizar el motor existente como `core/` en vez de empezar de cero | 7.600 líneas probadas resuelven ya lo más difícil |
| D-2 | Cinco mercados (ES, US, DE, IN, BR) | Alemania ya funciona |
| D-3 | Pilares ortogonales + sub-scores; sólo los pilares agregan | Evitar contar momentum y calidad dos veces |
| D-4 | El score es percentil dentro de cohorte (mercado × sector) | Un 0-100 absoluto no discrimina ni compara peras con manzanas |
| D-5 | Benchmark de retorno total para el target | Comparar TR contra índice de precio sesga la etiqueta |
| D-6 | Personalización tras flag, desactivada; análisis descriptivo de cartera sí | MiFID II / MAR |
| D-7 | ML sólo con universo ≥1.000 y ≥15 años; walk-forward purgado con embargo | La muestra actual no da para ML |
| D-8 | Pilar no disponible ⇒ renormalizar pesos, nunca imputar 50 | No inventar datos |
| D-9 | UPSERT + `pipeline_run` + sello de `fecha_descarga` | Idempotencia real |
| D-10 | Postgres para servir, Parquet/DuckDB para analítica | Cada acceso a su almacén |
| D-11 | Sin Celery al principio; Redis sólo caché | Coste operativo |
| D-12 | Deduplicación por empresa vía ISIN; ADRs en FASE 3 | Evitar doble conteo |
| D-13 | Universo evaluado a fecha, con altas y bajas | Sesgo de supervivencia |
| D-14 | `core/` en español, plataforma nueva en inglés, glosario y capa de adaptación | No reescribir código probado sólo por nombres |

---

## 5. Criterio de éxito del MVP

Los 16 puntos de §61, con dos matices honestos derivados del análisis:

- El punto 6 («demostrar performance histórica sin look-ahead bias») se cumple
  para el look-ahead —ya está resuelto y probado— pero **no** para el sesgo de
  supervivencia hasta cerrar RD-4. El MVP publica ambos hechos.
- El punto 1 («los cuatro mercados funcionen») se cumple con la pata técnica en
  los cuatro y la fundamental en aquellos donde haya datos (RD-3). Qué funciona
  en cada mercado es visible en la API, no letra pequeña.

Y la prueba concreta de §60, que es el objetivo operativo real:

```bash
python scripts/update_market_data.py     # datos de US, ES, BR, IN (y DE)
python scripts/calculate_scores.py       # scores reproducibles y almacenados
curl localhost:8000/api/v1/rankings?market=us&limit=20
curl localhost:8000/api/v1/stocks/AAPL/analysis
```
