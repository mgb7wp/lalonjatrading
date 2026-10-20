"""Fuente B3: cotizaciones oficiales de la bolsa de Brasil (ficheros COTAHIST).

La B3 publica gratis y sin clave las "Series Historicas": un fichero de texto de
ancho fijo por ano (`COTAHIST_A{ano}.ZIP`, desde 1986; el del ano en curso se
actualiza cada sesion) con todas las negociaciones del dia.

Adaptado de Vibe-Trading (HKUDS, licencia MIT, `agent/src/br_data/cotahist.py`):
de alli salen las posiciones de cada campo y las reglas de lectura (dos
decimales implicitos, precio por `FATCOT` unidades, solo registros en reales).

## Para que sirve aqui, y para que no

Son precios **de cotizacion, sin ajustar** ni por dividendos ni por splits. Por
eso declara `precios_ajustados=False` y el enrutador no la acepta como respaldo:
rellenar con ella el hueco de una fuente ajustada convertiria cada dividendo en
una caida.

Lo que si da es la **referencia oficial** contra la que comprobar el bruto de
yfinance en Brasil (tarea M4): un escalon que no esta en la B3 es un error del
proveedor, como el historico de UGPA3.SA antes de 2021-06-28. La comparacion
esta en `scripts/verify_sources.py --fuente b3`.

## Lo que pesa

El fichero anual son decenas de megas comprimido y cientos sin comprimir,
porque trae todo lo negociado (opciones incluidas). Se lee en flujo y se queda
solo con el mercado al contado de los valores pedidos, pero cada ano es una
descarga entera: no es una fuente para pedir veinte anos a diario.

## Estado

**No se ha podido ejecutar**: el entorno de desarrollo no llega a la B3. El
parseo esta en funciones puras con tests sobre registros en el formato
publicado.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterable
from datetime import date

import pandas as pd

from ..config import Config
from ..errores import ErrorDatos
from .proveedor import Capacidades, ProveedorPrecios

BASE = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist"

#: Longitud de un registro y tipo de los que traen cotizaciones.
LONGITUD_REGISTRO = 245
TIPO_COTIZACION = "01"

#: `TPMERC` del mercado al contado (lote estandar). El fraccionario es el 020.
MERCADO_CONTADO = 10

#: Sufijo de Yahoo de los valores de la B3 en el universo.
SUFIJO = ".SA"


def _entero(campo: str) -> int | None:
    campo = campo.strip()
    return int(campo) if campo.isdigit() else None


def _fecha(campo: str) -> date | None:
    campo = campo.strip()
    if len(campo) != 8 or not campo.isdigit():
        return None
    try:
        return date(int(campo[:4]), int(campo[4:6]), int(campo[6:8]))
    except ValueError:
        return None


def parsear_registro(linea: str) -> dict | None:
    """Un registro de cotizacion de COTAHIST, o None si no lo es o esta roto.

    Posiciones (base 0, extremo excluido) del formato publicado por la B3: DATA
    2-10, CODBDI 10-12, CODNEG 12-24, TPMERC 24-27, MODREF 52-56, PREABE 56-69,
    PREMAX 69-82, PREMIN 82-95, PREULT 108-121, QUATOT 152-170, FATCOT 210-217.
    Los precios llevan dos decimales implicitos y van por `FATCOT` acciones.
    """
    if len(linea) < LONGITUD_REGISTRO or not linea.startswith(TIPO_COTIZACION):
        return None
    fecha = _fecha(linea[2:10])
    if fecha is None:
        return None
    # El historico antiguo trae monedas anteriores al real: esas no se leen como
    # si fueran reales.
    if linea[52:56].strip() != "R$":
        return None
    factor = _entero(linea[210:217])
    precios = [_entero(linea[a:b]) for a, b in ((56, 69), (69, 82), (82, 95), (108, 121))]
    if not factor or any(p is None or p <= 0 for p in precios):
        return None
    apertura, maximo, minimo, cierre = (p / 100.0 / factor for p in precios)
    return {
        "fecha": fecha,
        "codneg": linea[12:24].strip(),
        "tpmerc": _entero(linea[24:27]),
        "apertura": apertura,
        "maximo": maximo,
        "minimo": minimo,
        "cierre": cierre,
        "volumen": float(_entero(linea[152:170]) or 0),
    }


def filas_de_cotahist(
    lineas: Iterable[str], tickers: Iterable[str], inicio: date, fin: date
) -> list[dict]:
    """Filas del contrato de precios para los valores pedidos, del contado.

    `cierre` y `cierre_bruto` son el mismo numero: es el precio de cotizacion,
    sin ajustar. Ver el docstring del modulo.
    """
    codigos = {t.removesuffix(SUFIJO): t for t in tickers if t.endswith(SUFIJO)}
    salida: list[dict] = []
    for linea in lineas:
        registro = parsear_registro(linea.rstrip("\r\n"))
        if registro is None or registro["tpmerc"] != MERCADO_CONTADO:
            continue
        ticker = codigos.get(registro["codneg"])
        if ticker is None or not inicio <= registro["fecha"] <= fin:
            continue
        salida.append(
            {
                "fecha": registro["fecha"],
                "ticker": ticker,
                "apertura": registro["apertura"],
                "maximo": registro["maximo"],
                "minimo": registro["minimo"],
                "cierre": registro["cierre"],
                "cierre_bruto": registro["cierre"],
                "volumen": registro["volumen"],
            }
        )
    return salida


def lineas_de_zip(ruta_o_bytes) -> Iterable[str]:
    """Las lineas de texto de un ZIP de COTAHIST, leidas en flujo (Latin-1)."""
    origen = io.BytesIO(ruta_o_bytes) if isinstance(ruta_o_bytes, bytes) else ruta_o_bytes
    with zipfile.ZipFile(origen) as archivo:
        for info in archivo.infolist():
            if info.is_dir():
                continue
            with archivo.open(info) as crudo:
                yield from io.TextIOWrapper(crudo, encoding="latin-1", newline="")


class ProveedorB3(ProveedorPrecios):
    """Cotizaciones oficiales sin ajustar de la B3."""

    nombre = "b3"

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self.avisos: list[str] = []

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("precios",),
            mercados=("br",),
            precios_ajustados=False,
            notas=(
                "Precios de cotizacion SIN ajustar por dividendos ni splits: sirven "
                "para comprobar el bruto de otra fuente, no para operar.",
                "Cada ano es un fichero de decenas de megas.",
            ),
        )

    def _descargar(self, ano: int, destino) -> None:
        url = f"{BASE}/COTAHIST_A{ano}.ZIP"
        try:
            with urllib.request.urlopen(url, timeout=600) as respuesta:
                shutil.copyfileobj(respuesta, destino)
        except urllib.error.HTTPError as exc:
            raise ErrorDatos(f"la B3 ha respondido {exc.code} al fichero de {ano}") from exc
        except urllib.error.URLError as exc:
            raise ErrorDatos(f"no se ha podido conectar con la B3: {exc.reason}") from exc

    def precios(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        filas: list[dict] = []
        for ano in range(inicio.year, fin.year + 1):
            # A disco y no a memoria: el fichero anual pesa decenas de megas.
            with tempfile.TemporaryFile() as temporal:
                self._descargar(ano, temporal)
                temporal.seek(0)
                filas.extend(filas_de_cotahist(lineas_de_zip(temporal), tickers, inicio, fin))
        pedidos = {t for t in tickers if t.endswith(SUFIJO)}
        sin_precios = sorted(pedidos - {f["ticker"] for f in filas})
        if sin_precios:
            self.avisos.append(
                f"[b3/precios] {len(sin_precios)} valores sin cotizaciones: "
                f"{', '.join(sin_precios)}"
            )
        return pd.DataFrame(filas)

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        raise ErrorDatos("la B3 no sirve divisas en este proyecto: usa 'bce'")

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        return dict.fromkeys(tickers)
