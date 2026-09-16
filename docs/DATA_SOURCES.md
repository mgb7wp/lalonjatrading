# Fuentes de datos

Qué se puede obtener gratis para cada mercado, qué no, y qué hay que pagar antes
de cobrar a nadie. Es el documento que pide §50 del encargo.

> **Estado de verificación.** El entorno donde se desarrolla tiene la salida de
> red restringida por política (`403` en CONNECT hacia `sec.gov`,
> `ecb.europa.eu`, `stooq.com`), así que **los endpoints y límites de abajo
> siguen sin comprobarse en vivo**. Están escritos a partir de documentación
> conocida y marcados con su estado. Las cuotas y precios de las APIs cambian a
> menudo.
>
> `python scripts/verify_sources.py` ya existe (FASE 3) y es lo que convierte
> cada hipótesis en un hecho. Ejecutado aquí devuelve `403` en las tres, que es
> el resultado honesto. **Ninguna fila marcada `POR VERIFICAR` debe convertirse
> en dependencia del pipeline sin pasar antes por ahí.**
>
> Lo que sí está probado sin red es el **parseo** de las tres fuentes nuevas,
> contra respuestas grabadas y contra el contrato de datos
> (`tests/test_ingesta.py`). Es donde de verdad se puede uno equivocar; lo que
> no se puede saber sin red es si los campos que devuelve la API real se llaman
> como dice su documentación.

Para cómo se añade una fuente al código, ver [FUENTES.md](../FUENTES.md), que
sigue vigente y describe el mecanismo (interfaz, capacidades, registro,
contrato).

---

## 1. Resumen ejecutivo

**Precios: resuelto y gratis para los cinco mercados.**
**Fundamentales: resuelto y gratis sólo en EE. UU. y Brasil.** España e India no
tienen fuente gratuita fiable con fechas de publicación reales.

Y el hecho que condiciona el negocio, no el desarrollo:

> **yfinance no sirve para un producto de pago.** Es un cliente no oficial que
> raspa Yahoo Finance. Sus condiciones de uso no contemplan redistribuir los
> datos en un servicio comercial, no hay SLA y la biblioteca se rompe cada vez
> que Yahoo cambia algo. Es perfectamente válida para **construir, backtestear y
> validar**. No lo es para facturar. La migración a un proveedor con licencia es
> un cambio de configuración, no de arquitectura, y está presupuestada en la
> FASE 18 del roadmap.

---

## 2. Qué hace falta y quién lo da

### 2.1 Precios (OHLCV, ajustados, splits, dividendos)

| Fuente | Mercados | Clave | Coste | Estado | Notas |
|---|---|---|---|---|---|
| **yfinance** | ES, US, DE, IN, BR | no | 0 € | **EN USO, probado** | Ajustado y bruto. Revisa el pasado hacia atrás: por eso se guarda `fecha_descarga`. Sin deslistadas. Uso no comercial. |
| **Stooq** | US, DE, ES amplios; IN/BR por confirmar | no | 0 € | POR VERIFICAR | CSV directo, sin clave. Buen *fallback* de precios EOD. Cobertura de India y Brasil a comprobar ticker a ticker. |
| **Alpha Vantage** | global | sí | 0 € (cuota muy baja) | POR VERIFICAR | La cuota gratuita del plan básico es del orden de decenas de peticiones **al día**. Con 140 valores × 5 mercados no es viable como fuente principal. |
| **EODHD** | global | sí | ~20-80 €/mes | POR VERIFICAR | Candidata principal para comercializar. Adaptador ya escrito (`eodhd_proveedor.py`), **nunca ejecutado con clave real**. |

**Recomendación:** yfinance como dueña, Stooq como respaldo de precios una vez
verificada su cobertura.

### 2.2 Tipos de cambio

| Fuente | Estado | Notas |
|---|---|---|
| **BCE (Data Portal)** | POR VERIFICAR | Oficial, gratuito, sin clave, tipos de referencia diarios EUR→X. Es la fuente correcta para una cartera en euros. **Cuidado:** se publican por la tarde (CET), así que la decisión del día usa el tipo de D-1 (`fx_decision_dia_anterior: true` ya lo implementa). |
| **yfinance** | EN USO | Sirve hoy. Sustituir por BCE cuando se verifique: es oficial y estable. |

### 2.3 Fundamentales — aquí está el problema real

| Mercado | Fuente gratuita | Fechas de publicación reales | Histórico | Estado |
|---|---|---|---|---|
| **EE. UU.** | **SEC EDGAR** (`data.sec.gov`, XBRL `companyfacts`) | **Sí** (`filed`) | 2009→ | **ADAPTADOR ESCRITO** (FASE 3); parseo probado, red POR VERIFICAR |
| **Brasil** | **CVM Dados Abertos** (DFP anuales, ITR trimestrales, CSV por año) | **Sí** (fecha de recepción) | ~2010→ | POR VERIFICAR — prioridad alta (FASE 5) |
| **España** | — | No | — | **Sin fuente gratuita fiable.** La CNMV publica los informes financieros, pero no en formato explotable de forma sistemática. BME/SIX es de pago. |
| **India** | — | No | — | **Sin fuente gratuita fiable.** NSE y BSE exponen endpoints públicos, pero sus condiciones no permiten uso sistemático ni comercial. |
| **Alemania** | Bundesanzeiger | Parcial | — | No explorado. Baja prioridad. |
| *Todos (respaldo)* | yfinance | **No** (estimadas) | ~4 ejercicios | EN USO |

**Por qué SEC EDGAR y CVM importan tanto:** dan la **fecha real de
presentación**. Son gratuitas, oficiales y su uso está expresamente permitido.

Y en el caso de EDGAR hay algo más fuerte que la fecha, que es lo que hace que
sea la única fuente del proyecto que puede marcar `pit_origin = captured`:

> `companyfacts` no devuelve una cifra por periodo: devuelve **todas las veces
> que esa cifra se ha publicado**, cada una con su expediente y su fecha. Cuando
> una empresa reexpresa sus cuentas, o repite las del año anterior como
> comparativa, aparece otra entrada del mismo periodo con fecha posterior.
> Quedándose con la de fecha **más antigua** se obtiene la cifra tal y como se
> publicó entonces, no la reexpresada a hoy.

Eso es literalmente lo que significa point-in-time, y ninguna otra fuente del
proyecto puede ofrecerlo: EODHD da la fecha real pero las cifras reexpresadas, y
yfinance no da ni una cosa ni la otra. El adaptador
(`core/estrategia/datos/sec_proveedor.py`) lo implementa y hay un test dedicado.

Dos límites del adaptador, escritos para que nadie los descubra por sorpresa:
sólo cubre **ejercicios anuales** (10-K), que es lo que consume el filtro
fundamental, y **no da EV**, porque la SEC publica cuentas y no cotizaciones —el
motor lo calcula en la fecha de decisión a partir de las acciones en
circulación—.

**Qué se hace con España e India mientras tanto.** No se inventa el hueco. Esos
mercados arrancan con la **pata técnica solamente** (`fundamental.activo: false`
ya existe en la configuración) y la API declara por mercado qué pilares están
disponibles. Cubrirlos de verdad requiere proveedor de pago, y eso se decide
cuando haya usuarios que lo paguen.

### 2.4 Datos de empresa (ISIN, sector, industria, capitalización)

yfinance da sector e industria con taxonomía propia, ya mapeada en
`config/implementacion.yaml`. ISIN: cobertura irregular; para deduplicar ADRs
(D-12) hará falta completarlo, y la vía gratuita más sólida en EE. UU. es el
propio EDGAR (CIK ↔ ticker).

### 2.5 Acciones corporativas

Splits y dividendos vienen con los precios ajustados de yfinance. Fusiones,
cambios de ticker y bajas: **sin fuente gratuita**. Es la causa del sesgo de
supervivencia (RD-4) y hoy se publica en lugar de disimularse.

### 2.6 Noticias, analistas, insiders, short interest

| Dato | Gratuito y legal | Decisión |
|---|---|---|
| Noticias con licencia para reproducir | No, a escala | Pilar `sentimiento` = `unavailable` |
| Sentimiento de noticias | No | Ídem |
| Revisiones de analistas | No (de pago) | Ídem |
| Insider trading EE. UU. | **Sí** — EDGAR Forms 3/4/5 | Candidato FASE 16+, sólo EE. UU. |
| Short interest EE. UU. | Parcial (FINRA, quincenal) | Candidato posterior |
| Earnings surprise | Requiere estimaciones (de pago) | No en el MVP |

Conforme a §16 y §29: **si no hay dato fiable, el score queda no disponible**. Y
conforme a D-8, los pesos se renormalizan sobre los pilares disponibles; nunca se
imputa un 50 «neutro», porque eso es inventar un dato que mueve el ranking.

### 2.7 Benchmarks

Configurados hoy: `^IBEX`, `^GSPC`, `^GDAXI`, `^NSEI`, `^BVSP`.

> **Aviso importante (D-5).** Estos son índices **de precio**, sin dividendos.
> Las series de las acciones sí vienen ajustadas por dividendos. Usar unos contra
> otras para construir el target `return_stock > return_benchmark` regala a cada
> acción la rentabilidad por dividendo del índice —2-4 % anual en IBEX e
> Ibovespa— y **sesga la etiqueta de entrenamiento hacia el 1**. Para el target
> hay que usar la versión *total return* del índice o restar el dividendo a la
> acción. Para detectar el **régimen** (§26) el índice de precio vale: allí sólo
> se mira la tendencia.

---

## 3. Tabla por proveedor (formato §50)

### yfinance
- **Aporta:** precios OHLCV ajustados y brutos, FX, sectores, fundamentales básicos, en los 5 mercados.
- **Coste:** 0 €. **Límites:** sin cuota documentada; se autolimita con pausas. Se rompe cuando Yahoo cambia.
- **Fiabilidad:** media. Revisa el pasado hacia atrás.
- **Legal:** cliente no oficial. **No apto para producto comercial.**
- **Respaldo:** Stooq (precios), EODHD (fundamentales).

### SEC EDGAR — *prioridad alta*
- **Aporta:** fundamentales XBRL de EE. UU. **con fecha de presentación real**; CIK↔ticker; insiders.
- **Coste:** 0 €. **Límites:** ~10 peticiones/s y `User-Agent` identificativo obligatorio.
- **Fiabilidad:** máxima (es el registro oficial).
- **Legal:** uso público expresamente permitido.
- **Respaldo:** yfinance (degradado a `reconstructed`).

### CVM Dados Abertos (Brasil) — *prioridad alta*
- **Aporta:** DFP/ITR con fecha de recepción; histórico ~2010.
- **Coste:** 0 €. **Límites:** descarga de ZIP/CSV anuales, no API por ticker; requiere un proceso de carga en bloque.
- **Legal:** datos abiertos oficiales.
- **Respaldo:** yfinance.

### BCE Data Portal — *adaptador escrito*
- **Aporta:** tipos de referencia EUR diarios. **Coste:** 0 €. **Legal:** abierto.
- **Cuidado:** se fijan sobre las 14:15 CET, así que decidir una operación con el
  tipo del mismo día es usar un dato que a esa hora no existía. La configuración
  ya lo resuelve (`fx_decision_dia_anterior: true`), pero es el tipo de sesgo que
  se reintroduce solo en cuanto alguien «simplifica».
- Sin datos en fines de semana ni festivos de TARGET. **No se rellenan**: el
  motor busca el último tipo conocido en o antes de la fecha, así que el hueco se
  resuelve solo y sin inventar una cotización que no existió.

### Stooq — *adaptador escrito, no apto todavía como fuente principal*
- **Aporta:** EOD multi-mercado sin clave. **Coste:** 0 €.
- **Uso previsto:** respaldo de precios si se cae yfinance.
- **Lo que no se sabe, y hay que saber:** Stooq no documenta con claridad sobre
  qué base ajusta. Que ajuste por *splits* es casi seguro; por **dividendos, no**.
  Y la diferencia no es un detalle: si no ajusta por dividendos y se usa como
  dueña de precios, **cada reparto se convierte en una caída que el motor leerá
  como señal**.
- Por eso el adaptador declara la duda en sus capacidades —de donde el informe
  saca sus avisos—, devuelve `cierre_bruto` igual al cierre en lugar de fingir
  que distingue dos series que no ha podido distinguir, y tiene una comprobación
  dedicada en `verify_sources.py` que lo compara con yfinance sobre un valor con
  dividendo alto. Si divergen de forma sistemática, no ajusta.
- **Cobertura de IN/BR por verificar.**

### EODHD — *de pago, para comercializar*
- **Aporta:** fundamentales con ~20 años y `filing_date` real, cobertura global, deslistadas en planes altos.
- **Coste:** ~20-80 €/mes según plan (POR VERIFICAR).
- **Estado:** adaptador escrito contra la documentación y probado con respuestas grabadas; **nunca ejecutado con clave real**.
- **Por qué se justifica:** es lo que arregla a la vez España, India, el histórico corto y la licencia comercial.

---

## 4. Plan de acción

| Orden | Acción | Estado | Qué resuelve |
|---|---|---|---|
| 1 | `scripts/verify_sources.py` | ✅ escrito (FASE 3) | Convierte cada hipótesis de este documento en un hecho |
| 2 | Adaptador **SEC EDGAR** | ✅ escrito (FASE 3) | PIT **real** en EE. UU.: cifras de su momento, no reexpresadas |
| 3 | Adaptador **BCE** para FX | ✅ escrito (FASE 3) | FX oficial y estable |
| 4 | Adaptador **Stooq** como respaldo | ✅ escrito (FASE 3) | Que caiga yfinance y no caiga el sistema |
| 5 | **Ejecutar `verify_sources.py` con red** y rellenar los `POR VERIFICAR` | ⏳ pendiente, requiere red | Que los tres adaptadores dejen de ser hipótesis |
| 6 | Adaptador **CVM** | FASE 5 | PIT real en Brasil |
| 7 | Evaluar **EODHD** con clave real | FASE 8 | España, India, histórico y licencia |
| 8 | Deslistadas y composición histórica de índices | post-MVP | Sesgo de supervivencia (RD-4) |

**El paso 5 es tuyo, no mío.** Los tres adaptadores están escritos y su parseo
probado, pero ninguno se ha ejecutado nunca contra su API. La primera ejecución
con red es la que dirá si los campos se llaman como dice la documentación.

---

## 5. Reglas que no dependen del proveedor

1. **Ningún dato entra sin pasar el contrato** (`core/datos/contrato.py`),
   aplicado en el enrutador. Ninguna columna obligatoria puede venir entera a
   nulo: un hueco suelto es normal, una columna vacía es un mapeo roto.
2. **Cada fila lleva su procedencia** (`fuente`, `fecha_descarga`). Sin eso, al
   mezclar orígenes el backtest deja de ser reproducible.
3. **Cada fuente declara sus capacidades** y el informe genera sus avisos a
   partir de ahí. Exagerarlas no mejora el sistema: hace que deje de avisar de
   sus límites.
4. **Las claves van en variables de entorno**, nunca en el repositorio.
5. **Si un proveedor falla**, se reintenta con backoff, se recurre al respaldo si
   lo hay, se sirve de caché marcando el dato como `stale`, y se registra. No se
   detiene la aplicación (§48).
