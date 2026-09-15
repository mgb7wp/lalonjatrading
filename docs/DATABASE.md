# Base de datos

29 tablas en PostgreSQL 16. El esquema vive en `backend/db/models/` y las
migraciones en `backend/db/migrations/`.

Este documento explica **por qué** el esquema es como es. El detalle campo a
campo está en los modelos, comentado; duplicarlo aquí garantizaría que las dos
versiones se contradijeran en tres meses.

## Puesta en marcha

```bash
python scripts/init_db.py          # migraciones + datos de referencia
python scripts/init_db.py --solo-migraciones
```

Idempotente de principio a fin: se ejecuta en cada arranque del contenedor `api`.
Un script de inicialización que sólo se puede ejecutar una vez acaba
ejecutándose a mano, y un paso manual en un despliegue es un paso que algún día
se olvida.

Migración nueva:

```bash
alembic revision --autogenerate -m "lo que cambia"
alembic upgrade head
```

## Qué hay

| Grupo | Tablas |
|---|---|
| Referencia | `country`, `currency`, `market`, `exchange`, `security`, `index_composition` |
| Series | `price`, `fundamental_snapshot`, `technical_indicator`, `fx_rate`, `corporate_action` |
| Análisis | `model_version`, `feature_snapshot`, `score`, `model_prediction`, `signal`, `explanation` |
| Usuario | `user_account`, `portfolio`, `portfolio_position`, `portfolio_transaction`, `watchlist`, `watchlist_item`, `alert`, `alert_event`, `saved_screener` |
| Operación | `pipeline_run`, `data_quality_check`, `data_freshness` |

## Las decisiones que sostienen el esquema

### Un score no existe sin la versión de modelo que lo produjo

`score.model_version_id` es una clave ajena **NOT NULL**. No es una convención:
es imposible insertar una puntuación huérfana, ni desde la aplicación, ni desde
una carga masiva, ni desde un script de emergencia a las dos de la mañana.

Es lo que convierte el «model drift sin control» que teme §8 del encargo en algo
que no puede pasar, en lugar de algo que no debería pasar. Lo mismo vale para
`signal` y `model_prediction`.

Los cinco perfiles de §18 —crecimiento, valor, equilibrado, momentum, bajo
riesgo— no son código: son cinco filas de `model_version` con pesos distintos en
`parameters` (JSONB). Un perfil nuevo no puede exigir una migración.

### `publication_date` es obligatoria

Una fila de `fundamental_snapshot` sin fecha de publicación no permite saber qué
se sabía en cada momento, y cualquier backtest que la toque pasa a usar
información del futuro. El contrato del motor ya la exige; la base de datos la
exige otra vez, porque una carga masiva no pasa por el contrato.

Además hay un `CHECK` de que `publication_date >= period_end`: publicar antes de
cerrar el periodo es imposible, y cuando aparece es un mapeo roto del proveedor.
De los que no se notan, porque el dato parece razonable y sólo adelanta la
información unos meses — que es exactamente lo que infla un backtest.

`pit_origin` distingue `captured` (una foto tomada en su momento) de
`reconstructed` (deducido después, que es lo que dan los proveedores gratuitos
porque reexpresan las cifras a hoy). Se guarda en lugar de disimularse: el
informe publica el porcentaje de filas reconstruidas.

### El score es un percentil, no una magnitud

`score.cohort_used` y `score.n_cohort` van en cada fila. Un 87 significa «mejor
que el 87 % de su cohorte ese día», y sin saber cuál era la cohorte y cuántos
había, una puntuación rara no se puede rastrear hasta su causa real: una cohorte
de cuatro empresas donde el percentil no significa nada.

Un pilar sin datos se guarda como **NULL**, nunca como un 50 «neutro». Imputar
un valor medio no es conservador: mueve el ranking con un dato que nadie ha
medido. `available_pillars` deja constancia de sobre qué pilares se renormalizaron
los pesos.

`risk` va invertido a propósito: **100 = menor riesgo relativo**.

### Toda serie tiene clave natural única

`price(security_id, date)`, `fundamental_snapshot(security_id, period_end,
period)`, `score(security_id, date, model_version_id)`… De ahí cuelga la
idempotencia del pipeline: sin una clave sobre la que hacer `UPSERT`, reejecutar
un día duplica filas. Hay un test que recorre el esquema y falla si una serie
nueva se olvida de la suya.

`pipeline_run` completa la otra mitad: su clave `(pipeline, stage, run_date,
market_id)` permite reanudar saltando lo ya hecho en vez de repetirlo.

### El universo se evalúa a fecha

`security` lleva `listed_from`, `listed_to` e `is_primary_listing`, y existe
`index_composition`. Sin eso, aplicar el universo de hoy a 2018 es elegir con
información del futuro: se backtestea sobre las empresas que sobrevivieron. Es
el sesgo de supervivencia, el más grande que arrastra hoy el sistema.

`company_id` agrupa las líneas de cotización de una misma empresa (ADR y local)
para que el ranking no la cuente dos veces. `isin` **no** es único a propósito:
una misma empresa cotiza en varias plazas con el mismo ISIN, y ése es justo el
caso que hay que poder representar.

### `price` está particionada por año

Con cinco mercados y una década son decenas de millones de filas. Sin partición,
recargar un año obliga a un `DELETE` masivo y el índice se degrada.

Las particiones van de 2000 a 2035 y **no hay partición por defecto**: una fecha
fuera de ese rango es casi siempre un error de mapeo del proveedor, y es mejor
que falle al cargar a que se acumule en un cajón de sastre donde nadie la mira.
Añadir años es una migración de una línea.

La clave primaria de una tabla particionada tiene que incluir la columna de
partición, lo que aquí coincide con la clave natural: no hace falta un `id`
sintético que sólo serviría para permitir duplicados.

### El P&L se deriva de las transacciones

`portfolio_transaction` es la fuente de verdad. `portfolio_position` es una vista
materializada que se reconstruye a partir de ella y nunca se edita a mano.
Denormalizar el P&L es cómodo hasta el día que alguien corrige una compra de hace
ocho meses.

Cada transacción congela su `fx_rate_to_base`: recalcularlo con el tipo de hoy
reescribiría la historia de la cartera cada mañana.

### Detalles que se pagan caros si se dejan para después

- **`user_account`, no `user`**: `user` es palabra reservada en Postgres.
- **Correo único sin distinguir mayúsculas** (índice funcional sobre
  `lower(email)`). Si no, `Ana@x.com` y `ana@x.com` son dos cuentas y la segunda
  no puede recuperar la contraseña.
- **`alert_event(alert_id, dedupe_key)` único**: sin él, la idempotencia del
  pipeline acaba fallando en el buzón del usuario.
- **`Numeric`, no `float`**, para precios e importes: un backtest tiene que dar
  el mismo número dos veces, y la suma de flotantes depende del orden.
- **Vocabularios cerrados como texto + `CHECK`**, no como `ENUM` nativo. Un
  `ENUM` nativo convierte cada ampliación del vocabulario en una migración
  delicada; texto con `CHECK` da la misma garantía y se modifica sin ceremonia.
- **Convención de nombres de restricciones** fijada antes de la primera tabla.
  Sin ella Postgres inventa nombres y Alembic genera migraciones que no saben qué
  borrar. Y como Postgres trunca los identificadores a 63 caracteres, hay un test
  que falla si alguno se pasa: el error aparecería si no al generar la migración,
  con un mensaje que no dice qué restricción es.

## Dónde NO están los datos

Las **features de entrenamiento no viven en Postgres** (decisión D-10). Con
2.000 valores, 80 features y una década son cientos de millones de celdas cuyo
acceso natural es analítico («todas las features de 2019»), no transaccional.
Viven en Parquet particionado y `feature_snapshot` guarda el puntero con su
hash, que es lo que convierte «éstas son las features que usó el modelo» en una
afirmación verificable.

Postgres es el sistema de registro y lo que sirve la API. Parquet es el almacén
analítico. Los produce el mismo pipeline.

## Tests

`tests/test_db.py`. Los estructurales (metadatos de SQLAlchemy) corren siempre;
los de integración se saltan solos si no hay Postgres accesible, para que la
suite siga corriendo en un portátil sin Docker.

La base de datos de pruebas **se recrea entera y se migra desde cero en cada
sesión**: el criterio de aceptación de la FASE 2 se ejerce en cada ejecución en
lugar de comprobarse a mano una vez. La fixture se niega a trabajar sobre una
base de datos cuyo nombre no contenga `test`, para que un `pytest` lanzado con el
`.env` de desarrollo cargado no pueda vaciar la de uno.
