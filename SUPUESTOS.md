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

**Los huecos no cuentan en el tamano de la muestra del percentil** (v0.4.4). Una
empresa sin el dato no esta en la foto contra la que se compara: si contara,
todas las demas bajarian de percentil sin motivo. Sigue contando para decidir si
el mercado tiene gente suficiente (`min_empresas_percentil`), que mide empresas
elegibles, no datos.

**El EV se calcula con el precio sin ajustar por dividendos** (`cierre_bruto`,
v0.4.4). El ajustado rebaja los precios pasados en lo que se repartio despues, y
con el la capitalizacion de hace anos saldria menor que la real. Limite conocido:
el precio sin ajustar de los proveedores si viene ajustado por splits, y las
acciones en circulacion son las del ultimo balance; si hubo un split entre ese
balance y la fecha de decision, el EV sale descuadrado hasta el balance
siguiente.

**Deuda neta de yfinance: la caja se resta una sola vez** (v0.4.6). Yahoo da a
veces la deuda total y a veces solo la neta, que ya lleva la caja restada. Con la
deuda total se resta la caja; con solo la neta, se toma tal cual. Se decide
ejercicio a ejercicio. Si hay deuda total pero no caja, se toma la deuda total:
sobrestima la deuda, que es el lado prudente.

**Sin deuda neta no hay EV** (v0.4.4). Tomarla como cero haria parecer barata a
una empresa endeudada solo porque al proveedor le falta el dato. La empresa ya
no pasaba el filtro (deuda/EBITDA sin calcular), pero su EV entraba en la
cohorte y movia la valoracion de las demas.

**El informe cuenta las compras puntuadas fuera de su mercado** (v0.4.4): cuantas
se percentilaron contra el bloque y cuantas con una cohorte insuficiente, por
mercado. Con la cohorte de todos los mercados a la vez (v0.4.1), el recurso al
bloque ya actua de verdad.

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

**El reparto es uno solo por semana, para todos los mercados** (v0.4.1). Cada
mercado calcula sus salidas, sus senales y sus ratios en su propia sesion de
decision, con sus datos de ese dia. Al terminar el dia en que decide el ultimo
mercado de la semana, las candidatas de todos se ordenan en una lista global y
los huecos se reparten una vez, contra un unico estado reservado de la cartera
(posiciones, sector, mercado y efectivo). El patrimonio que sirve para
dimensionar es el de ese momento. Repartir mercado a mercado dejaba que cada uno
viera la cartera como si los demas no hubieran reservado nada.

**Las posiciones ya en cartera cuentan en la cohorte del percentil de
momentum**, igual que ya contaban en la de los ratios fundamentales, y luego se
quitan de la lista antes de repartir. Si no contaran, la nota de una candidata
dependeria de lo que se tiene en cartera: comprar la mejor de un mercado subiria
el percentil de las demas la semana siguiente sin que nada hubiera cambiado en
el mercado. Al quitarlas antes de repartir, el puesto del ranking que se anota
es el de las comprables de verdad y el registro de rechazos no se llena cada
semana de `ya_en_cartera`.

**Orden de comprobacion**, que es lo que hace el resultado reproducible: ya en
cartera, regimen, tope de posiciones, tope de sector, tope de mercado, tamano
cero, efectivo. Si dos motivos pudieran aplicarse, siempre gana el primero.

**Lote minimo por mercado** (`lote_por_mercado`): el libro principal de B3 va en
lotes de 100, lo que con 10.000 EUR deja fuera bastantes valores brasilenos. Es
un hallazgo honesto, no algo que convenga esconder redondeando a una accion.

**Un sector que el mapeo no reconoce rechaza el valor.** Fallar hacia el lado
prudente importa: un sector sin traducir podria colar un banco en una cartera
que por diseno no quiere bancos. Aunque el valor tenga `sector_declarado` en
universo.yaml (v0.4.7): ese respaldo solo se usa cuando el proveedor NO devuelve
sector. Si devuelve uno que el mapeo no conoce, taparlo con lo que alguien
escribio a mano dejaria sin revisar justo la traduccion que falta. El
diagnostico imprime la linea de YAML que hay que pegar en `sectores`: con la
categoria que declaran los valores afectados si todos coinciden, y comentada si
no, para decidir a mano.

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

**El deslizamiento va en el precio y se informa como coste, pero se resta una
sola vez** (v0.4.2). Los precios de entrada y salida de cada operacion son los
realmente pagados y cobrados, con el deslizamiento dentro. El resultado de la
operacion resta solo comision e impuesto, y por construccion es lo que se movio
en caja. `costes_base` sigue siendo el coste total, deslizamiento incluido
(aparte en `deslizamiento_base`), porque es lo que cuesta operar y es lo que
mide `coste_pct_posicion`.

## Periodo de validacion

**La fecha de corte es fija** (`validacion.fecha_corte`, v0.4.8). El documento
define el diseno como la fraccion inicial `fraccion_diseno` del historico. Con
la fraccion sola, el corte avanzaba cada semana al llegar datos nuevos, y lo que
ayer era validacion pasaba a ser diseno sin que nadie lo decidiera. La fecha se
eligio para que, con los ocho anos que se descargan, el diseno sea ese 70 %; a
partir de ahi los datos nuevos solo alargan la validacion. Moverla es un cambio
de regla y va al registro.

**Mirar "todo" es mirar la validacion** (v0.4.8), y anota la consulta igual que
pedir la validacion sola. El informe que se genera y se publica cada semana
muestra por defecto solo el periodo de diseno.

**El panel pide confirmacion y anota una vez por sesion** (v0.4.8). Streamlit
reejecuta el script con cada clic; anotar cada ejecucion inflaria el contador y
no anotar nada dejaba mirar sin rastro. La vista de senales ensena solo la
ultima revision, sin historial de ordenes.

**Operar no gasta la validacion.** Para decidir las ordenes de la semana hacen
falta los datos de hoy, que caen en el periodo de validacion. Usarlos para
decidir no es consultarlos: lo que gasta la validacion es mirar como le fue al
sistema (curva, resultados, historial de operaciones), y eso solo se ensena con
la consulta anotada.

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
`abierta_al_final`, para que la curva este completa. El ultimo punto de la curva
es el de DESPUES de esa liquidacion, con los costes de salida pagados (v0.4.3):
asi el capital final del resumen es la suma del inicial y de los resultados de
todas las operaciones.

**La rentabilidad de cada ano se mide desde el ultimo valor del ano anterior**
(v0.4.3), y el primer ano desde el valor inicial. Medirla desde la primera
sesion del ano dejaba fuera lo que pasaba entre el cierre de diciembre y la
primera sesion de enero, y los anos encadenados no daban la rentabilidad total.

**El calentamiento se cuenta desde el principio de los datos, no desde el del
backtest** (v0.4.3). Las medias, el ATR, el regimen y el momentum necesitan
unos trece meses de historia. Si el backtest empieza despues de tenerlos (el
periodo de validacion, o cualquier `inicio` posterior al de los datos), se decide
desde la primera semana con el historico anterior. Solo cuando no hay historia
previa, como en el arranque del periodo de diseno, la cartera espera en liquidez;
ese tramo sigue dentro de la curva y rebaja la rentabilidad anualizada, y la
exposicion media lo deja ver.

## Datos

**Se ajustan los cuatro precios, no solo el cierre.** Calcular el ATR con
maximos y minimos en bruto y las medias con el cierre ajustado convierte cada
dividendo en un hueco inventado y deja el ATR sin sentido.

**El almacen fija cuando se conocio un dato, no que version se conocia.** Los
fundamentales de un proveedor gratuito vienen reexpresados a hoy, y las
reexpresiones no son neutras. Cada fila lleva `origen_pit` (`capturado` o
`reconstruido`) y el informe publica el porcentaje reconstruido, que en un
backtest de la version 1 es practicamente el 100%.

**Una venta programada sin precio ese dia se aplaza a la siguiente sesion** del
mercado (v0.4.9), y queda anotada como `venta_aplazada`. La decision de vender
sigue en pie; antes se perdia sin rastro y la posicion seguia abierta hasta que
saltara el stop.

**Cierre forzoso tras `sesiones_sin_datos_cierre_forzoso` sesiones sin precio.**
Arrastrar el ultimo cierre indefinidamente falsea el resultado.

**El regimen se apaga si falta el indice o esta desfasado.** Equivocarse hacia
el lado prudente cuesta operaciones no hechas; hacia el otro cuesta dinero.

**Las filas malas de precios se reparan o se apartan, no tumban la descarga**
(v0.4.5). Se apartan las que no se pueden arreglar sin inventar: sin cierre, con
precios negativos o cero, y las de la sesion en curso. De una fecha repetida se
queda la ultima fila que llego. Las que tienen cierre pero un OHLC incoherente se
reparan: el maximo pasa a ser el mayor de los cuatro precios y el minimo el
menor; si falta la apertura, el maximo o el minimo, se rellenan con el cierre.
Todo se cuenta al descargar. La reparacion es prudente para los stops: con el
minimo recalculado, un stop que el dato roto habria saltado sigue saltando.

**La sesion del dia en curso no se usa** (v0.4.5). Mientras el mercado esta
abierto, el "cierre" de hoy es el ultimo precio del momento. Se apartan los
precios y cambios con fecha de hoy o posterior; el ultimo dato es el de ayer.

**Un volumen que falta cuenta como una sesion sin negociacion** (v0.4.5). En la
media de liquidez, un hueco suma cero en lugar de ignorarse. Antes un solo hueco
volvia el promedio NaN, y como `NaN < minimo` es falso, el valor pasaba el
filtro sin que se supiera cuanto se negociaba.

**Faltar una divisa o tener el cambio congelado es un error al descargar**
(`datos.fx_antiguedad_maxima_dias`, v0.4.5). El ultimo cambio de cada divisa no
puede tener mas de esos dias; un tramo del historico sin cotizacion mas largo se
avisa, pero no para la descarga: el backtest arrastra el ultimo cambio conocido.

**Cada tipo de dato se descarga y se guarda por separado** (v0.4.5). Si fallan
los fundamentales, las divisas o los sectores, los precios buenos se guardan y
del tipo que fallo se conserva lo de la descarga anterior, si lo habia. El
manifiesto lo anota (`incompletos`), el informe lo avisa y el comando termina con
codigo 1 para que la tarea programada se entere. Sin precios no se toca nada.

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
