"""Fuente Stooq: precios de cierre diario, como respaldo.

Gratuita, sin clave y con cobertura de los cinco mercados. Su papel previsto es
**respaldo de precios**: que un dia se rompa yfinance —que es un cliente no
oficial y se rompe cada vez que Yahoo cambia algo— y el sistema siga sirviendo.

## Lo que no se sabe de esta fuente, y hay que saber antes de fiarse

Stooq no documenta con claridad **sobre que base ajusta los precios**. Que este
ajustado por splits es casi seguro; que lo este por dividendos, no.

Y la diferencia no es un detalle. El contrato de este proyecto exige OHLC
ajustado por dividendos y splits, porque calcular el ATR con maximos y minimos
en bruto y las medias con el cierre ajustado convierte cada dividendo en un hueco
fantasma. Si Stooq no ajusta por dividendos y se usa como duena de precios sin
saberlo, cada reparto se convierte en una caida que el motor leera como senal.

Por eso esta fuente:

1. Declara la duda en sus `notas`, que es de donde el informe saca sus avisos.
2. Devuelve `cierre_bruto` **igual** al cierre, en lugar de fingir que distingue
   dos series que no ha podido distinguir. Eso encoge la medida de liquidez en
   valores con mucho dividendo, y es preferible a inventarse la diferencia.
3. Tiene una comprobacion dedicada en `scripts/verify_sources.py` que la compara
   con yfinance sobre un valor que reparte dividendo. Si divergen de forma
   sistematica, no ajusta por dividendos y **no puede ser duena de precios**.

Mientras esa comprobacion no se haya pasado con red de verdad, usar Stooq como
`proveedor_datos.precios` es una decision sin fundamento. Como respaldo puntual
para no quedarse a oscuras, sirve.

## Estado

**No se ha podido ejecutar**: el entorno de desarrollo bloquea `stooq.com` por
politica de red. El parseo esta en una funcion pura con tests.
"""

from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
from datetime import date, datetime

import pandas as pd

from ..config import Config
from ..errores import ErrorDatos
from .proveedor import Capacidades, ProveedorPrecios

BASE = "https://stooq.com/q/d/l/"


def simbolo_stooq(ticker: str, mercado_id: str, cfg: Config) -> str:
    """Traduce un ticker del universo al formato de Stooq.

    Los sufijos no coinciden con los de Yahoo: `ITX.MC` alli es `itx.es` y
    `PETR4.SA` es `petr4.br`. El mapeo vive en `implementacion.yaml` para no
    incrustarlo en el codigo, igual que el de EODHD.
    """
    codigo = cfg.implementacion.codigos_stooq.get(mercado_id)
    if codigo is None:
        raise ErrorDatos(
            f"falta el sufijo de Stooq para el mercado '{mercado_id}' en "
            f"implementacion.yaml (codigos_stooq)"
        )
    base = ticker.split(".")[0].lower()
    return f"{base}.{codigo}" if codigo else base


def _numero(fila: dict, clave: str) -> float | None:
    crudo = fila.get(clave)
    try:
        return float(crudo) if crudo not in (None, "", "N/A") else None
    except ValueError:
        return None


def parsear_csv(texto: str, ticker: str) -> list[dict]:
    """Convierte el CSV diario de Stooq en filas del contrato de precios.

    Stooq devuelve texto plano tambien cuando no hay datos ("No data"), asi que
    un CSV sin las columnas esperadas es un caso normal y no una excepcion.
    """
    filas: list[dict] = []
    lector = csv.DictReader(io.StringIO(texto))
    if not lector.fieldnames or "Date" not in lector.fieldnames:
        return filas

    for fila in lector:
        try:
            fecha = datetime.strptime(fila["Date"][:10], "%Y-%m-%d").date()
            cierre = float(fila["Close"])
        except (KeyError, TypeError, ValueError):
            continue

        filas.append(
            {
                "fecha": fecha,
                "ticker": ticker,
                "apertura": _numero(fila, "Open"),
                "maximo": _numero(fila, "High"),
                "minimo": _numero(fila, "Low"),
                "cierre": cierre,
                # Igual al ajustado a proposito: no se ha podido comprobar que
                # Stooq distinga ambas series, y fingir la distincion seria
                # peor que no tenerla. Ver el docstring del modulo.
                "cierre_bruto": cierre,
                "volumen": _numero(fila, "Volume") or 0.0,
            }
        )
    return filas


class ProveedorStooq(ProveedorPrecios):
    """Precios diarios desde Stooq."""

    nombre = "stooq"

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("precios",),
            incluye_deslistadas=False,
            mercados=tuple(self._cfg.implementacion.codigos_stooq),
            necesita_clave=False,
            notas=(
                "AJUSTE POR DIVIDENDOS SIN VERIFICAR: comprobalo con "
                "scripts/verify_sources.py antes de usarla como duena de precios.",
                "cierre_bruto se devuelve igual al cierre; la liquidez medida "
                "queda algo por debajo de la real en valores con dividendo alto.",
                "Pensada como respaldo de yfinance, no como fuente principal.",
            ),
        )

    def _pedir(self, simbolo: str) -> str:
        url = f"{BASE}?s={simbolo}&i=d"
        try:
            with urllib.request.urlopen(url, timeout=60) as respuesta:
                return respuesta.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise ErrorDatos(f"Stooq ha respondido {exc.code} a {simbolo}") from exc
        except urllib.error.URLError as exc:
            raise ErrorDatos(f"no se ha podido conectar con Stooq: {exc.reason}") from exc

    def precios(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        filas: list[dict] = []
        for ticker in tickers:
            mercado_id = self._cfg.universo.mercado_de_ticker.get(ticker)
            if mercado_id is None:
                continue
            try:
                texto = self._pedir(simbolo_stooq(ticker, mercado_id, self._cfg))
            except ErrorDatos:
                # Un valor que no resuelve se queda fuera y sale en el
                # diagnostico; no tumba una descarga de 140 tickers.
                continue
            # Stooq sirve el historico entero y no admite rango, asi que se
            # recorta aqui.
            filas.extend(f for f in parsear_csv(texto, ticker) if inicio <= f["fecha"] <= fin)
        return pd.DataFrame(filas)

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        raise ErrorDatos(
            "Stooq no sirve divisas en este proyecto: usa 'bce', que es la fuente "
            "oficial del tipo de referencia del euro"
        )

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        return dict.fromkeys(tickers)
