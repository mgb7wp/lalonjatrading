"""Base de datos -> `Instantanea` del motor. La direccion contraria a `nucleo`.

Permite backtestear con lo que hay en Postgres en lugar de con el Parquet local,
que es el ultimo punto de la FASE 7. Importa: la flecha de dependencias sigue
apuntando en el sentido correcto. El motor **no sabe que existe una base de
datos** —regla de §4 de ARCHITECTURE.md— y por eso la traduccion vive aqui, en
`backend`, y no alli. `Instantanea` es un tipo del motor que se construye desde
fuera con tres DataFrames; nadie tiene que tocar `core/` para esto.

Dos cosas que este modulo hace y que no son obvias:

1. **Trae tambien los valores dados de baja.** Filtrar por `active = true`
   seria reconstruir el universo de hoy y aplicarlo al pasado, que es sesgo de
   supervivencia puro (D-13). Quien decide si un valor cotizaba en una fecha es
   el motor, con `listed_from` y `listed_to`; aqui no se decide, se entrega.
2. **Se niega a servir una base contaminada.** Si conviven precios sinteticos y
   reales, para al leer en vez de producir un backtest que parece normal. Es el
   mismo guardarrail que la ingesta, aplicado al otro extremo: alli impide
   escribir la mezcla, aqui impide consumirla.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from estrategia.datos.almacen import Instantanea
from sqlalchemy import text
from sqlalchemy.orm import Session

#: Fuentes que no son datos de mercado reales. Repetido a proposito y no
#: importado de `workers`: `backend` no debe depender de `workers`, y una
#: constante de dos palabras duplicada cuesta menos que esa dependencia.
FUENTES_SINTETICAS = {"sintetico"}


class BaseContaminada(RuntimeError):
    """La base mezcla datos sinteticos y reales; un backtest sobre eso no vale."""


def _comprobar_fuentes(sesion: Session) -> str:
    """Devuelve la procedencia de los precios, o revienta si estan mezclados."""
    fuentes = {f for (f,) in sesion.execute(text("SELECT DISTINCT source FROM price")).all() if f}
    if not fuentes:
        return "vacia"
    sinteticas = fuentes & FUENTES_SINTETICAS
    reales = fuentes - FUENTES_SINTETICAS
    if sinteticas and reales:
        raise BaseContaminada(
            f"la tabla `price` mezcla fuentes sinteticas {sorted(sinteticas)} con "
            f"reales {sorted(reales)}. Un backtest sobre esa mezcla produce numeros "
            f"que parecen normales y no lo son. Usa una base de datos distinta para "
            f"el proveedor sintetico."
        )
    return "sintetico" if sinteticas else "+".join(sorted(reales))


def _consulta(sesion: Session, sql: str, parametros: dict) -> pd.DataFrame:
    filas = sesion.execute(text(sql), parametros)
    return pd.DataFrame(filas.fetchall(), columns=list(filas.keys()))


def instantanea_desde_bd(
    sesion: Session,
    *,
    mercados: list[str] | None = None,
    desde: dt.date | None = None,
    hasta: dt.date | None = None,
) -> Instantanea:
    """Construye la instantanea que el motor espera, leyendo de Postgres.

    `mercados` acota por mercado; `desde` y `hasta` por fecha. Los tres son
    opcionales: sin ellos se trae todo, que es lo que quiere un backtest largo.
    """
    origen = _comprobar_fuentes(sesion)
    filtros = {
        "mercados": mercados,
        "desde": desde,
        "hasta": hasta,
    }
    donde_mercado = "AND s.market_id = ANY(:mercados)" if mercados else ""
    donde_desde = "AND p.date >= :desde" if desde else ""
    donde_hasta = "AND p.date <= :hasta" if hasta else ""

    precios = _consulta(
        sesion,
        f"""
        SELECT s.ticker            AS ticker,
               p.date              AS fecha,
               p.open              AS apertura,
               p.high              AS maximo,
               p.low               AS minimo,
               p.close             AS cierre,
               p.close_raw         AS cierre_bruto,
               p.volume            AS volumen,
               p.source            AS fuente
        FROM price p
        JOIN security s ON s.id = p.security_id
        -- CON los indices, a proposito. El regimen de mercado (§26) se calcula
        -- sobre la serie del indice de cada mercado, asi que excluirlos aqui
        -- dejaba `vista.serie('^IBEX')` en None y el regimen en DESCONOCIDO
        -- para los cinco mercados, siempre, hiciera lo que hiciera el mercado.
        -- Y DESCONOCIDO se trata aguas abajo como adverso, asi que el motor
        -- emitia senales frenadas sin que nada fallara.
        --
        -- No entran en el universo invertible por venir aqui: quien decide eso
        -- es `cfg.universo.tickers()`, y las etapas que puntuan y rankean
        -- filtran `asset_type <> 'index'` por su cuenta. Es exactamente la
        -- forma que ya tenia la instantanea de fichero, que si trae indices y
        -- referencias en `precios` y solo los valores en `sectores`.
        WHERE TRUE
          {donde_mercado} {donde_desde} {donde_hasta}
        ORDER BY s.ticker, p.date
        """,  # noqa: S608 - los filtros son literales de este modulo, no entrada
        filtros,
    )

    fundamentales = _consulta(
        sesion,
        f"""
        SELECT s.ticker                  AS ticker,
               f.period_end              AS fin_periodo,
               f.publication_date        AS fecha_publicacion,
               f.pit_origin              AS origen_pit,
               f.revenue                 AS ventas,
               f.ebit                    AS ebit,
               f.ebitda                  AS ebitda,
               f.free_cash_flow          AS flujo_caja_libre,
               f.net_debt                AS deuda_neta,
               f.equity                  AS patrimonio_neto,
               f.shares_outstanding      AS acciones_en_circulacion,
               f.enterprise_value        AS ev,
               f.roe                     AS roe,
               f.operating_margin        AS margen_operativo,
               f.net_income              AS beneficio_neto,
               f.gross_profit            AS beneficio_bruto,
               f.total_assets            AS activos_totales,
               f.total_debt              AS deuda_total,
               f.cash                    AS efectivo,
               f.eps                     AS bpa,
               f.current_assets          AS activo_corriente,
               f.current_liabilities     AS pasivo_corriente,
               f.interest_expense        AS gastos_financieros,
               f.reporting_currency      AS divisa_reporte,
               f.listing_currency        AS divisa_cotizacion,
               f.source                  AS fuente
        FROM fundamental_snapshot f
        JOIN security s ON s.id = f.security_id
        WHERE f.period = 'annual'
          {"AND s.market_id = ANY(:mercados)" if mercados else ""}
        ORDER BY s.ticker, f.period_end
        """,  # noqa: S608 - idem
        filtros,
    )

    fx = _consulta(
        sesion,
        """
        SELECT quote_currency AS divisa,
               date           AS fecha,
               rate           AS tasa,
               source         AS fuente
        FROM fx_rate
        WHERE base_currency = 'EUR'
        ORDER BY quote_currency, date
        """,
        {},
    )

    sectores_df = _consulta(
        sesion,
        f"""
        SELECT s.ticker AS ticker, s.sector AS sector
        FROM security s
        WHERE s.asset_type <> 'index'
          {donde_mercado}
        """,  # noqa: S608 - idem
        filtros,
    )

    # Las columnas Numeric de Postgres llegan como Decimal. El motor calcula con
    # numpy, y un array de Decimals se convierte en dtype=object: todo se vuelve
    # lento y algunas operaciones fallan con un error que no menciona el tipo.
    for df, columnas in (
        (precios, ("apertura", "maximo", "minimo", "cierre", "cierre_bruto", "volumen")),
        (
            fundamentales,
            tuple(
                c
                for c in fundamentales.columns
                if c
                not in {
                    "ticker",
                    "fin_periodo",
                    "fecha_publicacion",
                    "origen_pit",
                    "divisa_reporte",
                    "divisa_cotizacion",
                    "fuente",
                }
            ),
        ),
        (fx, ("tasa",)),
    ):
        for col in columnas:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    descarga = sesion.execute(text("SELECT max(downloaded_at) FROM price")).scalar()

    return Instantanea(
        precios=precios,
        fundamentales=fundamentales,
        fx=fx,
        sectores=dict(zip(sectores_df["ticker"], sectores_df["sector"], strict=True)),
        fecha_descarga=descarga.date() if isinstance(descarga, dt.datetime) else descarga,
        origen=f"base de datos ({origen})",
    )
