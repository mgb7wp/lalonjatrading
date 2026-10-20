"""Fuente Tiingo: precios diarios de EE. UU., como respaldo de yfinance.

Tiingo publica cierres diarios de acciones de EE. UU. por una API documentada,
con clave gratuita. Su papel aqui es el de **respaldo de precios** (tarea M5 de
PLAN.md): si un dia yfinance no devuelve un valor de EE. UU., el enrutador se lo
pide entero a Tiingo (`proveedor_datos.precios_respaldo`).

Adaptado del cargador de Vibe-Trading (HKUDS, licencia MIT,
`agent/backtest/loaders/tiingo_loader.py`): de alli salen el formato de la
respuesta y la regla de no mezclar en una serie barras ajustadas y sin ajustar.

## Lo que devuelve

Cada dia trae el precio de cotizacion (`open`, `high`, `low`, `close`) y el
ajustado por dividendos y splits (`adjOpen`, `adjHigh`, `adjLow`, `adjClose`).
El contrato pide los cuatro ajustados, asi que:

- `apertura`, `maximo`, `minimo` y `cierre` salen de los `adj*`;
- `cierre_bruto` sale de `close`, que en Tiingo no esta ajustado ni por splits.
  El `Close` de yfinance si lo esta. Como el respaldo sirve cada valor entero,
  dentro de una serie no se mezclan los dos criterios;
- una barra sin los cuatro ajustados se descarta. Rellenarla con el precio de
  cotizacion meteria un escalon falso en la serie.

## Estado

**No se ha podido ejecutar**: el entorno de desarrollo no tiene clave. El parseo
esta en una funcion pura con tests sobre respuestas con el formato documentado.
Antes de ponerla en `precios_respaldo`: `python scripts/verify_sources.py --fuente
tiingo` en el servidor.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

import pandas as pd

from ..config import Config
from ..errores import ErrorDatos
from .proveedor import Capacidades, ProveedorPrecios

BASE = "https://api.tiingo.com/tiingo/daily"
VARIABLE_CLAVE = "TIINGO_API_KEY"


class ClaveRechazada(ErrorDatos):
    """Tiingo no acepta la clave: no tiene sentido seguir con el resto."""


class LimiteAlcanzado(ErrorDatos):
    """Tiingo ha cortado por cuota: el resto de valores fallaria igual."""


def simbolo_tiingo(ticker: str) -> str | None:
    """El simbolo de Tiingo para un ticker del universo, o None si no lo sirve.

    Tiingo usa el ticker de EE. UU. en minusculas, con guion para las clases
    (`BRK-B` es `brk-b`). No sirve indices (`^GSPC`) ni valores de otras bolsas,
    que en el universo llevan sufijo (`SAP.DE`).
    """
    limpio = ticker.strip()
    if not limpio or limpio.startswith("^") or "." in limpio:
        return None
    return limpio.lower()


def _positivo(valor: Any) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) and numero > 0 else None


def parsear_precios(filas: Any, ticker: str) -> list[dict]:
    """Convierte la respuesta de `/tiingo/daily/{ticker}/prices` en filas del contrato.

    La respuesta es una lista de dias. Un dia sin los cuatro precios ajustados,
    sin cierre de cotizacion o con algun precio no positivo se descarta entero.
    """
    if not isinstance(filas, list):
        return []
    salida: list[dict] = []
    for fila in filas:
        if not isinstance(fila, dict):
            continue
        try:
            fecha = date.fromisoformat(str(fila.get("date", ""))[:10])
        except ValueError:
            continue
        ajustados = [_positivo(fila.get(c)) for c in ("adjOpen", "adjHigh", "adjLow", "adjClose")]
        bruto = _positivo(fila.get("close"))
        if bruto is None or any(v is None for v in ajustados):
            continue
        apertura, maximo, minimo, cierre = ajustados
        volumen = fila.get("volume")
        try:
            volumen = float(volumen) if volumen is not None else 0.0
        except (TypeError, ValueError):
            volumen = 0.0
        salida.append(
            {
                "fecha": fecha,
                "ticker": ticker,
                "apertura": apertura,
                "maximo": maximo,
                "minimo": minimo,
                "cierre": cierre,
                "cierre_bruto": bruto,
                "volumen": volumen if math.isfinite(volumen) and volumen >= 0 else 0.0,
            }
        )
    return salida


class ProveedorTiingo(ProveedorPrecios):
    """Precios diarios de EE. UU. desde Tiingo."""

    nombre = "tiingo"

    def __init__(self, cfg: Config, clave: str | None = None) -> None:
        self._cfg = cfg
        self._red = cfg.implementacion.descargas
        self._clave = clave if clave is not None else os.environ.get(VARIABLE_CLAVE, "")
        #: Lo que no se ha podido traer, valor a valor. El enrutador lo recoge.
        self.avisos: list[str] = []

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("precios",),
            mercados=("us",),
            necesita_clave=True,
            notas=(
                "Solo EE. UU. y sin indices: el de regimen (^GSPC) tiene que venir de otra fuente.",
                "cierre_bruto es el precio de cotizacion sin ajustar tampoco por "
                "splits; el de yfinance si lo esta.",
                "El plan gratuito limita las peticiones por hora: sirve de respaldo, "
                "no para descargar el universo entero a diario.",
            ),
        )

    def disponible(self) -> tuple[bool, str]:
        if not self._clave.strip():
            return False, f"falta la clave de API: ponla en {VARIABLE_CLAVE} (.env)"
        return True, ""

    def _pedir(self, simbolo: str, inicio: date, fin: date) -> Any:
        """Una llamada a la API, con reintentos ante fallos de red o del servidor.

        La clave va en la cabecera y no en la URL, para que no acabe en un log.
        """
        parametros = urllib.parse.urlencode(
            {"startDate": inicio.isoformat(), "endDate": fin.isoformat()}
        )
        peticion = urllib.request.Request(
            f"{BASE}/{urllib.parse.quote(simbolo)}/prices?{parametros}",
            headers={"Authorization": f"Token {self._clave}", "Accept": "application/json"},
        )
        espera = self._red.espera_inicial_s
        for intento in range(self._red.intentos):
            try:
                with urllib.request.urlopen(peticion, timeout=60) as respuesta:
                    return json.loads(respuesta.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise ClaveRechazada("Tiingo ha rechazado la clave de API") from exc
                if exc.code == 404:
                    return []
                if exc.code == 429:
                    raise LimiteAlcanzado("Tiingo ha cortado por cuota (429)") from exc
                ultimo: Exception = exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                ultimo = exc
            if intento < self._red.intentos - 1:
                time.sleep(espera)
                espera *= 2
        raise ErrorDatos(f"Tiingo no responde para {simbolo}: {ultimo}")

    def precios(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        ok, motivo = self.disponible()
        if not ok:
            raise ErrorDatos(motivo)
        filas: list[dict] = []
        sin_precios: list[str] = []
        for i, ticker in enumerate(tickers):
            simbolo = simbolo_tiingo(ticker)
            if simbolo is None:
                continue
            if i and self._red.pausa_entre_peticiones_s > 0:
                time.sleep(self._red.pausa_entre_peticiones_s)
            try:
                del_valor = parsear_precios(self._pedir(simbolo, inicio, fin), ticker)
            except (ClaveRechazada, LimiteAlcanzado):
                # Con la clave rechazada o la cuota agotada, el resto fallaria
                # igual: se corta aqui y el enrutador pasa al siguiente respaldo.
                raise
            except ErrorDatos as exc:
                self.avisos.append(f"[tiingo/precios] {ticker}: {exc}")
                continue
            if del_valor:
                filas.extend(del_valor)
            else:
                sin_precios.append(ticker)
        if sin_precios:
            self.avisos.append(
                f"[tiingo/precios] {len(sin_precios)} valores sin precios: {', '.join(sin_precios)}"
            )
        return pd.DataFrame(filas)

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        raise ErrorDatos("Tiingo no sirve divisas en este proyecto: usa 'bce'")

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        return dict.fromkeys(tickers)
