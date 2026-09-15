# Estrategia mixta (fundamental + técnica) · especificación v0.1

Este documento define las reglas que debe implementar la app. Los valores numéricos son puntos de partida razonables, no parámetros optimizados ni recomendaciones de inversión. Ningún parámetro se cambia para mejorar un backtest sin anotarlo en el registro de cambios y volver a validarlo.

## Lógica general

El análisis fundamental decide qué empresas son candidatas, el técnico decide cuándo entrar y salir, y la gestión del riesgo decide cuánto comprar. Todos los parámetros viven en `config/reglas.yaml`, que se crea a partir del bloque del final de este documento, y el código no debe contener números sueltos.

## Universo

Multi-mercado desde el inicio, no solo España. La lista de tickers vive en `config/universo.yaml`, agrupada por mercado, con el sufijo que usa el proveedor de datos (p. ej. `.MC` para España, `.PA` para Francia, `.NS` para India, `.SA` para Brasil, sin sufijo para EE. UU.) y su divisa de cotización. Cada mercado se etiqueta como `desarrollado` o `emergente` según la clasificación de MSCI, porque esa etiqueta condiciona umbrales de liquidez, deslizamiento y validación, no solo estadística.

Una acción entra en el universo si su volumen medio diario negociado en los últimos tres meses, convertido a la divisa base con el tipo de cambio de cada fecha, supera `universo.volumen_minimo_desarrollado` o `universo.volumen_minimo_emergente` según corresponda; el mínimo es más alto en emergentes porque su liquidez real suele ser menor de lo que aparenta el dato agregado. En la versión 1 se excluyen bancos, aseguradoras e inmobiliarias en todos los mercados, porque ratios como deuda neta/EBITDA o EV/EBIT no son significativos para ellas; los nombres de sector deben mapearse a la clasificación del proveedor de datos, que no siempre coincide entre mercados.

## Filtro fundamental (qué)

Se recalcula cada vez que una empresa publica resultados, usando únicamente datos que ya eran públicos en esa fecha. Una empresa pasa el filtro si cumple todos los mínimos de `fundamental.minimos` (ROE, margen operativo, crecimiento anual compuesto de ventas a tres años, flujo de caja libre positivo y deuda neta/EBITDA máxima), con los umbrales especiales de `fundamental.excepciones_sector` cuando existan, como el de las eléctricas. Los percentiles para la puntuación se calculan **dentro de cada mercado**, no contra el universo global entero: comparar el ROE de una empresa india con el de una alemana mezcla normas contables y ciclos económicos distintos y no aporta nada útil. Entre las que lo pasan se calcula una puntuación fundamental de 0 a 100: la calidad es la media de los percentiles de ROE y margen operativo, la valoración es el percentil inverso de EV/EBIT (más barata, mejor puntuación), y ambas se combinan con los pesos de `fundamental.puntuacion`. La comparación final entre candidatas de mercados distintos se hace con esa puntuación ya percentilada, nunca con los ratios en bruto.

## Filtro técnico (cuándo)

La revisión es semanal: las señales se calculan con el cierre del último día hábil de la semana y las órdenes se ejecutan en la apertura de la sesión siguiente en el calendario de cada mercado (los festivos no coinciden entre países, así que "la sesión siguiente" se calcula por mercado, no de forma global). El momentum y las medias se calculan siempre sobre el precio en divisa local, para no mezclar la tendencia real del valor con el movimiento de su divisa; la conversión a la divisa base se aplica solo al valorar la cartera y calcular el riesgo, en `cartera.divisa_base`.

El régimen de mercado se comprueba por bloque, no con un único índice global: `tecnico.indices_regimen` mapea cada mercado o región a su índice (por ejemplo el IBEX para España, un índice de emergentes para esos mercados), y solo se abren posiciones nuevas en los mercados cuyo índice cierra por encima de su media de `tecnico.regimen_mercado_media` sesiones. Una empresa que ha pasado el filtro fundamental es comprable si, además, su cierre está por encima de la media de `tecnico.media_larga` sesiones, la media de `tecnico.media_corta` sesiones está por encima de la larga y su momentum 12-1 (rentabilidad de los últimos 12 meses sin contar el más reciente, en divisa local) es positivo. Las comprables se ordenan por una puntuación final que combina la fundamental y el percentil de momentum según `seleccion.pesos`, calculado dentro de cada mercado por el mismo motivo que en la sección anterior, y se compran por ese orden mientras queden huecos en la cartera.

## Salidas (hasta cuándo)

El stop inicial se sitúa `salidas.stop_inicial_atr` veces el ATR por debajo del precio de entrada. El stop dinámico es el cierre más alto desde la entrada menos `salidas.stop_dinamico_atr` veces el ATR; se recalcula a diario y nunca baja. En cada momento se aplica el más alto de los dos. Los stops se vigilan cada día: si el mínimo de la sesión toca el stop, la salida se hace al precio del stop, salvo que el valor abra ya por debajo, en cuyo caso se sale al precio de apertura. En la revisión semanal también se cierra la posición si el cierre queda por debajo de la media larga o si la empresa ha dejado de pasar el filtro fundamental tras publicar resultados.

## Tamaño de posición y cartera (cuánto)

Todo el cálculo de riesgo se hace en `cartera.divisa_base` (por defecto EUR): el precio de entrada, el stop y el capital se convierten con el tipo de cambio del día antes de calcular nada. Número de acciones = (capital actual × `riesgo.por_operacion`) ÷ (precio de entrada − stop inicial, ambos en divisa base), redondeado hacia abajo y limitado para que la posición no supere `cartera.peso_maximo` del capital. Se respetan `cartera.max_posiciones`, `cartera.max_por_sector` y `cartera.max_por_mercado`, este último para que un solo país no concentre el riesgo cambiario y de liquidez de la cartera. Si no hay candidatas, la cartera se queda en liquidez, y eso forma parte del sistema.

## Reglas contra sesgos (obligatorias)

Los precios deben estar ajustados por dividendos y splits en su divisa local. Los datos fundamentales se usan desde su fecha de publicación; si el proveedor no la ofrece, se supone que un trimestre no se conoce hasta `datos.retraso_trimestral_dias` días después de su cierre y un ejercicio completo hasta `datos.retraso_anual_dias` días después, con el valor específico de `datos.retraso_por_mercado` cuando exista, porque algunos mercados emergentes publican con más retraso que el europeo medio. Ninguna decisión puede usar datos posteriores al momento en que se toma, y debe haber tests que lo comprueben. Si el proveedor incluye empresas que dejaron de cotizar, el universo histórico debe incluirlas; si no, el informe debe advertir del sesgo de supervivencia, con especial atención a los mercados emergentes, donde las exclusiones y deslistados son más frecuentes.

Cada operación descuenta la comisión, el deslizamiento y el impuesto a la transacción que corresponda al mercado donde cotiza el valor, según la tabla `config/impuestos_transaccion.yaml` (un impuesto y un porcentaje por país; España usa su Impuesto sobre las Transacciones Financieras del 0,2% solo en compras de las empresas de la lista anual de la Agencia Tributaria; otros países tienen su propio impuesto o ninguno). El deslizamiento no es un único porcentaje global: `costes.deslizamiento_pct_por_mercado` permite fijar uno más alto en mercados emergentes o de menor liquidez, y el backtest debe usar el valor específico del mercado cuando exista.

Un mercado emergente puede limitar la repatriación de capital o imponer controles de cambio en momentos de estrés; la app no puede modelar esto con precisión, así que el informe debe incluir un aviso permanente de que la rentabilidad en divisa base asume que la conversión y salida de capital fueron siempre posibles al tipo de cambio de mercado, lo que no siempre ha sido cierto históricamente en algunos países.

Desde el primer día, la app guarda cada semana una copia de los datos fundamentales y del tipo de cambio de todo el universo con su fecha de descarga, para ir construyendo un histórico propio sin sesgo de anticipación.

## Validación e informe

El histórico se divide en un periodo de diseño (la fracción inicial `validacion.fraccion_diseno`) y un periodo de validación que no se consulta hasta tener una versión cerrada. Si se consulta muchas veces deja de ser una prueba independiente, así que la prueba definitiva de cada versión es operar en simulado. El informe muestra rentabilidad anualizada, drawdown máximo, ratio de Sharpe, porcentaje de operaciones ganadoras, número de operaciones y resultados por año, en conjunto y desglosados por mercado y por bloque desarrollado/emergente, porque una estrategia global puede parecer sólida en el agregado mientras una región concreta arrastra el resultado. La curva de capital se compara con dos referencias en divisa base que incluyan dividendos: un índice global desarrollado (MSCI World) y un índice de mercados emergentes (MSCI Emerging Markets), o ETFs equivalentes con precios ajustados y convertidos con el mismo tipo de cambio que usa la cartera. Incluye también un análisis de sensibilidad que mueve cada parámetro un `validacion.sensibilidad_pct` arriba y abajo para comprobar que los resultados no se desmoronan, y avisa de que no hay base para concluir nada si hay menos de `validacion.min_operaciones` operaciones en total o menos de `validacion.min_operaciones_por_mercado` en un mercado concreto.

## Fuera de la versión 1

Disparador de entrada por retroceso (RSI), salida por tiempo, métricas específicas para bancos y aseguradoras, estimación fiscal completa por país (España usa FIFO y la regla de los dos meses; otros países tienen sus propias reglas, no modeladas todavía), cobertura de riesgo de divisa con derivados, y alertas por Telegram o email. Cada mejora se evalúa primero en el periodo de diseño y después en simulado.

## Registro de cambios

| Fecha | Versión | Cambio | Motivo | Resultado en diseño |
|-------|---------|--------|--------|---------------------|
|       | 0.1     | Versión inicial (solo España) | — | — |
|       | 0.2     | Universo multi-mercado (desarrollados + emergentes), divisa base, percentiles por mercado, impuestos y deslizamiento por país, proveedor de datos gratuito (yfinance) | Ampliar el alcance a una cartera global | — |
|       | 0.3     | Cohorte de percentiles = universo elegible, posiciones de trazado de Hazen, suelo `min_empresas_percentil`; reglas de signo para EV/EBIT, EBITDA y patrimonio negativos; corte semanal global en UTC; reserva de huecos en el momento de decidir; FX de D-1 para decidir y de D para valorar; `vigente_desde` en los impuestos; lote por mercado; antigüedad máxima del dato fundamental | Corregir sesgos y degeneraciones detectados al implementar la v0.2 | — |
|       | 0.4     | Reparto de fuentes por tipo de dato con contrato verificable y procedencia por fila; EV calculado en la fecha de decisión a partir de acciones en circulación y precio; adaptador EODHD; informe HTML publicable; `panel.modo_publico` | Conectar fuentes reales y publicar el informe | — |

## Configuración (`config/reglas.yaml`)

```yaml
# Valores de partida, no optimizados

proveedor_datos:
  nombre: yfinance          # gratuito, sin clave; cubre precios de la mayoría de bolsas globales
  fundamentales_anos_disponibles: 4   # limitación conocida del proveedor gratuito
  ampliacion_futura: eodhd  # a evaluar solo si el histórico fundamental se queda corto

cartera:
  divisa_base: EUR
  capital_inicial_eur: 10000
  max_posiciones: 8
  max_por_sector: 3
  max_por_mercado: 3           # evita concentrar riesgo cambiario/liquidez en un solo país
  peso_maximo: 0.15

universo:
  mercados:
    - id: es
      sufijo: ".MC"
      divisa: EUR
      clasificacion: desarrollado
    - id: us
      sufijo: ""
      divisa: USD
      clasificacion: desarrollado
    - id: de
      sufijo: ".DE"
      divisa: EUR
      clasificacion: desarrollado
    - id: in
      sufijo: ".NS"
      divisa: INR
      clasificacion: emergente
    - id: br
      sufijo: ".SA"
      divisa: BRL
      clasificacion: emergente
  # lista completa de tickers por mercado en config/universo.yaml
  volumen_minimo_desarrollado: 500000   # en divisa base, media diaria, últimos 3 meses
  volumen_minimo_emergente: 1000000     # más exigente: la liquidez real suele ser menor
  excluir_sectores: [bancos, seguros, inmobiliarias]

datos:
  precios_ajustados: true
  retraso_trimestral_dias: 90          # valor por defecto si no hay fecha de publicación
  retraso_anual_dias: 120
  retraso_por_mercado:
    in: 105
    br: 100
  guardar_foto_fundamentales: semanal
  guardar_foto_fx: semanal

fundamental:
  minimos:
    roe: 0.10
    margen_operativo: 0.08
    crecimiento_ventas_3a: 0.00
    flujo_caja_libre_positivo: true
    deuda_neta_ebitda_max: 3.0
  excepciones_sector:
    electricas:
      deuda_neta_ebitda_max: 5.0
  percentiles: por_mercado             # nunca comparar ratios en bruto entre mercados
  puntuacion:
    peso_calidad: 0.5
    peso_valoracion: 0.5

tecnico:
  revision: semanal                    # señal al cierre local, orden en la apertura siguiente de cada mercado
  calculo_medias_momentum: divisa_local
  indices_regimen:
    es: "^IBEX"
    us: "^GSPC"
    de: "^GDAXI"
    in: "^NSEI"
    br: "^BVSP"
  regimen_mercado_media: 200
  media_corta: 50
  media_larga: 200
  momentum_meses: 12
  momentum_excluir_meses: 1
  atr_periodo: 14

seleccion:
  pesos:
    fundamental: 0.5
    momentum: 0.5

salidas:
  stop_inicial_atr: 2.0
  stop_dinamico_atr: 3.0
  salir_bajo_media_larga: true
  salir_si_falla_fundamental: true

riesgo:
  por_operacion: 0.01

costes:
  comision_fija_eur: 3.0               # ajústala a tu bróker; algunos cobran más fuera de la UE
  comision_pct: 0.0
  deslizamiento_pct_por_mercado:
    desarrollado: 0.001
    emergente: 0.003                   # mayor por defecto; ajustar por mercado si hay datos mejores
  impuestos_transaccion: config/impuestos_transaccion.yaml   # un % y unas reglas por país

referencias_informe:
  - msci_world_eur
  - msci_emerging_markets_eur

validacion:
  fraccion_diseno: 0.70
  sensibilidad_pct: 0.25
  min_operaciones: 100
  min_operaciones_por_mercado: 15
```
