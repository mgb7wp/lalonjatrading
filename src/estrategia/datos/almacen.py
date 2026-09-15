"""Almacen de datos y vista puntual a una fecha.

Aqui esta la salvaguarda principal contra el sesgo de anticipacion. El resto de
la app nunca recibe una serie entera: recibe una `VistaPuntual`, construida con
una fecha de corte, que no devuelve nada posterior a esa fecha.

La vista se apoya en series ya indexadas y con los indicadores precalculados
(`indicadores.py`), asi que consultar es buscar una posicion, no filtrar un
DataFrame. El corte se aplica sobre esa posicion: `serie_hasta` devuelve el
indice de la ultima sesion en o antes del corte, y todo lo que se lee va por ahi.
Los indicadores son ventanas hacia atras, de modo que la posicion `i` solo
depende de datos en posiciones `<= i`.

La vista ademas anota la fecha maxima que ha tocado, para que los tests puedan
afirmar no solo que el resultado es correcto, sino que para calcularlo no se
miro ni un dia mas alla del corte.

Un limite honesto que conviene decir en voz alta: el almacen fija *cuando* se
conocio un dato, no *que version* de ese dato se conocia. Los fundamentales de
un proveedor gratuito vienen reexpresados a dia de hoy, y las reexpresiones no
son neutras. Por eso cada fila lleva `origen_pit`: `capturado` si viene de una
foto tomada en su momento, `reconstruido` si se dedujo despues. En un backtest
de la version 1 sera `reconstruido` casi siempre, y el informe publica ese
porcentaje en lugar de disimularlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ..errores import ErrorAnticipacion, ErrorDatos
from ..indicadores import SerieFX, SerieValor, construir_fx, construir_series


@dataclass
class Instantanea:
    """Un conjunto de datos coherente, con su fecha de descarga.

    Yahoo revisa hacia atras los precios ajustados, asi que el mismo backtest da
    numeros distintos segun el dia en que se bajaron los datos. Guardar la fecha
    de descarga y estamparla en el informe es lo que permite reproducir.
    """

    precios: pd.DataFrame
    fundamentales: pd.DataFrame
    fx: pd.DataFrame
    sectores: dict[str, str | None] = field(default_factory=dict)
    fecha_descarga: date | None = None
    origen: str = "desconocido"

    _series: dict[str, SerieValor] = field(default_factory=dict, repr=False)
    _fx: dict[str, SerieFX] = field(default_factory=dict, repr=False)
    _fund: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)
    _preparada: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self.precios = _normalizar_precios(self.precios)
        self.fundamentales = _normalizar_fundamentales(self.fundamentales)
        self.fx = _normalizar_fx(self.fx)

    def preparar(self, cfg) -> "Instantanea":
        """Precalcula indicadores e indices. Se hace una vez por backtest."""
        self._series = construir_series(self.precios, cfg)
        self._fx = construir_fx(self.fx)
        self._fund = (
            {str(t): g.reset_index(drop=True)
             for t, g in self.fundamentales.groupby("ticker", sort=False)}
            if not self.fundamentales.empty
            else {}
        )
        self._preparada = True
        return self

    @property
    def series(self) -> dict[str, SerieValor]:
        if not self._preparada:
            raise ErrorDatos("la instantanea no esta preparada; llama a preparar(cfg)")
        return self._series

    @property
    def rango_precios(self) -> tuple[date, date]:
        if self.precios.empty:
            raise ErrorDatos("la instantanea no tiene precios")
        return self.precios["fecha"].min(), self.precios["fecha"].max()

    def vista(self, fecha_corte: date) -> "VistaPuntual":
        """La vista de lo que se conocia al cierre de `fecha_corte`."""
        if not self._preparada:
            raise ErrorDatos("la instantanea no esta preparada; llama a preparar(cfg)")
        return VistaPuntual(self, fecha_corte)

    # -- persistencia ------------------------------------------------------

    def guardar(self, directorio: Path) -> None:
        directorio = Path(directorio)
        directorio.mkdir(parents=True, exist_ok=True)
        self.precios.to_parquet(directorio / "precios.parquet", index=False)
        self.fundamentales.to_parquet(directorio / "fundamentales.parquet", index=False)
        self.fx.to_parquet(directorio / "fx.parquet", index=False)
        pd.DataFrame(
            {"ticker": list(self.sectores), "sector": list(self.sectores.values())}
        ).to_parquet(directorio / "sectores.parquet", index=False)
        pd.Series(
            {"fecha_descarga": str(self.fecha_descarga or ""), "origen": self.origen}
        ).to_json(directorio / "manifiesto.json")

    @classmethod
    def cargar(cls, directorio: Path) -> "Instantanea":
        directorio = Path(directorio)
        if not (directorio / "precios.parquet").is_file():
            raise ErrorDatos(
                f"no hay datos en {directorio}. Ejecuta primero `estrategia datos`."
            )
        sectores_df = pd.read_parquet(directorio / "sectores.parquet")
        manifiesto = {}
        if (directorio / "manifiesto.json").is_file():
            manifiesto = pd.read_json(
                directorio / "manifiesto.json", typ="series"
            ).to_dict()
        descarga = str(manifiesto.get("fecha_descarga") or "")
        return cls(
            precios=pd.read_parquet(directorio / "precios.parquet"),
            fundamentales=pd.read_parquet(directorio / "fundamentales.parquet"),
            fx=pd.read_parquet(directorio / "fx.parquet"),
            sectores=dict(zip(sectores_df["ticker"], sectores_df["sector"])),
            fecha_descarga=date.fromisoformat(descarga) if descarga else None,
            origen=str(manifiesto.get("origen", "desconocido")),
        )


class VistaPuntual:
    """Lo que se sabia en una fecha. No devuelve nada posterior."""

    __slots__ = ("_inst", "_corte", "_corte_ord", "_maxima")

    def __init__(self, instantanea: Instantanea, fecha_corte: date) -> None:
        self._inst = instantanea
        self._corte = fecha_corte
        self._corte_ord = fecha_corte.toordinal()
        self._maxima: date | None = None

    @property
    def fecha_corte(self) -> date:
        return self._corte

    @property
    def fecha_maxima_tocada(self) -> date | None:
        """La fecha mas alta leida hasta ahora. La usan los tests de sesgo."""
        return self._maxima

    def _anotar(self, fecha: date) -> None:
        if fecha > self._corte:  # pragma: no cover - red de seguridad
            raise ErrorAnticipacion(
                f"se ha leido un dato de {fecha}, posterior al corte {self._corte}"
            )
        if self._maxima is None or fecha > self._maxima:
            self._maxima = fecha

    # -- precios -----------------------------------------------------------

    def serie(self, ticker: str) -> SerieValor | None:
        return self._inst.series.get(ticker)

    def posicion_hasta(self, ticker: str) -> int:
        """Indice de la ultima sesion en o antes del corte. -1 si no hay."""
        serie = self.serie(ticker)
        if serie is None:
            return -1
        i = serie.posicion(self._corte)
        if i >= 0:
            self._anotar(serie.fechas[i])
        return i

    def precios(self, ticker: str, sesiones: int | None = None) -> pd.DataFrame:
        """Historico hasta el corte como DataFrame. Comodo, pero lento.

        El bucle del backtest no lo usa: va por `serie()` y posiciones. Se
        mantiene para el panel, los informes y los tests, donde la claridad
        importa mas que la velocidad.
        """
        serie = self.serie(ticker)
        i = self.posicion_hasta(ticker)
        if serie is None or i < 0:
            return pd.DataFrame(
                columns=["fecha", "ticker", "apertura", "maximo", "minimo",
                         "cierre", "cierre_bruto", "volumen"]
            )
        desde = 0 if sesiones is None else max(0, i + 1 - sesiones)
        return pd.DataFrame(
            {
                "fecha": serie.fechas[desde : i + 1],
                "ticker": ticker,
                "apertura": serie.apertura[desde : i + 1],
                "maximo": serie.maximo[desde : i + 1],
                "minimo": serie.minimo[desde : i + 1],
                "cierre": serie.cierre[desde : i + 1],
                "cierre_bruto": serie.cierre_bruto[desde : i + 1],
                "volumen": serie.volumen[desde : i + 1],
            }
        )

    def posicion_exacta(self, ticker: str, fecha: date) -> int:
        """Indice de esa sesion concreta, o -1. Nunca devuelve una futura."""
        if fecha > self._corte:
            raise ErrorAnticipacion(
                f"se ha pedido {ticker} en {fecha}, posterior al corte {self._corte}"
            )
        serie = self.serie(ticker)
        if serie is None:
            return -1
        i = serie.posicion_exacta(fecha)
        if i >= 0:
            self._anotar(fecha)
        return i

    def precio_en(self, ticker: str, fecha: date) -> pd.Series | None:
        """La fila OHLCV de una sesion concreta, si existe y no es futura."""
        i = self.posicion_exacta(ticker, fecha)
        if i < 0:
            return None
        serie = self.serie(ticker)
        assert serie is not None
        return pd.Series(
            {
                "fecha": serie.fechas[i],
                "apertura": float(serie.apertura[i]),
                "maximo": float(serie.maximo[i]),
                "minimo": float(serie.minimo[i]),
                "cierre": float(serie.cierre[i]),
                "cierre_bruto": float(serie.cierre_bruto[i]),
                "volumen": float(serie.volumen[i]),
            }
        )

    def tickers_con_precio(self) -> list[str]:
        return sorted(
            t for t in self._inst.series if self._inst.series[t].posicion(self._corte) >= 0
        )

    # -- fundamentales -----------------------------------------------------

    def fundamentales(self, ticker: str) -> pd.DataFrame:
        """Fundamentales ya publicados a la fecha de corte.

        El filtro es por `fecha_publicacion`, no por fin de periodo: un trimestre
        cerrado en marzo no se conoce hasta que se publica.
        """
        df = self._inst._fund.get(ticker)
        if df is None or df.empty:
            return pd.DataFrame()
        recorte = df[df["fecha_publicacion"] <= self._corte]
        if not recorte.empty:
            self._anotar(recorte["fecha_publicacion"].max())
        return recorte.reset_index(drop=True)

    def ultimo_fundamental(self, ticker: str, periodo: str = "anual") -> pd.Series | None:
        df = self.fundamentales(ticker)
        if df.empty:
            return None
        df = df[df["periodo"] == periodo]
        return None if df.empty else df.iloc[-1]

    # -- divisas -----------------------------------------------------------

    def fx(self, divisa: str, fecha: date, divisa_base: str = "EUR") -> float:
        """Tipo de cambio `divisa -> divisa_base` en esa fecha.

        Si no hay cotizacion ese dia (festivo, fin de semana) se arrastra la
        ultima conocida, que es lo que haria cualquiera al valorar.
        """
        if divisa == divisa_base:
            return 1.0
        if fecha > self._corte:
            raise ErrorAnticipacion(
                f"se ha pedido el cambio de {divisa} en {fecha}, posterior al "
                f"corte {self._corte}"
            )
        serie = self._inst._fx.get(divisa)
        if serie is None:
            raise ErrorDatos(f"no hay tipo de cambio de {divisa}")
        tasa = serie.tasa_en(fecha)
        if tasa is None:
            raise ErrorDatos(f"no hay tipo de cambio de {divisa} en o antes de {fecha}")
        self._anotar(fecha)
        # Se guarda EUR -> divisa; para pasar de divisa a EUR se invierte.
        return 1.0 / tasa

    def fx_decision(
        self, divisa: str, fecha: date, usar_dia_anterior: bool, divisa_base: str = "EUR"
    ) -> float:
        """Cambio para decidir y dimensionar.

        Los tipos de referencia del BCE se publican por la tarde, asi que
        decidir a la hora del cierre indio con el cambio de hoy seria usar un
        dato que aun no existe. Para decidir se usa el de la vispera; el del
        propio dia se reserva para valorar la cartera al cierre.
        """
        if divisa == divisa_base:
            return 1.0
        objetivo = fecha - timedelta(days=1) if usar_dia_anterior else fecha
        return self.fx(divisa, objetivo, divisa_base)

    # -- sectores ----------------------------------------------------------

    def sector(self, ticker: str) -> str | None:
        return self._inst.sectores.get(ticker)


# --------------------------------------------------------------------------
# Normalizacion
# --------------------------------------------------------------------------


def _a_fecha(serie: pd.Series) -> pd.Series:
    return pd.to_datetime(serie).dt.date


def _normalizar_precios(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["fecha"] = _a_fecha(df["fecha"])
    return df.sort_values(["ticker", "fecha"]).reset_index(drop=True)


def _normalizar_fundamentales(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for col in ("fin_periodo", "fecha_publicacion", "fecha_descarga"):
        if col in df.columns:
            df[col] = _a_fecha(df[col])
    return df.sort_values(["ticker", "fin_periodo"]).reset_index(drop=True)


def _normalizar_fx(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["fecha"] = _a_fecha(df["fecha"])
    return df.sort_values(["divisa", "fecha"]).reset_index(drop=True)
