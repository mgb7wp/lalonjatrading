# Fuentes de datos

De dónde sale cada dato, cómo se añade una fuente nueva y qué tiene que cumplir.

## Cómo se reparte el trabajo

Cada tipo de dato tiene una fuente dueña, declarada en `config/reglas.yaml`:

```yaml
proveedor_datos:
  precios: yfinance
  fundamentales: eodhd
  divisas: yfinance
  sectores: eodhd
```

También vale la forma corta del documento, `nombre: yfinance`, que significa
«esta fuente para todo». Lo específico gana sobre el atajo.

El reparto por especialidad es lo que resuelve el problema real de este
proyecto: quedarse con los precios gratuitos de yfinance y traer los
fundamentales de una fuente con histórico largo y fechas de publicación reales.

`--proveedor` en la línea de comandos fuerza una sola fuente para todo,
ignorando el reparto. Es cómodo para trabajar sin red (`--proveedor sintetico`)
o para probar una fuente concreta.

## Las fuentes que hay

| Fuente | Sirve | Histórico fundamental | Fechas de publicación | Clave |
|---|---|---|---|---|
| `sintetico` | todo | — | inventadas | no |
| `yfinance` | todo | ~4 ejercicios | estimadas por retraso fijo | no |
| `eodhd` | fundamentales, sectores | ~20 años | **reales** (`filing_date`) | sí |

### `sintetico`

Datos inventados y deterministas. No es un apaño para los tests: es la única
forma de ejercitar casos que con datos reales aparecen cuando quieren —un hueco
por debajo del stop, una empresa que deja de pasar el filtro a mitad de camino,
un mercado con el régimen apagado—. Están guionados en `datos/sintetico.py`.

Cualquier informe generado con esta fuente va marcado como sintético en la
cabecera y en el nombre del fichero.

### `yfinance`

Gratis y sin clave, cubre los cinco mercados. Sus límites condicionan lo que se
puede concluir, y por eso el informe los repite:

- Unos **cuatro ejercicios** de fundamentales. Como el crecimiento de ventas a
  tres años necesita **cuatro** ejercicios publicados, la estrategia no puede
  operar hasta que llega el cuarto: del orden de tres años y medio desde el
  inicio de los datos.
- **Sin fecha real de publicación**: se estima sumando el retraso configurado.
- **Cifras reexpresadas** a día de hoy.
- **Sin empresas deslistadas**, de ahí el sesgo de supervivencia.

### `eodhd`

La ampliación que ya contemplaba el documento (`ampliacion_futura: eodhd`).
Aporta histórico largo y **la fecha real de presentación de cada ejercicio**, que
es lo que elimina la estimación por retraso fijo.

Conviene no difuminar una distinción: una fecha real arregla **cuándo** se supo
algo, no **qué versión** se supo. Los fundamentales estándar siguen viniendo
reexpresados a hoy, así que las filas siguen saliendo con
`origen_pit: reconstruido`. Lo único que convierte eso en `capturado` es la foto
semanal.

La clave va en `EODHD_API_KEY`, nunca en el repositorio. **No se ha podido
ejecutar**: se escribió contra la documentación de la API y se probó con
respuestas grabadas.

## Cómo se añade una fuente

Cinco pasos, y ninguno toca el motor.

**1. Escribe el adaptador** en `src/estrategia/datos/`, heredando de
`ProveedorPrecios`, `ProveedorFundamentales` o `Proveedor` según lo que sirva.

**2. Declara sus capacidades.** No es documentación: el informe las lee para
saber de qué tiene que avisar.

```python
@property
def capacidades(self) -> Capacidades:
    return Capacidades(
        tipos=("fundamentales",),
        anios_fundamentales=20,
        fechas_publicacion_reales=True,
        cifras_reexpresadas=True,
        incluye_deslistadas=False,
        necesita_clave=True,
    )
```

Rellenarlo con optimismo no mejora el sistema: hace que deje de avisar de sus
propios límites.

**3. Registra la fuente** en `datos/registro.py`, con importación perezosa:

```python
def _mi_fuente(cfg):
    from .mi_fuente import ProveedorMiFuente
    return ProveedorMiFuente(cfg)

registrar("mi_fuente", _mi_fuente)
```

**4. Separa el parseo en funciones puras.** Es donde de verdad se puede uno
equivocar, y es lo único que se puede probar sin clave y sin red. `eodhd` tiene
`parsear_fundamentales()` y `parsear_sector()` fuera de la clase por eso.

**5. Añade sus respuestas grabadas** y comprueba que pasa el contrato:

```python
def test_lo_que_devuelve_mi_fuente_cumple_el_contrato(cfg):
    filas = parsear_fundamentales(_payload(), "X.MC", "es", cfg, date.today())
    inf = contrato.verificar_fundamentales(pd.DataFrame(filas), "mi_fuente")
    assert inf.cumple, [str(i) for i in inf.incumplimientos]
```

## El contrato

Ningún dato entra en el almacén sin pasar por `datos/contrato.py`. Se aplica en
el enrutador, en el único sitio por el que pasan todos los datos, así que no
depende de que quien escriba el adaptador se acuerde.

Comprueba columnas presentes y tipos, fechas ordenadas y sin duplicados,
coherencia OHLC, fechas de publicación presentes, y **ninguna columna
obligatoria entera a nulo**.

Esa última es la que más vale, y tiene una historia concreta detrás. El proveedor
de yfinance devolvía la columna `ev` entera a nulo —con un comentario que decía
que se completaría más adelante y que nadie completó—. El efecto: EV/EBIT no se
podía calcular nunca, la valoración puntuaba cero para todas las empresas y **la
mitad del peso de la puntuación fundamental dejaba de hacer nada**. Ni se caía
nada ni salía ningún aviso; el ranking simplemente pasaba a decidirse solo por
calidad.

La lección no es «revisar mejor»: es que una fuente puede cumplir la forma del
contrato y no su fondo. Un hueco suelto es un dato que falta, cosa normal; una
columna entera vacía es un mapeo roto. Las fuentes nuevas traerán fallos de esa
misma familia con otro nombre, y el contrato los convierte en un error ruidoso.

## Procedencia

Cada fila de precios y de fundamentales lleva una columna `fuente`, que estampa
el enrutador. Sin eso, en cuanto se mezclan orígenes el backtest deja de ser
reproducible y un número raro no hay por dónde cogerlo.

## Antes de fiarte de una fuente nueva

```bash
estrategia --proveedor mi_fuente diagnostico --anos 8 --detalle
```

Devuelve, ticker a ticker, qué resuelve y qué no. Mira sobre todo la sección de
**Valoración (EV/EBIT)**: si muchos valores no tienen EV calculable, media
puntuación fundamental no está haciendo nada.

## Lo que está previsto

La arquitectura no debería tener que cambiar para nada de esto:

- **Más mercados.** Añadir uno es una entrada en `universo.mercados`, su
  calendario en `implementacion.yaml` y sus tickers. El documento menciona
  Francia (`.PA`) pero la configuración no la incluye; añadirla es eso.
- **Empresas deslistadas.** Es la única forma de atacar de verdad el sesgo de
  supervivencia. Necesita una fuente que las dé y campos de alta y baja por
  ticker en `universo.yaml`; el filtro de universo ya se evalúa a fecha, así que
  el motor está preparado.
- **Fundamentales point-in-time de verdad.** Convertiría `origen_pit` en
  `capturado` y quitaría el aviso más serio que emite hoy el informe. Mientras
  tanto, la foto semanal lo va construyendo desde cero.
- **Intradía.** No hace falta para una estrategia de revisión semanal, pero el
  contrato de precios ya distingue ajustado de bruto, que es lo que suele
  romperse al bajar de granularidad.
