# Supuestos

`ESTRATEGIA.md` es la fuente de verdad, pero no puede decidirlo todo: hay puntos
donde la letra admite dos lecturas y otros que no llega a tratar. Este documento
recoge cada decision que se ha tomado al implementar, con su motivo. Estan aqui,
y no enterradas en el codigo, porque cambiar cualquiera de ellas cambia los
resultados, y quien lea un backtest tiene derecho a saber cual era la regla.

Las decisiones que anaden o modifican parametros estan ademas en el registro de
cambios de `ESTRATEGIA.md`, como pide el propio documento.

## Ciclo semanal

**Corte semanal global en vez de por mercado.** El documento dice que las
senales se calculan con el cierre del ultimo dia habil de la semana y que las
ordenes se ejecutan en la apertura siguiente "en el calendario de cada mercado".
Se ha implementado con un **unico instante de corte por semana** —el ultimo
cierre de bolsa de esa semana, mirando los cinco mercados— del que cuelga todo:
cada mercado aporta su ultima sesion cerrada antes del corte y ejecuta en su
primera apertura posterior.

Para los cinco mercados actuales, un corte por mercado da exactamente el mismo
resultado: se comprobo sesion a sesion sobre los calendarios reales de 2024 y no
hay una sola semana en que difieran. La razon de hacerlo asi es que la propiedad
quede garantizada por construccion y no por suerte del calendario: como la
comparacion final entre candidatas es global, todas tienen que estar puntuadas
con informacion disponible en un mismo instante.

**Retraso entre decidir y ejecutar.** Normalmente es una sesion. Si un mercado
estuvo cerrado al final de la semana, su senal llega mas vieja; eso se registra
en `sesiones_de_retraso` y el informe lo reporta, en lugar de disimularlo
decidiendo con datos de otro mercado que aun no existian.

**Orden dentro del dia.** Stops primero (con el nivel de ayer), luego ventas
programadas, luego compras, luego el stop intradia de lo comprado hoy, luego el
trinquete con el cierre, y por ultimo la revision semanal. Las salidas van antes
que las entradas para que un hueco liberado se pueda usar.

**Un hueco liberado no se rellena hasta el siguiente corte semanal.** Mas simple
y mas conservador que reabrir la lista de candidatas a mitad de semana.

## Anticipacion

**El stop de la sesion D se calcula con datos hasta D-1.** El documento dice que
el stop dinamico "se recalcula a diario". Si se recalculase antes de mirar el
minimo de hoy, se estaria usando el cierre de hoy para decidir si hoy se toco el
stop. Es un error de una linea que mejora todos los backtests en silencio, asi
que el trinquete se actualiza al final del dia.

**El ATR del stop inicial se congela en la entrada**; el del dinamico es el
corriente. El documento no lo aclara y cambia los resultados.

**El trinquete usa cierres, nunca maximos intradia.** Usar maximos apretaria los
stops y mejoraria el resultado sin que la estrategia lo diga.

**El tipo de cambio para decidir es el de D-1; el de D solo se usa para
valorar.** Los tipos de referencia del BCE se publican por la tarde, asi que
decidir a la hora del cierre indio con el cambio de hoy seria usar un dato que
todavia no existe.

**El filtro fundamental se reevalua en cada revision semanal**, no solo en la
semana de publicacion de resultados. Es mas frecuente y mas estricto que la
letra del documento, y da el mismo resultado salvo en esa semana exacta.

## Percentiles y puntuacion

**La cohorte del percentil es el universo elegible del mercado**, no solo las
empresas que aprueban los minimos (`fundamental.cohorte_percentiles`). Con la
otra lectura, un mercado con dos aprobadas produce un 0 y un 100, y esa segunda
empresa —mediocre en terminos absolutos— competiria de tu a tu con la mejor de
un mercado bien cribado. La puntuacion se emite solo para las aprobadas.

**Posiciones de trazado de Hazen**, `(rango - 0,5) / n`, en lugar de
`(rango - 1) / (n - 1)`. Con Hazen, una cohorte de uno da 50 y una de dos da 25
y 75: el percentil deja de afirmar una certeza que la muestra no sostiene.

**Por debajo de `min_empresas_percentil` se percentila contra el bloque**
(desarrollado o emergente) y el informe lo marca. Excluir los mercados pequenos
crearia un sesgo por tamano de mercado correlacionado justo con la distincion
que al documento le importa.

**Sin EV/EBIT utilizable, la valoracion puntua en el peor percentil, no en uno
neutro.** No saber si una empresa esta barata no es lo mismo que estar barata.

**Empates: desempate por ticker ascendente.** Sin un desempate explicito, dos
ejecuciones del mismo backtest pueden dar carteras distintas segun como ordene
pandas, y el resultado deja de ser reproducible.

## Trampas de signo

Tres ratios se dan la vuelta con denominador o numerador negativo, y en los tres
casos una comprobacion ingenua deja pasar a la empresa que habria que descartar:

- **EBIT <= 0** -> no hay EV/EBIT; la valoracion va al peor percentil.
- **EBITDA <= 0** -> no hay deuda/EBITDA; la empresa no pasa el filtro.
- **Patrimonio neto <= 0** -> el ROE no es valido; la empresa no pasa.

**La caja neta si pasa.** Deuda neta negativa da un ratio negativo que cumple el
maximo, y eso es correcto: es una empresa sin deuda. Queda escrito para que
nadie lo "arregle".

**Un ratio que no se puede calcular no pasa.** Sin el dato no hay forma de
afirmar que se cumple el minimo.

**Antiguedad maxima del dato fundamental** (`antiguedad_maxima_dias`, 450 dias):
pasado ese plazo sin publicacion nueva, la empresa deja de pasar el filtro en
lugar de arrastrar cifras de hace tres anos como si fueran de hoy.

## Cartera y tamano

**Una candidata que no cabe se salta y se sigue bajando por la lista.** El
documento dice "se compran por ese orden mientras queden huecos", que admite las
dos lecturas; esta es la que llena la cartera.

**Los huecos se reservan al decidir, no al ejecutar.** Comprobar los limites en
el momento del fill haria que el mercado que abre antes (India, 04:00 UTC) se
quedara siempre con los huecos antes que Europa o EE. UU.: un sesgo de huso
horario, no una decision de estrategia.

**Orden de comprobacion**, que es lo que hace el resultado reproducible: ya en
cartera, regimen, tope de posiciones, tope de sector, tope de mercado, tamano
cero, efectivo. Si dos motivos pudieran aplicarse, siempre gana el primero.

**Lote minimo por mercado** (`lote_por_mercado`): el libro principal de B3 va en
lotes de 100, lo que con 10.000 EUR deja fuera bastantes valores brasilenos. Es
un hallazgo honesto, no algo que convenga esconder redondeando a una accion.

**Un sector que el mapeo no reconoce rechaza el valor.** Fallar hacia el lado
prudente importa: un sector sin traducir podria colar un banco en una cartera
que por diseno no quiere bancos.

**La elegibilidad del universo se evalua a fecha.** Calcularla una sola vez con
todo el historico seria anticipacion y supervivencia a la vez.

**El volumen negociado usa precio BRUTO x volumen bruto.** Los proveedores no
ajustan el volumen por dividendos, asi que combinarlo con el precio ajustado
subestima la liquidez de los anos antiguos, que es donde este filtro decide. Se
convierte con el cambio del dia de la decision, y no sesion a sesion: la
diferencia es menor que el ruido del propio umbral y ahorra sesenta consultas de
divisa por valor y semana.

**"Los ultimos tres meses" son 63 sesiones del calendario de ese mercado**
(`sesiones_volumen`), no aritmetica de meses naturales, que cuenta distinto
segun los festivos de cada pais.

## Costes e impuestos

**El ITF espanol solo existe desde el 16 de enero de 2021** (`vigente_desde`).
Aplicarlo a un backtest que empieza antes sobreestima los costes de los primeros
anos.

**Si no hay lista anual del ano de la operacion se usa la mas cercana hacia
atras**, y el informe avisa de la extrapolacion.

**No hay filtro por coste.** Con 10.000 EUR y 3 EUR fijos por operacion, las
posiciones pequenas pagan una fraccion alta en comisiones. Se mide y se reporta
(`coste_pct_posicion`), pero no se rechaza ninguna candidata por eso: seria
cambiar la estrategia, y el documento pide medir antes de tocar.

## Metricas

**El Sharpe se calcula sobre rentabilidades semanales** por defecto
(`metricas.periodicidad_sharpe`). Con cinco calendarios distintos, parte de la
cartera esta congelada cualquier dia en que su mercado tiene fiesta y los demas
no; esos ceros artificiales hunden la volatilidad diaria medida e inflan el
Sharpe sin que la estrategia haya hecho nada mejor.

**La tasa libre de riesgo es 0 por defecto** (`metricas.tasa_libre_riesgo_anual`).
El documento no la fija.

**El factor de anualizacion se mide sobre las sesiones reales del periodo**, no
con un 252 incrustado.

**Las referencias son ETF de acumulacion cotizados en euros** (EUNL.DE e
IS3N.DE): los dividendos van dentro del precio, como pide el documento, y no hay
una conversion de divisa mas donde equivocarse. Su fecha de lanzamiento recorta
la comparacion hacia atras.

**El informe publica la exposicion media.** Las referencias estan invertidas al
100% siempre y la estrategia no; comparar las curvas sin decirlo no seria una
comparacion justa.

**Las posiciones abiertas al final se cierran al ultimo cierre** y se marcan
`abierta_al_final`, para que la curva este completa.

## Datos

**Se ajustan los cuatro precios, no solo el cierre.** Calcular el ATR con
maximos y minimos en bruto y las medias con el cierre ajustado convierte cada
dividendo en un hueco inventado y deja el ATR sin sentido.

**El almacen fija cuando se conocio un dato, no que version se conocia.** Los
fundamentales de un proveedor gratuito vienen reexpresados a hoy, y las
reexpresiones no son neutras. Cada fila lleva `origen_pit` (`capturado` o
`reconstruido`) y el informe publica el porcentaje reconstruido, que en un
backtest de la version 1 es practicamente el 100%.

**Cierre forzoso tras `sesiones_sin_datos_cierre_forzoso` sesiones sin precio.**
Arrastrar el ultimo cierre indefinidamente falsea el resultado.

**El regimen se apaga si falta el indice o esta desfasado.** Equivocarse hacia
el lado prudente cuesta operaciones no hechas; hacia el otro cuesta dinero.

## Inconsistencias del documento

**Francia.** La prosa menciona el sufijo `.PA` para Francia, pero
`universo.mercados` no incluye ningun mercado `fr`. Manda la configuracion: la
version 1 son cinco mercados, y ni `universo.yaml` ni la tabla de impuestos
incluyen Francia.

**Indices de regimen.** La prosa habla de "un indice de emergentes para esos
mercados" y la configuracion mapea un indice por pais (`^NSEI`, `^BVSP`). Manda
la configuracion. Varios mercados pueden apuntar al mismo ticker si algun dia se
quiere la version por bloque.

## Limites conocidos que no son supuestos, sino hechos

- El proveedor gratuito da unos cuatro ejercicios de fundamentales. Con eso, el
  crecimiento de ventas a tres anos tiene practicamente una sola observacion por
  empresa: **ese filtro es casi estatico** durante el backtest.
- Con un historico fundamental tan corto, **los minimos de `validacion`
  (100 operaciones en total, 15 por mercado) probablemente no se alcancen**. El
  informe lo dice en vez de disimularlo. Para validar el motor sobre un
  historico largo existe `fundamental.activo: false`.
- **Los dividendos se reinvierten brutos.** Un inversor en euros paga retencion
  en origen en EE. UU., India y Brasil. No se modela; el informe lo advierte.
- **No hay empresas deslistadas.** El universo son las que cotizan hoy, asi que
  hay sesgo de supervivencia, mas fuerte en emergentes.
