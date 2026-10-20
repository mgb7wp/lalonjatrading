"""Fuente Yahoo directa: precios de los cinco mercados sin la libreria yfinance.

Habla con el mismo servicio que yfinance (el grafico v8 de Yahoo Finance, el que
usa la propia web), pero sin pasar por la libreria. Su papel es de **respaldo de
precios** (tarea M5): la libreria yfinance es un cliente no oficial que ya se ha
roto mas de una vez al cambiar Yahoo algo, y cuando eso pasa el servicio de
Yahoo suele seguir funcionando.

Lo que NO protege: si Yahoo bloquea las peticiones (el 429 que se ve desde la
nube), esta fuente cae a la vez que yfinance, porque es el mismo servidor. Para
eso esta Tiingo en EE. UU.

Adaptado del cliente de Vibe-Trading (HKUDS, licencia MIT,
`agent/backtest/loaders/yahoo_client.py`): de alli salen la peticion al grafico
v8 y el ajuste por dividendos con `adjclose / close`.

## Lo que devuelve

El `close` del grafico ya viene ajustado por splits, pero no por dividendos,
igual que el `Close` de yfinance con `auto_adjust=False`. El ajuste por
dividendos es el cociente `adjclose / close` de cada dia, aplicado a los cuatro
precios, como hace `yfinance_proveedor.ajustar_ohlc`:

- `apertura`, `maximo`, `minimo` y `cierre`: ajustados;
- `cierre_bruto`: el `close` del grafico;
- un dia sin `adjclose` utilizable se descarta si el resto lo tiene, para no
  mezclar en una serie dias ajustados y sin ajustar. Una respuesta sin ningun
  `adjclose` no se usa: el contrato pide precios ajustados.

Cada barra se fecha con la hora de la bolsa (`gmtoffset` del grafico), no con
la UTC: en una bolsa que abre antes de medianoche UTC, la fecha UTC seria la del
dia anterior.

## Estado

**No se ha podido ejecutar**: el entorno de desarrollo recibe un 429 de Yahoo.
El parseo esta en una funcion pura con tests sobre respuestas con el formato del
grafico v8.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from datetime import time as hora
from typing import Any

import pandas as pd

from ..config import Config
from ..errores import ErrorDatos
from .proveedor import Capacidades, ProveedorPrecios

BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

#: Yahoo rechaza el agente por defecto de urllib; se presenta como un navegador.
AGENTE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: Un factor de ajuste fuera de este rango no es un dividendo: es un dato roto.
FACTOR_MINIMO, FACTOR_MAXIMO = 0.01, 100.0


class LimiteAlcanzado(ErrorDatos):
    """Yahoo ha cortado (429): el resto de valores fallaria igual."""


def _numero(serie: Any, i: int) -> float | None:
    if not isinstance(serie, list) or not 0 <= i < len(serie):
        return None
    try:
        valor = float(serie[i])
    except (TypeError, ValueError):
        return None
    return valor if math.isfinite(valor) else None


def parsear_grafico(datos: Any, ticker: str) -> list[dict]:
    """Convierte una respuesta del grafico v8 en filas del contrato de precios.

    Una respuesta con `chart.error` (valor desconocido, sin datos) da una lista
    vacia: es un valor que falta, no un fallo de la fuente.
    """
    grafico = (datos or {}).get("chart") or {}
    if grafico.get("error") or not grafico.get("result"):
        return []
    resultado = grafico["result"][0] or {}
    desfase = (resultado.get("meta") or {}).get("gmtoffset") or 0
    marcas = resultado.get("timestamp") or []
    indicadores = resultado.get("indicators") or {}
    cotizacion = ((indicadores.get("quote") or [{}])[0]) or {}
    ajustado = (((indicadores.get("adjclose") or [{}])[0]) or {}).get("adjclose")

    filas: list[dict] = []
    for i, marca in enumerate(marcas):
        apertura, maximo, minimo, cierre = (
            _numero(cotizacion.get(c), i) for c in ("open", "high", "low", "close")
        )
        # Las ranuras sin negociacion vienen a nulo: no son dias.
        if None in (apertura, maximo, minimo, cierre) or cierre <= 0:
            continue
        adj = _numero(ajustado, i)
        factor = adj / cierre if adj is not None and adj > 0 else None
        if factor is None or not FACTOR_MINIMO <= factor <= FACTOR_MAXIMO:
            continue
        try:
            fecha = (datetime.fromtimestamp(int(marca), UTC) + timedelta(seconds=desfase)).date()
        except (TypeError, ValueError, OverflowError):
            continue
        volumen = _numero(cotizacion.get("volume"), i)
        filas.append(
            {
                "fecha": fecha,
                "ticker": ticker,
                "apertura": apertura * factor,
                "maximo": maximo * factor,
                "minimo": minimo * factor,
                "cierre": adj,
                "cierre_bruto": cierre,
                "volumen": volumen if volumen is not None and volumen >= 0 else 0.0,
            }
        )
    return filas


def _epoca(dia: date) -> int:
    return int(datetime.combine(dia, hora(0), UTC).timestamp())


class ProveedorYahoo(ProveedorPrecios):
    """Precios diarios del grafico v8 de Yahoo, sin la libreria yfinance."""

    nombre = "yahoo"

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._red = cfg.implementacion.descargas
        #: Lo que no se ha podido traer, valor a valor. El enrutador lo recoge.
        self.avisos: list[str] = []

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("precios",),
            # Los cinco mercados, los indices de regimen y las referencias del
            # informe: todo lo que yfinance sirve.
            mercados=None,
            notas=(
                "Mismo servidor que yfinance: protege si se rompe la libreria, no "
                "si Yahoo bloquea las peticiones.",
            ),
        )

    def _pedir(self, ticker: str, inicio: date, fin: date) -> Any:
        """Una llamada al grafico, con reintentos ante fallos de red o del servidor."""
        parametros = urllib.parse.urlencode(
            {
                "period1": _epoca(inicio),
                # `period2` es exclusivo: se pide hasta el dia siguiente al fin.
                "period2": _epoca(fin + timedelta(days=1)),
                "interval": "1d",
                "events": "div,splits",
                "includeAdjustedClose": "true",
            }
        )
        peticion = urllib.request.Request(
            f"{BASE}/{urllib.parse.quote(ticker)}?{parametros}",
            headers={"User-Agent": AGENTE, "Accept": "application/json"},
        )
        espera = self._red.espera_inicial_s
        for intento in range(self._red.intentos):
            try:
                with urllib.request.urlopen(peticion, timeout=60) as respuesta:
                    return json.loads(respuesta.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return {}
                if exc.code == 429:
                    raise LimiteAlcanzado("Yahoo ha cortado por volumen (429)") from exc
                ultimo: Exception = exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                ultimo = exc
            if intento < self._red.intentos - 1:
                time.sleep(espera)
                espera *= 2
        raise ErrorDatos(f"Yahoo no responde para {ticker}: {ultimo}")

    def precios(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        filas: list[dict] = []
        sin_precios: list[str] = []
        for i, ticker in enumerate(tickers):
            if i and self._red.pausa_entre_peticiones_s > 0:
                time.sleep(self._red.pausa_entre_peticiones_s)
            try:
                del_valor = parsear_grafico(self._pedir(ticker, inicio, fin), ticker)
            except LimiteAlcanzado:
                # Con Yahoo cortando, el resto fallaria igual: se corta aqui y
                # el enrutador pasa al siguiente respaldo.
                raise
            except ErrorDatos as exc:
                self.avisos.append(f"[yahoo/precios] {ticker}: {exc}")
                continue
            del_valor = [f for f in del_valor if inicio <= f["fecha"] <= fin]
            if del_valor:
                filas.extend(del_valor)
            else:
                sin_precios.append(ticker)
        if sin_precios:
            self.avisos.append(
                f"[yahoo/precios] {len(sin_precios)} valores sin precios: {', '.join(sin_precios)}"
            )
        return pd.DataFrame(filas)

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        raise ErrorDatos("la fuente 'yahoo' no sirve divisas en este proyecto: usa 'bce'")

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        return dict.fromkeys(tickers)
