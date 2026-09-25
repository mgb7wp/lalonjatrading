# Glosario: nucleo (espanol) ↔ plataforma (ingles)

El motor cuantitativo esta escrito en espanol y no se traduce (decision D-14 de
[PROJECT_PLAN.md](PROJECT_PLAN.md)): reescribir 7.600 lineas probadas para
cambiar nombres es riesgo sin beneficio, y el codigo que mas caro cuesta
verificar es justo el que no conviene tocar por estetica.

El codigo nuevo —esquema de base de datos, endpoints HTTP, frontend— va en
ingles, que es la convencion del ecosistema y lo que espera cualquiera que se
incorpore al proyecto.

La costura entre ambos es deliberada, esta en un solo sitio (`backend/adapters/`)
y se traduce con esta tabla. Todo lo que cruce de `estrategia.*` a un esquema de
API o de base de datos pasa por ahi.

## Entidades

| Nucleo | Plataforma | Nota |
|---|---|---|
| `mercado` | `market` | `es`, `us`, `de`, `in`, `br` |
| `valor` / `ticker` | `security` | el nucleo trabaja con el ticker; la plataforma con una entidad con ISIN |
| `precios` | `price` | OHLCV |
| `fundamentales` | `fundamental_snapshot` | |
| `cartera` | `portfolio` | |
| `posicion` | `portfolio_position` | |
| `operacion` | `transaction` | |
| `candidata` | — | concepto solo del motor de seleccion |

## Datos y trazabilidad

| Nucleo | Plataforma | Nota |
|---|---|---|
| `Instantanea` | *(snapshot)* | conjunto coherente con su `fecha_descarga` |
| `VistaPuntual` | *(point-in-time view)* | la unica puerta hacia el pasado |
| `fecha_descarga` | `downloaded_at` | lo que hace reproducible un backtest |
| `fecha_publicacion` | `publication_date` | lo que fija que se sabia cuando |
| `origen_pit` | `pit_origin` | `capturado`→`captured`, `reconstruido`→`reconstructed` |
| `fuente` | `source` | procedencia de cada fila |
| `Capacidades` | *(capabilities)* | lo que una fuente declara saber hacer |

## Analisis

| Nucleo | Plataforma | Nota |
|---|---|---|
| `puntuacion` | `score` | percentil 0-100 dentro de su cohorte |
| `cohorte_usada` / `n_cohorte` | `cohort_used` / `n_cohort` | sin esto un score raro no se puede rastrear |
| `senal` | `signal` | |
| `MotivoRechazo` | `rejection_reason` | enumeracion cerrada, no texto libre |
| `MotivoSalida` | `exit_reason` | idem |
| `calidad` | `quality` | sub-score de fundamental |
| `valoracion` | `valuation` | sub-score de fundamental |
| `crecimiento` | `growth` | sub-score de fundamental |
| `momentum` | `momentum` | sub-score de tecnico |
| `riesgo` | `risk` | pilar; **100 = menor riesgo** |

## Terminos que no se traducen

`momentum`, `drawdown`, `Sharpe`, `Sortino`, `benchmark`, `spread`, `slippage`
(en el nucleo, `deslizamiento`) y `ticker` se usan igual en ambos lados: son los
nombres con los que se conocen en la industria y traducirlos produciria codigo
mas dificil de leer, no mas facil.
