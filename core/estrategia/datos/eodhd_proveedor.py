"""Fuente EODHD: fundamentales y sectores.

Es la ampliacion que el propio documento contempla
(`proveedor_datos.ampliacion_futura: eodhd`), y lo que aporta ataca la limitacion
mas seria que tiene hoy el sistema: **historico largo y fecha de presentacion
real de cada ejercicio** (`filing_date`). Con yfinance hay que estimar cuando se
publicaron las cuentas sumando un retraso fijo, y ademas solo se llega a unos
cuatro ejercicios, lo que deja la estrategia sin poder operar hasta que aparece
el cuarto, porque el crecimiento de ventas a tres anos necesita cuatro.

Una distincion importante que conviene no difuminar: una fecha de presentacion
real arregla **cuando** se supo algo, no **que version** se supo. Los
fundamentales estandar de EODHD, como los de casi todo el mundo, vienen
reexpresados a dia de hoy. Por eso esta fuente declara
`fechas_publicacion_reales=True` pero sigue declarando
`cifras_reexpresadas=True`, y las filas siguen saliendo con
`origen_pit: reconstruido`. Lo unico que convierte eso en `capturado` es la foto
semanal, que va guardando lo que se veia en cada momento.

**No se ha podido ejecutar.** Ni hay clave ni el entorno de desarrollo tiene
salida a internet, asi que esto esta escrito contra la documentacion de la API y
probado contra respuestas grabadas en `tests/fixtures/eodhd/`. El parseo, que es
donde de verdad se puede equivocar uno, esta en funciones puras con tests. La
primera ejecucion con clave es la que dira si los nombres de los campos son los
esperados; `estrategia diagnostico` existe para que esa vez devuelva una lista y
no una traza.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any

import pandas as pd

from ..config import Config
from ..errores import ErrorDatos
from .proveedor import Capacidades, ProveedorFundamentales

BASE = "https://eodhd.com/api"
VARIABLE_CLAVE = "EODHD_API_KEY"

#: Nombres alternativos de cada concepto en los estados financieros. EODHD es
#: bastante estable, pero no cuesta nada admitir variantes y evita que un cambio
#: de nombre tumbe la descarga entera.
CAMPOS = {
    "ventas": ("totalRevenue", "revenue"),
    "ebit": ("operatingIncome", "ebit"),
    "ebitda": ("ebitda",),
    "beneficio_neto": ("netIncome", "netIncomeApplicableToCommonShares"),
    "patrimonio_neto": ("totalStockholderEquity", "totalEquity"),
    "deuda_total": ("shortLongTermDebtTotal", "totalDebt", "netDebt"),
    "efectivo": ("cash", "cashAndEquivalents", "cashAndShortTermInvestments"),
    "acciones": ("commonStockSharesOutstanding", "commonStock"),
    "flujo_operativo": ("totalCashFromOperatingActivities",),
    "capex": ("capitalExpenditures",),
}


def _numero(bloque: dict, nombres: tuple[str, ...]) -> float | None:
    """Primer campo con valor utilizable de entre los nombres dados.

    EODHD devuelve los importes como cadenas y usa `None` y `"0"` con
    significados distintos, asi que conviene convertir con cuidado.
    """
    for nombre in nombres:
        crudo = bloque.get(nombre)
        if crudo in (None, "", "None"):
            continue
        try:
            return float(crudo)
        except (TypeError, ValueError):
            continue
    return None


def _fecha(texto: Any) -> date | None:
    if not texto:
        return None
    try:
        return datetime.strptime(str(texto)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def ticker_eodhd(ticker: str, mercado_id: str, cfg: Config) -> str:
    """Traduce un ticker del universo al formato de EODHD.

    Los sufijos no coinciden con los de Yahoo: lo que alli es `RELIANCE.NS` aqui
    es `RELIANCE.NSE`, y `SAP.DE` es `SAP.XETRA`. El mapeo vive en
    `implementacion.yaml` para no incrustarlo en el codigo.
    """
    codigo = cfg.implementacion.codigos_eodhd.get(mercado_id)
    if not codigo:
        raise ErrorDatos(
            f"falta el codigo de bolsa de EODHD para el mercado '{mercado_id}' "
            f"en implementacion.yaml (codigos_eodhd)"
        )
    base = ticker.split(".")[0]
    return f"{base}.{codigo}"


def parsear_fundamentales(
    payload: dict, ticker: str, mercado_id: str, cfg: Config, descargado: date
) -> list[dict]:
    """Convierte la respuesta de EODHD en filas del esquema del proyecto.

    Funcion pura y con tests: es donde de verdad se puede uno equivocar, y es lo
    unico de esta fuente que se puede validar sin clave y sin red.
    """
    general = payload.get("General") or {}
    financieros = payload.get("Financials") or {}
    divisa_reporte = general.get("CurrencyCode")
    divisa_cotizacion = general.get("CurrencySymbol") or divisa_reporte

    balance = (financieros.get("Balance_Sheet") or {}).get("yearly") or {}
    resultados = (financieros.get("Income_Statement") or {}).get("yearly") or {}
    caja = (financieros.get("Cash_Flow") or {}).get("yearly") or {}

    filas: list[dict] = []
    for clave, bloque_res in resultados.items():
        fin_periodo = _fecha(bloque_res.get("date") or clave)
        if fin_periodo is None:
            continue

        bloque_bal = balance.get(clave, {})
        bloque_caja = caja.get(clave, {})

        # La razon de ser de esta fuente: la fecha real de presentacion. Si
        # faltara en algun ejercicio se estima, y se deja dicho cual es cual.
        presentacion = _fecha(bloque_res.get("filing_date"))
        if presentacion is not None:
            origen_fecha = "proveedor"
        else:
            from .yfinance_proveedor import estimar_fecha_publicacion

            presentacion = estimar_fecha_publicacion(
                fin_periodo, mercado_id, cfg, "anual"
            )
            origen_fecha = "estimada_retraso"

        ventas = _numero(bloque_res, CAMPOS["ventas"])
        ebit = _numero(bloque_res, CAMPOS["ebit"])
        neto = _numero(bloque_res, CAMPOS["beneficio_neto"])
        patrimonio = _numero(bloque_bal, CAMPOS["patrimonio_neto"])
        deuda = _numero(bloque_bal, CAMPOS["deuda_total"])
        efectivo = _numero(bloque_bal, CAMPOS["efectivo"])
        acciones = _numero(bloque_bal, CAMPOS["acciones"])

        operativo = _numero(bloque_caja, CAMPOS["flujo_operativo"])
        capex = _numero(bloque_caja, CAMPOS["capex"])
        # El capex viene negativo en unos sitios y positivo en otros; con el
        # valor absoluto el flujo de caja libre sale bien en los dos casos.
        flujo = None
        if operativo is not None:
            flujo = operativo - abs(capex) if capex is not None else operativo

        filas.append(
            {
                "ticker": ticker,
                "fin_periodo": fin_periodo,
                "periodo": "anual",
                "fecha_publicacion": presentacion,
                "origen_fecha_publicacion": origen_fecha,
                # La fecha es real, pero las cifras siguen reexpresadas a hoy:
                # eso no lo arregla ningun proveedor, solo la foto semanal.
                "origen_pit": "reconstruido",
                "fecha_descarga": descargado,
                "roe": (neto / patrimonio)
                if neto is not None and patrimonio not in (None, 0)
                else None,
                "margen_operativo": (ebit / ventas)
                if ebit is not None and ventas
                else None,
                "ventas": ventas,
                "flujo_caja_libre": flujo,
                "deuda_neta": (deuda - (efectivo or 0.0)) if deuda is not None else None,
                "ebitda": _numero(bloque_res, CAMPOS["ebitda"]),
                "ebit": ebit,
                # El EV se calcula en la fecha de decision con el precio de ese
                # dia; aqui solo se aportan las piezas.
                "ev": None,
                "patrimonio_neto": patrimonio,
                "acciones_en_circulacion": acciones,
                "divisa_reporte": divisa_reporte,
                "divisa_cotizacion": divisa_cotizacion,
            }
        )

    filas.sort(key=lambda f: f["fin_periodo"])
    return filas


def parsear_sector(payload: dict) -> str | None:
    return ((payload.get("General") or {}).get("Sector")) or None


class ProveedorEODHD(ProveedorFundamentales):
    """Fundamentales y sectores desde EODHD."""

    nombre = "eodhd"

    def __init__(self, cfg: Config, clave: str | None = None) -> None:
        self._cfg = cfg
        self._clave = clave or os.environ.get(VARIABLE_CLAVE, "")
        self._cache: dict[str, dict] = {}

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("fundamentales", "sectores"),
            # Su valor esta justo aqui: historico largo, frente a los cuatro
            # ejercicios del proveedor gratuito.
            anios_fundamentales=20,
            fechas_publicacion_reales=True,
            # Pero las cifras siguen siendo las de hoy, no las de entonces.
            cifras_reexpresadas=True,
            incluye_deslistadas=False,
            mercados=tuple(self._cfg.implementacion.codigos_eodhd),
            necesita_clave=True,
            notas=(
                "Da la fecha real de presentacion de cada ejercicio, lo que "
                "elimina la estimacion por retraso fijo.",
            ),
        )

    def disponible(self) -> tuple[bool, str]:
        if not self._clave:
            return False, (
                f"falta la clave de API. Exporta {VARIABLE_CLAVE} o anadela como "
                f"secreto del repositorio si corre en CI."
            )
        return True, ""

    def _pedir(self, ruta: str, **parametros: str) -> dict:
        """Una llamada a la API, con la clave y en JSON."""
        ok, motivo = self.disponible()
        if not ok:
            raise ErrorDatos(motivo)

        parametros = {"api_token": self._clave, "fmt": "json", **parametros}
        url = f"{BASE}/{ruta}?{urllib.parse.urlencode(parametros)}"
        try:
            with urllib.request.urlopen(url, timeout=60) as respuesta:
                return json.loads(respuesta.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise ErrorDatos("EODHD ha rechazado la clave de API") from exc
            if exc.code == 402:
                raise ErrorDatos(
                    "EODHD dice que el plan actual no cubre esta peticion"
                ) from exc
            if exc.code == 404:
                raise ErrorDatos(f"EODHD no conoce {ruta}") from exc
            raise ErrorDatos(f"EODHD ha respondido {exc.code} a {ruta}") from exc
        except urllib.error.URLError as exc:
            raise ErrorDatos(f"no se ha podido conectar con EODHD: {exc.reason}") from exc

    def ficha(self, ticker: str) -> dict:
        """Respuesta completa de fundamentales de un valor, cacheada.

        Se cachea porque la misma respuesta sirve para los fundamentales y para
        el sector, y cada llamada consume cuota.
        """
        if ticker not in self._cache:
            mercado_id = self._cfg.universo.mercado_de_ticker.get(ticker)
            if mercado_id is None:
                self._cache[ticker] = {}
            else:
                simbolo = ticker_eodhd(ticker, mercado_id, self._cfg)
                try:
                    self._cache[ticker] = self._pedir(f"fundamentals/{simbolo}")
                except ErrorDatos:
                    # Un valor que no resuelve se queda fuera y sale en el
                    # diagnostico; no tumba una descarga de 140 tickers.
                    self._cache[ticker] = {}
        return self._cache[ticker]

    def fundamentales(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        hoy = date.today()
        filas: list[dict] = []
        for ticker in tickers:
            mercado_id = self._cfg.universo.mercado_de_ticker.get(ticker)
            if mercado_id is None:
                continue
            payload = self.ficha(ticker)
            if not payload:
                continue
            for fila in parsear_fundamentales(
                payload, ticker, mercado_id, self._cfg, hoy
            ):
                # Se filtra por fecha de publicacion y no por cierre de periodo:
                # lo que importa es cuando se supo, no a que ejercicio se refiere.
                if fila["fecha_publicacion"] <= fin:
                    filas.append(fila)
        return pd.DataFrame(filas)

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        return {t: parsear_sector(self.ficha(t)) for t in tickers}
