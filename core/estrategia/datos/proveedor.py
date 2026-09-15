"""Interfaz de las fuentes de datos.

Precios y fundamentales se piden por separado a proposito. El documento ya
contempla cambiar de proveedor fundamental (`ampliacion_futura: eodhd`) sin
tocar el de precios, y ademas tienen longitudes de historico, cadencias y modos
de fallar muy distintos: una sola interfaz para ambos obligaria a inventar la
mitad que un proveedor no ofrece.

Columnas que toda fuente de precios debe devolver, en divisa local:

- `cierre`, `apertura`, `maximo`, `minimo`: OHLC **ajustado** por dividendos y
  splits. Los cuatro, no solo el cierre: calcular el ATR con maximos y minimos
  en bruto y las medias con el cierre ajustado convierte cada dividendo en un
  hueco fantasma y deja el ATR sin sentido.
- `cierre_bruto`, `volumen`: sin ajustar. El volumen negociado se mide con
  precio bruto x volumen bruto, porque el volumen no se ajusta por dividendos y
  mezclarlo con el precio ajustado subestima la liquidez historica.
- `fuente`: de donde salio la fila. La estampa el enrutador, no la fuente.

Las **capacidades** las declara cada fuente y no son documentacion: el informe
las lee para saber de que tiene que avisar. Hoy el aviso del historico corto esta
atado a un parametro de configuracion escrito a mano; leyendolo de aqui, el dia
que entre una fuente con datos point-in-time de verdad el aviso deja de
dispararse solo, sin que nadie tenga que acordarse de actualizar un texto.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

#: Tipos de dato que una fuente puede servir. El enrutador asigna una dueña a
#: cada uno.
TIPOS_DE_DATO = ("precios", "fundamentales", "divisas", "sectores")

COLUMNAS_PRECIOS = [
    "fecha",
    "ticker",
    "apertura",
    "maximo",
    "minimo",
    "cierre",
    "cierre_bruto",
    "volumen",
]

COLUMNAS_FUNDAMENTALES = [
    "ticker",
    "fin_periodo",
    "periodo",
    "fecha_publicacion",
    "origen_fecha_publicacion",
    "origen_pit",
    "fecha_descarga",
    "roe",
    "margen_operativo",
    "ventas",
    "flujo_caja_libre",
    "deuda_neta",
    "ebitda",
    "ebit",
    "ev",
    "patrimonio_neto",
    # El EV se calcula en la fecha de decision a partir de estas tres, porque el
    # EBIT es anual y mira hacia atras pero la valoracion debe reflejar el precio
    # de hoy. Las divisas van juntas porque los estados financieros vienen en la
    # divisa en que REPORTA la empresa, que no siempre es la de su cotizacion.
    "acciones_en_circulacion",
    "divisa_reporte",
    "divisa_cotizacion",
]

COLUMNAS_FX = ["fecha", "divisa", "tasa"]


@dataclass(frozen=True, slots=True)
class Capacidades:
    """Lo que una fuente sabe hacer, en sus propias palabras.

    El informe genera sus avisos a partir de esto, asi que rellenarlo con
    optimismo no hace que el sistema mejore: hace que deje de avisar de sus
    propios limites.
    """

    tipos: tuple[str, ...]
    anios_fundamentales: int | None = None
    fechas_publicacion_reales: bool = False
    cifras_reexpresadas: bool = True
    incluye_deslistadas: bool = False
    mercados: tuple[str, ...] | None = None
    necesita_clave: bool = False
    notas: tuple[str, ...] = field(default_factory=tuple)

    def sirve(self, tipo: str) -> bool:
        return tipo in self.tipos


class Fuente(ABC):
    """Base de toda fuente de datos."""

    nombre: str = "abstracta"

    @property
    @abstractmethod
    def capacidades(self) -> Capacidades:
        """Que tipos sirve y con que limitaciones."""

    def disponible(self) -> tuple[bool, str]:
        """Si la fuente se puede usar ahora mismo, y por que no si no.

        Sirve para que la falta de una clave de API sea un mensaje claro al
        arrancar y no un error a mitad de una descarga de media hora.
        """
        return True, ""


class ProveedorPrecios(Fuente):
    """Da series OHLCV en divisa local."""

    @abstractmethod
    def precios(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        """OHLCV por ticker y fecha, con las columnas de `COLUMNAS_PRECIOS`."""

    @abstractmethod
    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        """Tipos de cambio diarios `EUR -> divisa`.

        Se guardan siempre en un solo sentido y se invierten al leer, para que
        no haya dos convenios circulando por el codigo.
        """

    @abstractmethod
    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        """Sector que la fuente asigna a cada ticker, sin traducir."""


class ProveedorFundamentales(Fuente):
    """Da estados financieros con su fecha de publicacion."""

    @abstractmethod
    def fundamentales(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        """Fundamentales por ticker y periodo, segun `COLUMNAS_FUNDAMENTALES`.

        `fecha_publicacion` es obligatoria. Si la fuente no la ofrece, quien
        implemente esto debe estimarla a partir del cierre del periodo mas el
        retraso de `datos.retraso_por_mercado`, decirlo en
        `origen_fecha_publicacion` y marcar `origen_pit` como `reconstruido`.
        """


class Proveedor(ProveedorPrecios, ProveedorFundamentales, ABC):
    """Una fuente que cubre precios y fundamentales a la vez."""

    nombre: str = "abstracto"
