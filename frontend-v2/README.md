# LaLonja Trading — frontend (v2, estilo claro)

Implementación en Next.js 14 (App Router, componentes de servidor, CSS propio con variables, fuentes autoalojadas) del diseño «LaLonja Trading v2» de Claude Design (estilo claro). Convive con `frontend/` sin sustituirlo.

```bash
npm install
cp .env.example .env.local   # LALONJA_API_URL=… o LALONJA_DEMO=1
npm run dev
```

## Qué hay

| Ruta | Estado |
| --- | --- |
| `/` Portada | Diseñada. Las cifras del universo salen de la API; si no hay, se declara. |
| `/entrar` (`?modo=registro`) | Diseñada. Acción de servidor, contraseña ≥ 12, funciona sin JS. |
| `/restablecer` (`?token=…` para el paso 2) | Diseñada. |
| `/panel` | Diseñada: mercados, distribución de señales, mejor puntuados, más mejoran / más caen. |
| `/mercados` | Diseñada. En móvil, cada fila pasa a tarjeta. |
| `/hoja` | Bloqueo «uso personal desactivado» diseñado; el contenido, pendiente. |
| `/ajustes` | Provisional: solo el interruptor de uso personal (cookie). |
| Descubrir, Ficha, Seguimiento, Cartera, Alertas, Estado de los datos, Buscar, Analista IA | Pendientes de diseño en la v2: muestran el aviso de pendiente. |

Comunes a toda la app: barra superior con búsqueda (atajo `/`), fecha de los datos, franja de frescura por mercado, menú lateral agrupado (Operar marcado PERSONAL y oculto sin uso personal), barra inferior en móvil con «Más» (un `<details>`, sin JS), aviso legal fijo.

## Notas de implementación

- **Estados por bloque.** Todo dato llega como `Loaded<T>` (`lib/types.ts`): `ok` con fecha, `unavailable` con motivo o `error`. Cada bloque pinta su propio «no disponible», así que el estado «parcial» sale solo. La página entera pasa a error solo si fallan todos los bloques, y a «primer uso» si no hay mercados ni scores. «Cargando» es `app/(app)/loading.tsx`.
- **Consulta pasada.** `?fecha=YYYY-MM-DD` (anterior a hoy). El middleware la reenvía como cabecera porque los layouts no reciben `searchParams`; la navegación la conserva. Invierte la cabecera a oscuro y muestra la franja rayada con «Volver a hoy».
- **Uso personal.** Cookie `lalonja_uso_personal`, **desactivado por defecto** (en la maqueta venía activado).
- **Medidor de score.** 10 celdas de un solo tono (`--tone-0…9` en `app/app.css`), nunca semáforo.
- **Contrato de API supuesto** (en `lib/api.ts` y `lib/auth-actions.ts`; ajústalo a la API real): `GET /markets`, `/rankings/top`, `/rankings/movers`, `/signals/distribution`, `/universe/stats`, que devuelven `{ data, as_of }` o `{ unavailable: "motivo" }`, con `?fecha=`; `POST /auth/login|register|reset-request|reset`.
- **Demo.** `LALONJA_DEMO=1|parcial|vacio|error` usa las cifras de la maqueta con una franja «DATOS DE DEMOSTRACIÓN» visible. No son datos reales.
- Estilo: tokens de Industry copiados en `app/industry.css`; acento azul acero, oro solo en el logotipo; verde `#1b7350` y rojo `#ad3b27` siempre con ▲/▼.
- `/metodologia` aún no existe (los enlaces del aviso legal apuntan ahí).
