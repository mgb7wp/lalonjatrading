# Plan de tareas para completar LalonjaTrading

## Contexto

**Qué hay hoy.** El repositorio contiene la versión 1 completa de la estrategia de `ESTRATEGIA.md`. Son unas 11.000 líneas de Python y 92 tests. Incluye:
- el motor: universo, filtro fundamental, señal técnica, stops, costes y divisas;
- un informe en HTML;
- un panel de Streamlit.

**El problema.** Solo se ha probado con datos inventados (el proveedor "sintético"). Nunca ha tocado datos reales, ni un bróker, ni Cloudflare.

**Tus objetivos:**
1. Un backtest fiable con datos reales.
2. Una hoja de órdenes semanal que puedas seguir en eToro: primero en simulado y después con 1.000 € reales.

**Tus condiciones:**
- Datos gratis. Como mucho, pagarías un mes de EODHD.
- Todo automático en tu ordenador Windows.
- Las órdenes se consultan en una página web privada en tu dominio de Cloudflare.

**Diagnóstico.** Revisé todos los ficheros y verifiqué a mano los fallos más graves. Hay tres bloques de trabajo:
- **(a) Fallos que falsean los resultados.** Hay que arreglarlos antes de creerse ningún número.
- **(b) El "modo operativo" no existe.** El comando `senales` no puede usarse para operar:
  - siempre enseña las órdenes de la semana anterior;
  - no dice ni qué vender ni dónde poner el stop;
  - no conoce tu cartera real.
- **(c) Falta la automatización.** El ciclo semanal que describe la documentación (`.github/workflows/semanal.yml`) no está en el repositorio: se perdió al importarlo.

## Cómo usar este plan
- **Cada tarea tiene un código** (A1, B2…) y un responsable:
  - 🤖 lo hace Claude Code;
  - 👤 lo haces tú;
  - 🤝 lo hacéis juntos.
- **Para una tarea 🤖**, abre una sesión de Claude Code y escribe: *"Haz la tarea B2 de PLAN.md"*. Cada una cabe en una sesión: Claude crea una rama, cambia el código, añade tests y te explica el resultado.
- **Dónde ejecutarlas:**
  - Las que necesitan datos reales, eToro o tu ordenador (marcadas 💻) hay que hacerlas **en tu Windows**. Desde la nube, Yahoo Finance devuelve el error 429 (lo he comprobado).
  - Para esas, instala Claude Code en tu PC (app de escritorio o CLI).
  - Las demás pueden hacerse desde la web.
- **El orden importa.** No saltes a la fase F (operar) sin haber cerrado la B (fallos).

---

## Fase A — Preparar el terreno

**A1 🤖 Guardar el plan y crear las reglas para Claude.**
- Guarda este plan como `PLAN.md` en el repositorio.
- Crea un `CLAUDE.md` con las normas del proyecto:
  - en español;
  - `ESTRATEGIA.md` manda sobre el código;
  - ningún parámetro cambia sin una entrada en su registro de cambios;
  - ejecutar `pytest` siempre.
- *Hecho cuando:* ambos ficheros están en `main`.

**A2 🤖 Poner los tests en marcha.**
- Instala las dependencias y ejecuta los 92 tests. Arregla los que fallen.
- Pon versiones máximas a `yfinance`, `streamlit` y `exchange-calendars` en `pyproject.toml`: las versiones nuevas cambian cosas sin avisar. Quita `plotly`, que no se usa.
- Arregla `test_el_enrutador_avisa_de_una_clave_que_falta` (`tests/test_fuentes.py:198`): falla si existe la variable de entorno `EODHD_API_KEY`.
- *Hecho cuando:* `pytest` sale en verde.

**A3 🤖 Separar la configuración de los tests de la tuya.**
- Crea una copia fija de la configuración para los tests (por ejemplo `tests/config_prueba/`).
- Así, cuando cambies capital, mercados o comisiones para eToro, los tests no se rompen.
- *Hecho cuando:* cambiar `config/reglas.yaml` no hace fallar ningún test.

**A4 🤖 Comprobación automática en GitHub (opcional).**
- Un workflow `.github/workflows/tests.yml` que ejecuta `pytest` en cada cambio.
- Si GitHub rechaza subir el fichero por permisos (probablemente la misma causa por la que se perdió el anterior), Claude te da el contenido y lo pegas tú desde la web de GitHub.

## Fase B — Arreglar los fallos que falsean resultados

**B1 🤖 La línea de comandos usa datos inventados por defecto.**
- Qué pasa:
  - `--proveedor` vale `sintetico` por defecto (`src/estrategia/cli.py:344`) y siempre fuerza una sola fuente (`cli.py:49`).
  - Por eso el reparto de fuentes de `reglas.yaml` es inalcanzable.
  - Y `estrategia informe` publicaría datos falsos como si fueran reales.
- Qué hacer:
  - Que por defecto se use `reglas.yaml`.
  - Que la carpeta de caché sea coherente con la que lee el panel.
  - Que un origen mixto como "eodhd+sintetico" también se marque como sintético (`informe.py:55`).
- Añadir tests.

**B2 🤖 Ranking global y límites de cartera entre mercados. Es el fallo más grave.**
- Qué pasa:
  - La revisión semanal decide mercado a mercado: `backtest.py:222-229` → `_revisar` → `ordenes.asignar`, sin contar las órdenes que ya han reservado los otros mercados.
  - Resultado: puede haber hasta 15 compras en una semana con un máximo de 8 posiciones.
  - Los topes por sector y el efectivo disponible se pueden rebasar.
  - Y entra antes quien va primero en la lista es, us, de, in, br, no quien tiene mejor puntuación.
- Qué hacer:
  - En cada corte semanal, reunir las candidatas de todos los mercados.
  - Ordenarlas globalmente, como dicen `ESTRATEGIA.md` y `SUPUESTOS.md:115-118`.
  - Repartir los huecos una sola vez.
  - Recalcular el percentil de momentum dentro de cada mercado, pero con la cohorte completa.
- Test: en una semana con 5 mercados activos nunca se superan `max_posiciones`, `max_por_sector`, `max_por_mercado` ni el efectivo.

**B3 🤖 El deslizamiento se cuenta dos veces por operación.**
- Qué pasa:
  - Los precios de compra y venta ya lo incluyen (`backtest.py:416`, `:473`).
  - `cartera.py:74-94` lo vuelve a restar.
  - La curva de capital está bien, pero el % de operaciones ganadoras y los resultados por mercado y por bloque salen peor de lo real, sobre todo en emergentes.
- Arreglar y añadir test.

**B4 🤖 El calentamiento y las métricas anuales.**
- El calentamiento de unos 13 meses se aplica después de `inicio` aunque exista histórico anterior (`backtest.py:117`, `:266-275`). Por eso el periodo de validación pierde casi la mitad de su tiempo en liquidez. Hay que usar el histórico previo para los indicadores.
- La rentabilidad por año no encadena bien los años (`metricas.py:146`).
- La curva termina antes de la liquidación final.

**B5 🤖 Puntuación fundamental.**
- Los percentiles cuentan los huecos (NaN) en el tamaño de la muestra (`fundamental.py:72-76`).
- El EV se calcula con el precio ajustado por dividendos; debe usar `cierre_bruto` (`backtest.py:352-356`).
- La deuda neta que falta se toma como 0.
- El recurso de percentilar contra el bloque (desarrollado o emergente) cuando un mercado tiene pocas empresas nunca llega a actuar, y el informe no lo dice.

**B6 🤖 Descargas robustas con datos reales.**
- Qué pasa hoy:
  - Una sola fila mala de Yahoo (OHLC incoherente o fecha repetida, `contrato.py:133-154`) tumba toda la descarga.
  - Si fallan los fundamentales, tampoco se guardan los precios.
- Qué hacer:
  - Reparar o apartar las filas malas y avisar de ellas.
  - Guardar cada tipo de dato por separado.
  - Reintentos también en los estados financieros (`yfinance_proveedor.py:259-264`).
  - Pausas entre peticiones.
  - Comprobar que llegan todas las divisas y poner un límite de antigüedad al tipo de cambio.
  - Volumen con huecos (NaN) no debe pasar el filtro de liquidez.
  - Descartar filas sin cierre.
  - No usar la sesión del día en curso.
- Corregir `diagnostico.py`:
  - usa el ejercicio más antiguo en lugar del más reciente (`:145`);
  - no comprueba índices, divisas ni ETF de referencia.

**B7 🤖 yfinance: correcciones y tests.**
- La caja se resta dos veces en la deuda neta (`yfinance_proveedor.py:275` y `:315`).
- Añadir tests para `ajustar_ohlc`, `con_reintentos` y `estimar_fecha_publicacion`.

**B8 🤖 Sectores desconocidos.**
- Un sector que el mapeo no conoce hoy acaba usando el `sector_declarado` (`sectores.py:50-55`). Contradice `SUPUESTOS.md:128`: podría colar un banco.
- Aplicar la regla documentada: se rechaza, y el diagnóstico imprime el YAML que hay que pegar.

**B9 🤖 Proteger el periodo de validación.**
- `informe --periodo todo`, que es la opción por defecto, y el panel enseñan el periodo de validación sin anotar la consulta (`cli.py:391`, `panel/app.py:179`, `:213-225`).
- La fecha de corte entre diseño y validación se desplaza cada semana.
- Qué hacer:
  - Fijar la fecha de corte en la configuración.
  - Que el informe semanal muestre solo el periodo de diseño.
  - Que el panel anote cada consulta.

**B10 🤖 Limpieza de fallos menores.**
- `foto` falla en una carpeta recién clonada (`cli.py:144`).
- Una venta programada se pierde sin dejar rastro (`backtest.py:172-174`).
- Un `except Exception` silencioso al pedir el tipo de cambio (`backtest.py:373`).
- `senales --detalle` filtra por la fecha equivocada (`cli.py:199`).
- Los errores de configuración salen como traza cruda, en vez de un mensaje claro.
- Números sueltos en el código que deberían ir a la configuración (`ordenes.py:127`, `tecnico.py:131/174/195`, `informe.py:112/262`).
- Código muerto (`tecnico.py:27-105`).
- Faltan ñ y tildes en los textos públicos ("Ano").

## Fase C — Primer contacto con datos reales 💻

**C1 🤝 Instalación en tu Windows.**
- Instalar Python 3.11 o superior, Git y Claude Code.
- Clonar el repositorio y ejecutar `pip install -e ".[panel,dev]"`.
- Después: `estrategia diagnostico --anos 8 --detalle`.
- *Hecho cuando:* tienes el informe de diagnóstico en `datos/resultados/`.

**C2 🤖💻 Corregir el universo con el diagnóstico.**
- Tickers probablemente obsoletos: `TATAMOTORS.NS`, `BRFS3.SA`, `JBSS3.SA`, `ELET3.SA`, `CPLE6.SA`.
- Sectores que Yahoo devuelve y el mapeo no conoce.
- Campos de los estados financieros que salen vacíos.
- EV calculable en la mayoría de los valores.
- *Hecho cuando:* al menos el 90 % de los valores son utilizables y no queda ningún sector sin mapear.

**C3 👤 Comprobar qué vende eToro.**
- Claude te prepara la lista de los 140 valores y tú marcas cuáles se pueden comprar en eToro.
- Lo más probable es que eToro no ofrezca India (NSE) ni Brasil (B3).
- Tú decides qué hacer con esos mercados:
  - quitarlos;
  - sustituirlos por sus ADR en EE. UU.;
  - o dejarlos solo en el backtest.
- Después, 🤖 aplica la decisión en `config/universo.yaml` y `reglas.yaml`, con una entrada en el registro de cambios.

**C4 🤝 Verificar los impuestos.**
- Contrastar con la lista oficial de la Agencia Tributaria las listas anuales del ITF español (`config/impuestos_transaccion.yaml`). Hoy son idénticas todos los años y falta 2026.
- Actualizar también la tasa de la SEC.

**C5 👤 Decidir los retrasos de publicación.**
- `reglas.yaml` da a India 105 días y a Brasil 100, menos que los 120 de Europa y EE. UU.
- Eso contradice la idea del documento: los emergentes publican más tarde.
- Tú eliges los valores; 🤖 los aplica y los anota en el registro de cambios.

**C6 🤖💻 Primeros backtests y explicación en lenguaje llano.**
- Primero solo con la parte técnica (`fundamental.activo: false`) sobre todo el histórico. Sirve para validar calendarios, stops, costes y divisas con más de 100 operaciones.
- Después con el filtro fundamental activado. Con yfinance habrá muy pocas operaciones, y eso es esperable.
- *Hecho cuando:* los informes no llevan la marca "sintético" y entiendes qué dicen.

## Fase D — Fundamentales: gratis y, si quieres, un mes de EODHD

**D1 🤖 Preparar EODHD antes de pagar, para no gastar el mes depurando.** Se hace desde la nube, con respuestas grabadas.
- Corregir errores probables del adaptador:
  - toma la divisa de `CurrencySymbol`, que es un símbolo como "$" y no un código (`eodhd_proveedor.py:118-119`);
  - usa `commonStock` como número de acciones, pero es un importe (`:59`);
  - resta la caja dos veces en la deuda neta (`:57`, `:182`);
  - no tiene reintentos ni gestiona el error 429;
  - los errores por valor se tragan en silencio.
- Guardar en disco las respuestas en bruto (`datos/eodhd_crudo/`, fuera de git por la licencia).
- Crear una fuente `archivo` que lea esas respuestas sin clave y complete los años nuevos con yfinance.
- Que el informe lea las capacidades reales de cada fuente, en lugar del número escrito a mano en `fundamentales_anos_disponibles`.

**D2 🤝💻 El mes de pago.**
- Contratar el plan que incluya fundamentales. Compruébalo en su web: el plan básico de precios no los trae.
- Descargar todo en uno o dos días, pasar el diagnóstico y guardar el archivo.
- Opcional: bajar también las empresas deslistadas para reducir el sesgo de supervivencia.

**D3 👤 Cancelar la suscripción.**
- La configuración queda con la fuente `archivo` para los fundamentales.

**Alternativa gratuita parcial:** SEC EDGAR da fundamentales de EE. UU. gratis y con fechas reales de presentación. Solo es una opción si descartas EODHD.

## Fase E — Adaptar la estrategia a eToro y a 1.000 €

**E1 🤖 Fracciones de acción.**
- Con 1.000 € y 8 posiciones caben unos 125-150 € por valor. Redondeando a acciones enteras, casi nada cabe.
- Hay que cambiar `acciones: int` a decimal en `tipos.py:156,179,225` y `riesgo.py:41,74`, y en las órdenes y la cartera.
- Nuevos parámetros:
  - `cartera.fracciones_permitidas`;
  - `cartera.importe_minimo_orden` (el mínimo de eToro).
- Entrada en el registro de cambios como v0.5.

**E2 🤝 Tarifas reales de eToro.**
- Consultar la página oficial de tarifas: comisión por operación y comisión de conversión de divisa.
- Poner esos valores en `costes.*`.
- Añadir `costes.conversion_divisa_pct`, un parámetro nuevo que hay que anotar en el registro de cambios.
- Referencia: la comisión fija actual de 3 € supondría un 2,4 % por operación con posiciones de 125 €.

**E3 🤝 Límites de cartera con 1.000 €.**
- Revisar `max_posiciones`, `max_por_mercado` y `peso_maximo`.
- Solo se comparan en el periodo de diseño, y todo cambio se anota.
- El lote de 100 de Brasil deja de importar con fracciones, si Brasil sigue en el universo.

## Fase F — Modo operativo: la hoja de órdenes semanal

**F1 🤖 Cartera persistente.**
- Ficheros `datos/cartera/simulada.yaml` y `datos/cartera/real.yaml`. Cada uno guarda las posiciones (valor, fecha, precio, acciones, stop inicial, ATR de entrada, máximo cierre) y el efectivo.
- Comandos:
  - `estrategia cartera ver`
  - `cartera compra TICKER --acciones --precio --fecha`
  - `cartera venta ...`
- Reutilizar la estructura `Posicion` de `tipos.py`.
- Siempre puedes pedirle a Claude: *"he comprado 0,4 acciones de X a 120 €, regístralo"*.

**F2 🤖 Decidir la semana actual, no la anterior.**
- El calendario se construye solo hasta el último precio disponible (`backtest.py:107`, `:130`). Por eso la última revisión, que se ejecutaría el lunes siguiente, se descarta.
- Solución: extender el calendario con las sesiones futuras, que `exchange_calendars` ya conoce.
- Test: con datos hasta un viernes, salen las órdenes para el lunes.

**F3 🤖 Nuevo comando `estrategia semana` con tu cartera real.**
- Usa las mismas funciones del motor que el backtest (`_revisar`, `ordenes.asignar`, `salidas`, `tecnico.senal`), sin un camino paralelo.
- Produce, en Markdown y HTML:
  1. **VENDER:** las salidas semanales (bajo la media larga o ya no pasa el filtro fundamental).
  2. **MOVER STOP:** el nuevo nivel para cada posición.
  3. **COMPRAR:** para cada valor, el importe en €, las acciones aproximadas, el precio de referencia, el stop inicial, su puesto en el ranking y el motivo.
  4. **AVISOS:** mercados con el régimen apagado o datos que faltan.
- Test: la hoja coincide con lo que haría el backtest partiendo de la misma cartera.

**F4 🤖 Stops diarios.**
- El trailing stop de eToro no sigue la regla "máximo cierre − 3 ATR", así que el nivel se recalcula cada día.
- Nuevo comando `estrategia stops`, que ejecuta cada mañana laborable y lista solo los stops que han subido, para que los actualices en eToro.

**F5 🤖 Diario de ejecución.**
- Cada hoja semanal se archiva.
- Se compara lo que dijo el sistema con lo que ejecutaste: precio real frente a la apertura y deslizamiento real frente al modelado.

**F6 👤 8-12 semanas en simulado.**
- En la cartera virtual de eToro, sigues la hoja cada semana y registras lo que ejecutas.
- Para pasar a real: ninguna discrepancia sin explicar, costes reales iguales o menores que los modelados, y que entiendas cada orden.

**F7 👤 Pasar a real con 1.000 €.**

## Fase G — Automatización en tu Windows y web privada 💻

**G1 🤖 `foto` útil.**
- Guardar solo fundamentales, tipos de cambio y sectores. Hoy guarda además 8 años de precios cada semana y engorda git.
- Crear las carpetas si faltan.
- Reutilizar la descarga de `datos` en vez de bajar todo otra vez.
- Marcar las fotos incompletas.

**G2 🤖 Script semanal y tareas programadas de Windows.**
- Un script `despliegue/windows/semanal.ps1` que hace, en orden:
  1. activa el entorno;
  2. `datos`;
  3. `foto`;
  4. `semana`;
  5. `informe`;
  6. commit y push de `datos/fotos`;
  7. despliegue de la web.
- Guarda un log y te avisa si algo falla.
- Programador de tareas: el **sábado por la mañana**, con los cierres del viernes ya dentro. Así tienes el fin de semana para revisar las órdenes antes de la apertura del lunes.
- Un segundo script diario para `stops`.

**G3 🤝 Web privada.**
- Cloudflare Pages: crear el proyecto con la rama de producción `main` (hoy `DESPLIEGUE.md:56` cita una rama que no existe).
- Instalar Node.js y wrangler en Windows y guardar el token en una variable de entorno.
- Cloudflare Access, con acceso solo para tu email.
- Una página índice con la hoja de la semana, el informe y el archivo de semanas anteriores.
- *Hecho cuando:* lo abres desde el móvil con el código que te llega por email, y nadie más puede.

**G4 🤖 Panel solo en local.**
- Que escuche solo en `127.0.0.1` y oculte las trazas de error.
- Arreglar la caché: hoy no detecta los cambios de configuración (`panel/app.py:48-49`).
- Añadir una pestaña "Mi cartera".
- No exponerlo por el túnel: no forma parte de tus objetivos.

**G5 🤖 Leer las fotos semanales (cuando haya meses acumulados).**
- Convertirlas en fundamentales `capturado`. Hoy nadie las lee.

**G6 🤖 Aviso por email o Telegram cuando la hoja esté lista (opcional).**
- `ESTRATEGIA.md` lo deja fuera de la versión 1, así que se anota como cambio.

## Fase H — Calidad del informe y cierre de versión

**H1 🤖 Informe completo.**
- Por mercado y por bloque: rentabilidad anualizada, drawdown y Sharpe.
- Las referencias MSCI con cifras, no solo como líneas, y también en el Markdown.
- La sensibilidad dentro del HTML.
- `sesiones_de_retraso`.
- Un título con fecha en cada informe.

**H2 🤖 Sensibilidad.**
- Añadir los parámetros que no se mueven (`validacion.py:38-55`).
- Informar de las variantes inválidas en vez de saltarlas en silencio.
- Mover `crecimiento_ventas_3a` sumando y restando, porque vale 0 y un ±25 % no lo cambia.
- Dar un veredicto de "robusta / no robusta".

**H3 🤝 Cerrar la versión.**
- Congelar los parámetros.
- Ejecutar el periodo de validación **una sola vez**.
- Rellenar las fechas y los resultados del registro de cambios de `ESTRATEGIA.md`.

**H4 🤖 Documentación al día.**
- README, DESPLIEGUE y FUENTES: Windows, eToro, comandos correctos, rama `main`, estado real.
- Versión 0.5 en `pyproject.toml`.

**Mantenimiento recurrente 👤:**
- Cada enero: la lista del ITF de la Agencia Tributaria y la tasa de la SEC.
- Cada trimestre: los tickers que siguen en eToro.
- Cada año: revisar `universo.yaml`.

## Fuera de alcance (versión 2 del documento)
Quedan fuera:
- entrada por RSI;
- salida por tiempo;
- bancos y aseguradoras;
- fiscalidad de plusvalías (FIFO y regla de los dos meses; para la declaración usarás el informe anual de eToro);
- cobertura de divisa;
- panel público por túnel.

## Verificación final
- `pytest` en verde, con tests nuevos para el ranking global, el deslizamiento, las fracciones, la semana actual, la cartera persistente y la hoja coherente con el backtest.
- Diagnóstico real: al menos el 90 % de valores utilizables, ningún sector sin mapear y EV calculable en la mayoría.
- Backtest solo técnico con 100 operaciones o más, sin la marca de sintético.
- Un sábado, la tarea programada genera sola la hoja para el lunes y la web privada la muestra. Se comprueba dos semanas seguidas.
- Entre 8 y 12 semanas de simulado registradas en el diario antes de meter dinero real.

## Estado de las tareas

Marca aquí cada tarea al terminarla (Claude Code lo hace al cerrar cada sesión).

- [x] A1 — `PLAN.md` y `CLAUDE.md` creados (rama `claude/gallant-lamport-saaeo8`; pendiente de fusionar en `main`).
- [x] A2 — Tests en verde (92/92). Versiones máximas en `yfinance` (<1.8), `streamlit` (<1.65) y `exchange-calendars` (<4.14); `plotly` quitado; el test de la clave de EODHD ya no depende de tu ordenador (rama `claude/tarea-a2-plan-3vkpwa`; pendiente de fusionar en `main`).
