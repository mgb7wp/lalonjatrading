# Normas del proyecto para Claude Code

## Quién usa esto
- El dueño **no es programador**. Explícale los resultados en español y en lenguaje llano: qué ha cambiado, por qué importa y qué tiene que hacer él, si tiene que hacer algo.
- El código, los comentarios, los mensajes y la documentación van en español, como el resto del repositorio.
- Contexto del dueño:
  - opera con eToro, con 1.000 € de capital inicial (primero en simulado);
  - usa un ordenador Windows que está siempre encendido;
  - consulta las órdenes en una web privada de Cloudflare.

## El plan
- `PLAN.md` es la lista de tareas. Cuando te pidan "haz la tarea X", léela allí antes de empezar.
- Al terminar una tarea, márcala en la sección "Estado de las tareas" de `PLAN.md`.
- No mezcles tareas en un mismo cambio salvo que te lo pidan.

## Jerarquía de documentos
1. `ESTRATEGIA.md` es la fuente de verdad. Si el código y el documento no coinciden, manda el documento.
2. `SUPUESTOS.md` recoge cómo se resolvió lo que el documento no decide.
3. El código implementa ambos.

## Reglas que no se saltan
- **Parámetros:** todos viven en `config/`. Nada de números sueltos en el código.
- **Cambios de regla o de parámetro:** cualquier cambio que altere resultados necesita:
  - una fila en el registro de cambios de `ESTRATEGIA.md`;
  - su explicación en `SUPUESTOS.md` si es una interpretación.
- **Periodo de validación:** no ejecutes `backtest --periodo validacion` ni lo mires por otra vía sin permiso explícito del dueño. Cada consulta lo gasta.
- **Anticipación:** los tests de `tests/test_anti_sesgo.py` son condición de entrada. Si uno falla, ningún resultado vale.
- **Capas:** respeta el orden de importaciones que comprueba `tests/test_motor.py`.
- **Datos sintéticos:** nunca publiques en `sitio/` un informe hecho con datos sintéticos.
- **Secretos:** nunca subas claves al repositorio (`EODHD_API_KEY`, tokens de Cloudflare). Van en variables de entorno.

## Cómo trabajar
- **Instalación:** `pip install -e ".[panel,dev]"` (Python 3.11 o superior).
- **Tests:** `pytest`. Ejecútalos siempre antes de dar algo por terminado. Cada arreglo lleva su test.
- **Sin red:** `estrategia --proveedor sintetico ...`. La opción `--proveedor` va antes del subcomando.
  - Hoy `--proveedor` vale `sintetico` por defecto. Es un fallo pendiente: la tarea B1 de `PLAN.md`.
- **Datos reales:** desde la nube, Yahoo Finance devuelve el error 429. Lo que necesite datos reales se ejecuta en el ordenador Windows del dueño (tareas marcadas 💻 en `PLAN.md`).
- **Ramas:** trabaja en la rama indicada para la sesión y no fusiones en `main` sin que el dueño lo pida.
