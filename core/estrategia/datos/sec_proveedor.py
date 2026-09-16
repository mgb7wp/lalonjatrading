"""Fuente SEC EDGAR: fundamentales de EE. UU. con fecha de presentacion real.

Es la unica fuente **gratuita, oficial y legalmente utilizable** que da
fundamentales con la fecha en que se presentaron. Eso ataca de frente la
limitacion mas seria del sistema en el mercado mas grande del universo.

## Por que esta fuente marca `origen_pit: capturado`

Es la unica que puede, y conviene entender por que, porque es la diferencia
entre un backtest creible y uno que se enganna solo.

`companyfacts` no devuelve una cifra por periodo: devuelve **todas las veces que
esa cifra se ha publicado**, cada una con su numero de expediente (`accn`) y su
fecha de presentacion (`filed`). Cuando una empresa reexpresa sus cuentas, o
cuando repite las cifras del ano anterior como comparativa en el 10-K siguiente,
aparece otra entrada para el mismo periodo con `filed` posterior.

Quedarse con la entrada de `filed` **mas antiguo** de cada periodo devuelve la
cifra **tal y como se publico entonces**, no la reexpresada a hoy. Eso es
exactamente lo que significa point-in-time, y es lo que ninguna otra fuente del
proyecto puede ofrecer: EODHD da la fecha real pero las cifras reexpresadas, y
yfinance no da ni una cosa ni la otra.

Por eso esta fuente declara `cifras_reexpresadas=False` y emite
`origen_pit: capturado`. No es optimismo: es una propiedad del formato.

## Alcance

Solo ejercicios **anuales** (10-K). Es lo que consume hoy el filtro fundamental
—el crecimiento de ventas a tres anos necesita cuatro ejercicios— y anadir los
trimestrales sin necesitarlos multiplicaria por cuatro las filas y los modos de
fallar. La estructura admite trimestrales sin cambios: es filtrar por otro
formulario.

El `ev` no sale de aqui: la SEC publica cuentas, no cotizaciones. Se deja a nulo
y el motor lo calcula en la fecha de decision a partir de las acciones en
circulacion, que si vienen. El contrato lo contempla (`FUNDAMENTALES_AL_MENOS_UNA`).

## Estado

**No se ha podido ejecutar.** El entorno de desarrollo bloquea `sec.gov` por
politica de red, asi que esto esta escrito contra la documentacion de la API y
probado contra respuestas grabadas. El parseo —donde de verdad se puede uno
equivocar— esta en funciones puras con tests. La primera ejecucion de verdad es
la que dira si los conceptos XBRL elegidos cubren a las 33 empresas del universo;
`estrategia diagnostico` existe para que esa vez devuelva una lista y no una traza.

La SEC exige identificarse en el `User-Agent` con algo que permita contactar, y
pide no pasar de unas diez peticiones por segundo.
"""

from __future__ import annotations

import gzip
import json
import os
import time
import urllib.error
import urllib.request
import zlib
from datetime import date, datetime
from typing import Any

import pandas as pd

from ..config import Config
from ..errores import ErrorDatos
from .proveedor import Capacidades, ProveedorFundamentales

BASE_DATOS = "https://data.sec.gov"
BASE_WWW = "https://www.sec.gov"
VARIABLE_AGENTE = "SEC_USER_AGENT"

#: Formularios que se consideran ejercicio anual. `10-K/A` es una correccion; se
#: acepta porque tambien es una publicacion real con su propia fecha, y si llega
#: antes que ninguna otra para ese periodo, es lo que se supo.
FORMULARIOS_ANUALES = ("10-K", "10-K/A", "20-F", "40-F")

#: Minimo de dias para considerar que un periodo con fechas de inicio y fin es
#: un ejercicio completo. Un 10-K trae tambien magnitudes trimestrales, y sin
#: este filtro se colarian como si fueran anuales.
DIAS_MINIMOS_EJERCICIO = 300

#: Conceptos XBRL de cada magnitud, por orden de preferencia. Las empresas no
#: usan todas la misma etiqueta —la norma admite varias y cada una elige— asi
#: que se prueban en orden y gana la primera que traiga dato.
CONCEPTOS: dict[str, tuple[str, ...]] = {
    "ventas": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "ebit": ("OperatingIncomeLoss",),
    "amortizaciones": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ),
    "beneficio_neto": ("NetIncomeLoss", "ProfitLoss"),
    "patrimonio_neto": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "deuda_largo": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "deuda_corto": ("LongTermDebtCurrent", "ShortTermBorrowings"),
    "efectivo": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "flujo_operativo": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    "acciones": (
        "CommonStockSharesOutstanding",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
    # --- magnitudes opcionales de §14 -------------------------------------
    "beneficio_bruto": ("GrossProfit",),
    "activos_totales": ("Assets",),
    "activo_corriente": ("AssetsCurrent",),
    "pasivo_corriente": ("LiabilitiesCurrent",),
    "bpa": ("EarningsPerShareDiluted", "EarningsPerShareBasic"),
    # El gasto financiero tiene media docena de etiquetas y ninguna domina. Se
    # prueban en orden y, si no hay ninguna, la cobertura de intereses queda sin
    # calcular en lugar de inventarse.
    "gastos_financieros": (
        "InterestExpense",
        "InterestExpenseDebt",
        "InterestExpenseNonoperating",
        "InterestAndDebtExpense",
    ),
}

#: Magnitudes de balance: se declaran en un instante, sin fecha de inicio.
INSTANTANEAS = {
    "patrimonio_neto",
    "deuda_largo",
    "deuda_corto",
    "efectivo",
    "acciones",
    "activos_totales",
    "activo_corriente",
    "pasivo_corriente",
}


def _fecha(texto: Any) -> date | None:
    if not texto:
        return None
    try:
        return datetime.strptime(str(texto)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _es_ejercicio_completo(entrada: dict) -> bool:
    """Descarta las magnitudes trimestrales que vienen dentro de un 10-K."""
    inicio, fin = _fecha(entrada.get("start")), _fecha(entrada.get("end"))
    if inicio is None:
        return True  # magnitud de balance: no tiene duracion
    if fin is None:
        return False
    return (fin - inicio).days >= DIAS_MINIMOS_EJERCICIO


def primera_publicacion(hechos: dict, conceptos: tuple[str, ...]) -> dict[date, dict]:
    """Para cada cierre de ejercicio, la PRIMERA vez que se publico la cifra.

    Aqui esta el valor de esta fuente. Entre varias publicaciones del mismo
    periodo gana la de `filed` mas antiguo, que es la cifra tal y como se conocio
    entonces, antes de cualquier reexpresion posterior.

    Los conceptos se recorren en orden de preferencia **rellenando huecos**, y un
    ejercicio que ya tiene valor no se sobrescribe nunca. Esa segunda parte es
    la salvaguarda: garantiza que cada periodo sale de un solo concepto y que en
    los ejercicios donde dos etiquetas coexisten gana siempre la preferida, asi
    que no hay dos versiones de la misma cifra compitiendo.

    La primera version no rellenaba: se quedaba con el primer concepto que
    tuviera algo y descartaba el resto, para no mezclar etiquetas dentro de una
    serie. La intencion era buena y el efecto, malo. Apple declara sus ventas
    como `SalesRevenueNet` hasta 2017 y como
    `RevenueFromContractWithCustomerExcludingAssessedTax` desde entonces, porque
    la norma ASC 606 cambio la etiqueta. Con aquella regla salian **9 de 19
    ejercicios** y diez anos de historico desaparecian en silencio, que es peor
    que el problema que evitaba: el crecimiento de ventas a tres anos
    simplemente no se podia calcular y nadie sabia por que.

    Queda un riesgo real y conviene decirlo: en el ejercicio donde una norma
    sustituye a otra puede haber un escalon, porque las dos etiquetas no miden
    exactamente lo mismo. Es inherente al cambio contable, no al codigo, y
    `conceptos_por_magnitud()` permite verlo en lugar de suponerlo.
    """
    por_periodo: dict[date, dict] = {}
    for concepto in conceptos:
        bloque = hechos.get(concepto)
        if not bloque:
            continue
        for unidades in (bloque.get("units") or {}).values():
            for entrada in unidades:
                if entrada.get("form") not in FORMULARIOS_ANUALES:
                    continue
                if not _es_ejercicio_completo(entrada):
                    continue
                fin = _fecha(entrada.get("end"))
                presentado = _fecha(entrada.get("filed"))
                if fin is None or presentado is None or entrada.get("val") is None:
                    continue
                anterior = por_periodo.get(fin)
                # Un ejercicio que ya cubre un concepto mas preferido no se
                # toca. Dentro del mismo concepto, gana la publicacion mas
                # antigua, que es la cifra tal y como se conocio entonces.
                if anterior is not None and anterior["concepto"] != concepto:
                    continue
                if anterior is None or presentado < anterior["presentado"]:
                    por_periodo[fin] = {
                        "valor": float(entrada["val"]),
                        "presentado": presentado,
                        "concepto": concepto,
                        "expediente": entrada.get("accn"),
                    }
    return por_periodo


def conceptos_por_magnitud(hechos: dict) -> dict[str, dict[str, int]]:
    """Que etiqueta XBRL cubre cuantos ejercicios de cada magnitud.

    Sirve para ver de un vistazo si una serie esta cosida a partir de varias
    etiquetas —lo normal cuando hay un cambio de norma contable— y si el corte
    cae donde deberia. Lo usa `scripts/verify_sources.py`.
    """
    resumen: dict[str, dict[str, int]] = {}
    for magnitud, conceptos in CONCEPTOS.items():
        cuenta: dict[str, int] = {}
        for periodo in primera_publicacion(hechos, conceptos).values():
            cuenta[periodo["concepto"]] = cuenta.get(periodo["concepto"], 0) + 1
        if cuenta:
            resumen[magnitud] = cuenta
    return resumen


def _divide(numerador: float | None, denominador: float | None) -> float | None:
    if numerador is None or denominador in (None, 0):
        return None
    return numerador / denominador


def parsear_companyfacts(payload: dict, ticker: str, descargado: date) -> list[dict]:
    """Convierte `companyfacts` en filas del esquema del proyecto.

    Funcion pura y con tests: es lo unico de esta fuente que se puede validar sin
    red, y es donde estan los errores que importan.
    """
    facts = payload.get("facts") or {}
    hechos: dict[str, Any] = {}
    for espacio in ("us-gaap", "ifrs-full", "dei"):
        hechos.update(facts.get(espacio) or {})
    if not hechos:
        return []

    magnitudes = {
        nombre: primera_publicacion(hechos, conceptos) for nombre, conceptos in CONCEPTOS.items()
    }

    # Los periodos salen del conjunto de cierres vistos en las magnitudes de
    # resultados. Las de balance se buscan en ese mismo cierre.
    periodos: set[date] = set()
    for nombre in ("ventas", "ebit", "beneficio_neto"):
        periodos |= set(magnitudes[nombre])

    # La fecha de publicacion de la FILA es la mas tardia de las magnitudes que
    # la componen. Tomar la mas temprana dejaria ver una fila completa antes de
    # que existiera entera, que es sesgo de anticipacion por la puerta de atras.
    filas: list[dict] = []
    for fin_periodo in sorted(periodos):
        valores: dict[str, float | None] = {}
        presentaciones: list[date] = []
        for nombre, por_periodo in magnitudes.items():
            dato = por_periodo.get(fin_periodo)
            valores[nombre] = dato["valor"] if dato else None
            if dato:
                presentaciones.append(dato["presentado"])
        if not presentaciones:
            continue

        deuda_total = _suma(valores["deuda_largo"], valores["deuda_corto"])
        deuda_neta = None if deuda_total is None else deuda_total - (valores["efectivo"] or 0.0)
        ebitda = _suma(valores["ebit"], valores["amortizaciones"])
        fcl = (
            None
            if valores["flujo_operativo"] is None
            else valores["flujo_operativo"] - (valores["capex"] or 0.0)
        )

        filas.append(
            {
                "ticker": ticker,
                "fin_periodo": fin_periodo,
                "periodo": "anual",
                "fecha_publicacion": max(presentaciones),
                "origen_fecha_publicacion": "real_sec",
                # La afirmacion fuerte de esta fuente, y la unica del proyecto
                # que puede hacerla.
                "origen_pit": "capturado",
                "fecha_descarga": descargado,
                "roe": _divide(valores["beneficio_neto"], valores["patrimonio_neto"]),
                "margen_operativo": _divide(valores["ebit"], valores["ventas"]),
                "ventas": valores["ventas"],
                "flujo_caja_libre": fcl,
                "deuda_neta": deuda_neta,
                "ebitda": ebitda,
                "ebit": valores["ebit"],
                # La SEC publica cuentas, no cotizaciones: sin precio no hay EV.
                # El motor lo calcula en la fecha de decision con las acciones.
                "ev": None,
                "patrimonio_neto": valores["patrimonio_neto"],
                "acciones_en_circulacion": _acciones(
                    valores["acciones"], valores["beneficio_neto"], valores["bpa"]
                ),
                "divisa_reporte": "USD",
                "divisa_cotizacion": "USD",
                # --- magnitudes opcionales de §14 ------------------------
                "beneficio_neto": valores["beneficio_neto"],
                "beneficio_bruto": valores["beneficio_bruto"],
                "activos_totales": valores["activos_totales"],
                "deuda_total": deuda_total,
                "efectivo": valores["efectivo"],
                "bpa": valores["bpa"],
                "activo_corriente": valores["activo_corriente"],
                "pasivo_corriente": valores["pasivo_corriente"],
                # El gasto financiero se declara como numero positivo aunque en
                # las cuentas reste: la cobertura de intereses es EBIT partido
                # por el gasto, y un signo negativo la volveria del reves.
                "gastos_financieros": (
                    None
                    if valores["gastos_financieros"] is None
                    else abs(valores["gastos_financieros"])
                ),
            }
        )
    return filas


def _acciones(declaradas: float | None, beneficio: float | None, bpa: float | None) -> float | None:
    """Acciones en circulacion, deducidas del beneficio y el BPA.

    El concepto declarado no es de fiar, y el motivo merece contarse: McDonald's
    etiqueta `WeightedAverageNumberOfDilutedSharesOutstanding` con unidad
    `shares` y valor **716,4**, porque presenta sus cuentas en millones. XBRL no
    lo impide, asi que la misma etiqueta viene en unidades en unas empresas y en
    millones en otras.

    Tomarlo tal cual daba una capitalizacion un millon de veces menor y un PER
    de 0,0. No fallaba nada: la empresa aparecia sencillamente como la mas
    barata del mercado, que es el peor desenlace posible para un ranking.

    Beneficio partido por BPA es inmune a eso: el BPA esta por accion y el
    beneficio en moneda, asi que su cociente son acciones cualquiera que sea la
    escala con que se presenten las cuentas. Es la misma derivacion que se usa
    en la CVM, y da acciones medias ponderadas, no de cierre.

    El valor declarado queda de respaldo para cuando no hay BPA, y entonces se
    cree lo que dice la etiqueta porque no hay con que contrastarlo.
    """
    if beneficio not in (None, 0) and bpa not in (None, 0):
        return abs(beneficio) / abs(bpa)
    return declaradas


def _suma(a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


def parsear_mapa_cik(payload: Any) -> dict[str, str]:
    """Ticker -> CIK con diez digitos, desde `company_tickers.json`.

    El fichero es un objeto con claves numericas en texto, no una lista. El CIK
    va sin ceros a la izquierda y la API de `companyfacts` los exige, asi que se
    rellena aqui y no en cada llamada.
    """
    filas = payload.values() if isinstance(payload, dict) else payload
    mapa: dict[str, str] = {}
    for fila in filas:
        ticker = (fila.get("ticker") or "").strip().upper()
        cik = fila.get("cik_str")
        if ticker and cik is not None:
            mapa[ticker] = str(cik).zfill(10)
    return mapa


def _descomprimir(respuesta) -> str:
    """Devuelve el cuerpo de la respuesta como texto, descomprimiendo si toca.

    `urllib` anuncia que acepta gzip si se lo pones en la cabecera, pero **no
    descomprime la respuesta**: eso lo hacen `requests` y `httpx`, no la
    biblioteca estandar. El sintoma es un UnicodeDecodeError quejandose del byte
    0x8b en la posicion 1, que es la firma de gzip, y que no se parece en nada a
    "se me ha olvidado descomprimir".

    Se mantiene la cabecera en lugar de quitarla porque la SEC pide
    expresamente que se use compresion para no cargar sus servidores, y
    `companyfacts` de una empresa grande son varios megabytes.
    """
    crudo = respuesta.read()
    if respuesta.headers.get("Content-Encoding") == "gzip":
        crudo = gzip.decompress(crudo)
    elif respuesta.headers.get("Content-Encoding") == "deflate":
        crudo = zlib.decompress(crudo)
    return crudo.decode("utf-8")


class ProveedorSEC(ProveedorFundamentales):
    """Fundamentales de EE. UU. desde EDGAR."""

    nombre = "sec"

    def __init__(self, cfg: Config, agente: str | None = None) -> None:
        self._cfg = cfg
        self._agente = agente or os.environ.get(VARIABLE_AGENTE, "")
        self._mapa_cik: dict[str, str] | None = None
        self._cache: dict[str, dict] = {}

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("fundamentales",),
            anios_fundamentales=15,
            fechas_publicacion_reales=True,
            # La propiedad que la distingue de todas las demas fuentes del
            # proyecto: quedandose con la primera publicacion de cada periodo,
            # las cifras son las de entonces y no las reexpresadas a hoy.
            cifras_reexpresadas=False,
            incluye_deslistadas=False,
            mercados=("us",),
            necesita_clave=False,
            magnitudes=(
                "beneficio_neto",
                "beneficio_bruto",
                "activos_totales",
                "deuda_total",
                "efectivo",
                "bpa",
                "activo_corriente",
                "pasivo_corriente",
                "gastos_financieros",
            ),
            notas=(
                "Solo EE. UU. y solo ejercicios anuales (10-K).",
                "Unica fuente del proyecto que emite origen_pit: capturado.",
                "No da EV: la SEC publica cuentas, no cotizaciones.",
                "Exige identificarse en el User-Agent (SEC_USER_AGENT).",
            ),
        )

    def disponible(self) -> tuple[bool, str]:
        if not self._agente:
            return False, (
                f"la SEC exige identificarse. Exporta {VARIABLE_AGENTE} con algo "
                f'como "lalonja research tu@correo.com".'
            )
        return True, ""

    def _pedir(self, url: str) -> Any:
        ok, motivo = self.disponible()
        if not ok:
            raise ErrorDatos(motivo)

        peticion = urllib.request.Request(
            url, headers={"User-Agent": self._agente, "Accept-Encoding": "gzip, deflate"}
        )
        try:
            with urllib.request.urlopen(peticion, timeout=60) as respuesta:
                return json.loads(_descomprimir(respuesta))
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                raise ErrorDatos(
                    "la SEC ha devuelto 403: revisa el User-Agent, exige un contacto real"
                ) from exc
            if exc.code == 404:
                raise ErrorDatos(f"la SEC no conoce {url}") from exc
            if exc.code == 429:
                raise ErrorDatos(
                    "la SEC ha devuelto 429: se ha pasado el limite de peticiones"
                ) from exc
            raise ErrorDatos(f"la SEC ha respondido {exc.code} a {url}") from exc
        except urllib.error.URLError as exc:
            raise ErrorDatos(f"no se ha podido conectar con la SEC: {exc.reason}") from exc

    def cik_de(self, ticker: str) -> str | None:
        """El CIK de un ticker, con las excepciones de la configuracion.

        `company_tickers.json` apunta al emisor registrado HOY. Cuando una
        empresa se reorganiza, eso puede ser una entidad nueva sin historico:
        el ticker XOM resuelve a un CIK que solo ha presentado trimestrales,
        mientras los diecisiete ejercicios anuales estan en el de siempre.
        """
        excepcion = self._cfg.implementacion.cik_sec.get(ticker.upper())
        if excepcion:
            return excepcion.zfill(10)
        if self._mapa_cik is None:
            self._mapa_cik = parsear_mapa_cik(self._pedir(f"{BASE_WWW}/files/company_tickers.json"))
        return self._mapa_cik.get(ticker.upper())

    def ficha(self, ticker: str) -> dict:
        if ticker not in self._cache:
            cik = self.cik_de(ticker)
            if cik is None:
                self._cache[ticker] = {}
            else:
                try:
                    self._cache[ticker] = self._pedir(
                        f"{BASE_DATOS}/api/xbrl/companyfacts/CIK{cik}.json"
                    )
                except ErrorDatos:
                    # Un valor que no resuelve se queda fuera y sale en el
                    # diagnostico; no tumba una descarga entera.
                    self._cache[ticker] = {}
                # La SEC pide no pasar de unas diez peticiones por segundo.
                time.sleep(0.11)
        return self._cache[ticker]

    def fundamentales(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        hoy = date.today()
        filas: list[dict] = []
        for ticker in tickers:
            # Solo EE. UU.: pedirle a la SEC un valor espanol es gastar una
            # peticion para recibir un 404.
            if self._cfg.universo.mercado_de_ticker.get(ticker) != "us":
                continue
            payload = self.ficha(ticker)
            if not payload:
                continue
            for fila in parsear_companyfacts(payload, ticker, hoy):
                # Se filtra por fecha de publicacion y no por cierre de periodo:
                # lo que importa es cuando se supo, no a que ejercicio se refiere.
                if fila["fecha_publicacion"] <= fin:
                    filas.append(fila)
        return pd.DataFrame(filas)
