# Plan de tareas de La Lonja

## Contexto

**Qué es.** La Lonja (`lalonja-trading.com`) es la plataforma de análisis de inversiones del proyecto:
- el **motor** de la estrategia está en `core/estrategia/`, en español;
- la **plataforma** (API, base de datos, tareas diarias, web) está en `backend/`, `workers/`, `ml/` y `frontend/`, en inglés;
- el **servidor** es un Hetzner, detrás de Cloudflare Tunnel.

**Para qué, de momento.** Para uso propio:
- analizar valores con datos reales;
- operar en eToro, con 1.000 € de capital inicial, primero en simulado.

Lo comercial (cobrar a suscriptores) queda aparcado hasta el final.

**De dónde viene este plan.** El 23/09/2026 la plataforma pasó a `main` e incorporó los arreglos del motor B1–B10. Antes vivía en ramas separadas. Las fases del producto están en [`docs/ROADMAP.md`](docs/ROADMAP.md), y las decisiones de diseño (D-1 a D-14), en [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md).

## Cómo usar este plan

- **Cada tarea tiene un código** (S1, M2…) y un responsable:
  - 🤖 lo hace Claude Code;
  - 👤 lo haces tú;
  - 🤝 lo hacéis juntos.
- **Para una tarea 🤖**, abre una sesión y escribe: *"Haz la tarea M1 de PLAN.md"*. Cada una cabe en una sesión y termina en una pull request con sus tests. El CI tiene que salir en verde (ruff, pytest con Postgres y build del frontend).
- **Las tareas 🖥️ necesitan el servidor.** Claude no tiene acceso por SSH: te da los comandos y tú los pegas.
- **El orden importa:** primero, que el servicio no falle en silencio y que los números sean correctos; después, usarla para operar.

---

## Fase 1 — Unificar (en curso)

**I1 🤖 Integración.** Terminada en la rama `claude/gallant-lamport-saaeo8`; falta fusionarla.
- La plataforma incorpora B1–B10.
- Se arreglan dos choques: los sectores del backtest desde la base de datos, y la sesión del día en la descarga programada.
- 648 tests en verde.

**I2 🤖 `main` pasa a ser la plataforma.** Hay que fusionar la pull request de I1 y cerrar la PR #1, cuyo contenido llega por I1.

**I3 👤🖥️ El servidor pasa a `main`.**
- Es una vez. Los comandos están en [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), sección 1: `git checkout main`, `desplegar.sh` y el recálculo de scores y señales.
- *Hecho cuando:*
  - `/api/v1/rankings` da la fecha de hoy;
  - la pestaña "Análisis IA" aparece en la ficha de un valor.

**I4 🤖 Ramas viejas.**
- Borrar las ramas que ya no se usan:
  - `claude/saas-investment-analysis-ai-rix1km`;
  - `claude/affectionate-goodall-5zkcyd`;
  - `claude/tarea-a2-plan-3vkpwa`;
  - `claude/tarea-b1-plan-upatwu`.
- `claude/blissful-faraday-mi75sr` se borra después de M3 y M4, que aprovechan dos de sus commits.
- Solo con tu permiso.

## Fase 2 — Que no falle en silencio

**S1 🤖 Vigilar scores y señales.**
- Hoy `/health/data` vigila la frescura de precios, fundamentales y divisas, pero no la de scores y señales.
- Eso es justo lo que falló el 22/09: los rankings enseñaban scores viejos y nada avisó.
- Hay que añadirlo, y conectar un aviso externo gratuito (UptimeRobot o similar) que te escriba si `/health/data` no está en verde.

**S2 🤝🖥️ Copias de seguridad fuera del servidor.**
- Hoy viven en el mismo disco que la base de datos (`despliegue/copia_seguridad.sh`).
- Subirlas a Cloudflare R2, que tiene 10 GB gratis. Tú creas el bucket y el token; Claude, el script.

**S3 🤝 Cerrar la web con Cloudflare Access.**
- Solo tu email entra, incluido `/docs`.
- Es de uso propio, los datos de yfinance no se pueden redistribuir, y así nadie gasta tu cuota de IA.
- Se hace en el panel de Cloudflare (Zero Trust → Access); Claude te guía.

**S4 🤖 Despliegue automático desde el CI (opcional).**
- Hoy es `git pull` por SSH.

## Fase 3 — Que los números sean correctos

**M1 🤖 Fuga de futuro en los scores de producción.** Es lo más urgente de esta fase. Tres problemas en `workers/pipeline/scores.py`:
- `_fundamentales` no filtra por fecha de publicación, y `historico.iloc[-1]` puede ser un ejercicio que aún no se había publicado ese día. Un recálculo hacia atrás usa datos del futuro.
- La valoración usa `close`, que está ajustado por dividendos, en lugar de `close_raw`. Además, el EV suma la deuda bruta en lugar de la neta.
- `_indicadores` y `_precios` no tienen límite de antigüedad, así que un valor que dejó de cotizar sigue puntuando.

A la vez, en `core/estrategia/scoring.py` y `grupos.py`:
- el mínimo de cohorte debe contar los valores presentes, no las filas;
- la cohorte `__refundida__` no debe etiquetarse como `BLOQUE`.

Tests de anticipación como los de `tests/test_anti_sesgo.py`.

**M2 🤖 Señales** (`workers/pipeline/senales.py`).
- El score de "hace 30 días" se busca en un día exacto, y en fines de semana y festivos no lo encuentra. El limitador de caída se salta en silencio.
- El umbral `momentum_minimo` (tanto por uno) se compara con un sub-score de 0 a 100, así que nunca actúa.

**M3 🤖 Órdenes pendientes.**
- Las órdenes que aún no se han ejecutado deben ocupar hueco en el reparto semanal del backtest.
- Se trae el commit `c3018c8` de la rama `blissful-faraday`: `asignar(pendientes=)` y `Orden.reserva_base`.

**M4 🤖 Saltos de precio sin ajustar.**
- Traer el detector `contrato.saltos_sospechosos` del commit `a0afefb`.
- Arreglar los tres casos conocidos:
  - `TMPV.NS`: la escisión de Tata Motors;
  - `UGPA3.SA`: su histórico antes de 2021-06-28;
  - `EMBR3.SA`, que ahora es `EMBJ3.SA` (también en `config/cvm_empresas.yaml`).

**M5 🤖 Fuente de precios de respaldo.**
- Hoy los cinco mercados dependen solo de yfinance.
- Candidatas gratuitas: Tiingo y Twelve Data. EODHD es de pago.

**M6 🤝 Fundamentales de España, Alemania e India.**
- Hoy son 4 ejercicios reexpresados de yfinance.
- Opción: pagar **un mes** de EODHD, descargar todo el histórico y guardarlo. Antes hay que corregir el adaptador, que nunca se ha ejecutado con clave real:
  - toma la divisa de `CurrencySymbol`;
  - usa `commonStock` como número de acciones;
  - resta la caja dos veces en la deuda neta.

**M7 🤝 Verificar la configuración que dice "sin verificar".**
- `config/universo.yaml`: marcar qué valores vende eToro. India y Brasil probablemente no están, y hay que decidir qué hacer con ellos.
- Las listas del ITF español, contra la Agencia Tributaria.
- La tasa de la SEC.
- Los retrasos de publicación de India (105 días) y Brasil (100), que hoy son menores que los 120 de Europa y EE. UU.

## Fase 4 — Operar con ella (eToro, 1.000 €)

**O1 🤖 Cartera.**
- Poder corregir una transacción y renombrar la cartera. Hoy la API lo permite, pero la web no.
- Permitir una comisión de custodia sin valor asociado: hoy `portfolio_transaction.security_id` es obligatorio, así que hace falta una migración.

**O2 🤖 Hoja de órdenes semanal sobre tu cartera.** Es el corazón de "operar".
- Qué vender, a qué nivel mover cada stop y qué comprar, con el importe en €.
- Sale de las mismas funciones del motor que el backtest, partiendo de tu cartera real.
- Queda detrás de un interruptor `PERSONALIZATION_ENABLED`, activado solo para ti (decisión D-6: esto es recomendación personalizada y no puede abrirse a terceros sin revisión legal).
- Arreglar a la vez que las señales del motor van una semana tarde: la última revisión se descarta porque su sesión de ejecución cae fuera del calendario (`core/estrategia/backtest.py`).

**O3 🤖 eToro y 1.000 €.**
- Comprar fracciones de acción: hoy `acciones` es un entero en `core/estrategia/tipos.py` y `riesgo.py`.
- Las tarifas reales de eToro, incluida la conversión de divisa, en `costes`.
- Revisar `max_posiciones`, `max_por_mercado` y `peso_maximo` para 1.000 €.
- Todo va al registro de cambios.

**O4 🤖 Alertas (FASE 15).**
- Aviso por email o Telegram cuando haya que mover un stop o cuando salga la hoja semanal.
- Las tablas `alert` y `alert_event` ya existen; no hay nada construido encima.

**O5 👤 De 8 a 12 semanas en simulado.**
- Con la cartera virtual de eToro, siguiendo la hoja y registrando lo que ejecutas.
- Para pasar a real: ninguna diferencia sin explicar, y costes reales iguales o menores que los del modelo.

## Fase 5 — Completar la web

**W1 🤝 Explicaciones con IA (FASE 16).**
- Probar una llamada real. Nunca se ha hecho y necesita `ANTHROPIC_API_KEY` con límite de gasto.
- Darte un plan que las incluya: el plan FREE tiene 0 al día.
- Quitar el texto del panel que dice que esa capa "todavía no está construida".

**W2 🤖 Huecos de la web.**
- Restablecer la contraseña y la página de ajustes.
- Las entradas del menú marcadas "PRONTO".
- Las pestañas Valoración, Comparables y Noticias: ocultarlas si no hay datos, en lugar de enseñar un hueco.

**W3 🤖 Screeners guardados (FASE 11).** La tabla `saved_screener` ya existe.

## Fase 6 — Validación y cierre de versión

**V1 🤖 Sensibilidad.**
- Mover los parámetros que hoy no se mueven (`core/estrategia/validacion.py`).
- Informar de las variantes inválidas en vez de saltarlas en silencio.
- Dar un veredicto de "robusta / no robusta".

**V2 👤🤝 Cerrar la versión.**
- Congelar los parámetros.
- Abrir el periodo de validación (desde `validacion.fecha_corte`, 2020-09-01) **una sola vez**.
- Anotar el resultado en el registro de cambios de `ESTRATEGIA.md`.

## Aparcado mientras sea de uso propio

Todo esto es necesario antes de cobrar, y no antes:

- **Datos:** un proveedor con licencia comercial (riesgo RD-1: yfinance no la tiene).
- **Legal:** revisión de MAR y MiFID (decisión D-6).
- **Cuentas y cobro:** pagos, verificación de email, 2FA, borrar la cuenta, páginas de privacidad y términos, y límites de peticiones por plan.
- **Más producto:**
  - machine learning (FASE 8: necesita 1.000 valores; hoy hay 138);
  - más mercados;
  - el copiloto conversacional;
  - empresas deslistadas.

---

## Hecho

**Tareas A y B, del plan anterior (motor), ya integradas en la plataforma:**
- A1: `PLAN.md` y `CLAUDE.md`.
- A2: tests en verde y versiones máximas.
- A3: copia fija de la configuración para los tests.
- A4: CI. Hoy lo cubre `.github/workflows/ci.yml`.
- B1–B10: correcciones del motor. El detalle de cada una está en el registro de cambios de `ESTRATEGIA.md` (versiones 0.4.1 a 0.4.9):
  - B1: fuentes de datos por defecto;
  - B2: reparto de huecos global entre mercados;
  - B3: deslizamiento contado una vez;
  - B4: calentamiento con histórico previo y años encadenados;
  - B5: percentiles y EV;
  - B6: descargas robustas;
  - B7: yfinance;
  - B8: sectores;
  - B9: corte fijo entre diseño y validación;
  - B10: limpieza.

**I1: integración de B1–B10 en la plataforma** (motor v0.5.0), pendiente de fusionar en `main`.
