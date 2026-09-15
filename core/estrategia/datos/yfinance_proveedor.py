"""Proveedor real, sobre yfinance.

No se puede probar en el entorno donde se ha desarrollado la app, porque su
politica de red no deja salir a Yahoo Finance. Por eso el codigo se mantiene lo
mas simple posible y todo lo que se puede validar sin red (el ajuste de precios,
la estimacion de fechas de publicacion, el calculo de ratios) esta separado en
funciones puras con tests propios.

Dos decisiones que no son evidentes y que cambian los resultados:

1. Se descarga con `auto_adjust=False` y el ajuste se aplica a mano a los
   cuatro precios con el factor `Adj Close / Close`. Usar `Close` ajustado con
   `High`/`Low` en bruto —que es lo que sale por defecto si uno no se fija—
   convierte cada dividendo y cada split en un hueco inventado y deja el ATR sin
   sentido. Asi ademas quedan disponibles los precios brutos.
2. El volumen negociado se calcula con precio BRUTO x volumen bruto. Yahoo no
   ajusta el volumen por dividendos, asi que multiplicarlo por el precio
   ajustado subestima la liquidez de los anos antiguos justo donde el filtro de
   liquidez decide.

Limitaciones del proveedor gratuito, que el informe repite porque condicionan
lo que se puede concluir: unos cuatro ejercicios de fundamentales, sin fecha de
publicacion, con las cifras ya reexpresadas a dia de hoy, y sin las empresas que
dejaron de cotizar.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd

from ..config import Config
from ..errores import ErrorDatos
from .proveedor import Capacidades, Proveedor


def ajustar_ohlc(bruto: pd.DataFrame) -> pd.DataFrame:
    """Aplica el factor de ajuste a los cuatro precios, no solo al cierre.

    Espera las columnas de Yahoo (`Open`, `High`, `Low`, `Close`, `Adj Close`,
    `Volume`) y devuelve las columnas del proyecto.
    """
    faltan = {"Open", "High", "Low", "Close", "Adj Close", "Volume"} - set(bruto.columns)
    if faltan:
        raise ErrorDatos(f"faltan columnas en los datos de precios: {sorted(faltan)}")

    df = bruto.copy()
    cierre = df["Close"].replace(0.0, pd.NA)
    factor = (df["Adj Close"] / cierre).astype(float).fillna(1.0)
    return pd.DataFrame(
        {
            "apertura": df["Open"].astype(float) * factor,
            "maximo": df["High"].astype(float) * factor,
            "minimo": df["Low"].astype(float) * factor,
            "cierre": df["Adj Close"].astype(float),
            "cierre_bruto": df["Close"].astype(float),
            "volumen": df["Volume"].astype(float),
        }
    )


def estimar_fecha_publicacion(
    fin_periodo: date, mercado_id: str, cfg: Config, periodo: str
) -> date:
    """Cuando se supone conocido un periodo si el proveedor no lo dice."""
    dias = cfg.reglas.datos.retraso(mercado_id, "trimestral" if periodo == "trimestral" else "anual")
    return fin_periodo + timedelta(days=dias)


def con_reintentos(fn, intentos: int = 4, espera_inicial: float = 2.0):
    """Ejecuta algo que sale a la red, reintentando con espera creciente.

    Yahoo limita por volumen y falla de forma intermitente; 140 tickers en una
    tirada lo tocan con facilidad. Reintentar con espera creciente convierte una
    descarga fallida en una descarga lenta, que es mucho mejor resultado.
    """
    espera = espera_inicial
    ultimo: Exception | None = None
    for intento in range(intentos):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - se reintenta cualquier fallo de red
            ultimo = exc
            if intento == intentos - 1:
                break
            time.sleep(espera)
            espera *= 2
    raise ErrorDatos(f"fallo tras {intentos} intentos: {ultimo}") from ultimo


def _primera_fila(df: pd.DataFrame | None, *nombres: str) -> pd.Series | None:
    """Primera fila cuyo indice coincide con alguno de los nombres dados.

    Los estados financieros de Yahoo no usan siempre la misma etiqueta para el
    mismo concepto, asi que se prueban varias.
    """
    if df is None or df.empty:
        return None
    for nombre in nombres:
        if nombre in df.index:
            return df.loc[nombre]
    return None


class ProveedorYFinance(Proveedor):
    """Precios, divisas y fundamentales desde Yahoo Finance."""

    nombre = "yfinance"

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._info: dict[str, dict] = {}

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("precios", "fundamentales", "divisas", "sectores"),
            anios_fundamentales=self._cfg.reglas.proveedor_datos.fundamentales_anos_disponibles,
            # Yahoo no publica la fecha real en que se presentaron las cuentas,
            # asi que hay que estimarla con el retraso configurado.
            fechas_publicacion_reales=False,
            # Y las cifras que devuelve estan reexpresadas a dia de hoy, que no
            # es lo que se conocia entonces.
            cifras_reexpresadas=True,
            incluye_deslistadas=False,
            mercados=tuple(self._cfg.reglas.mercados_por_id),
            necesita_clave=False,
            notas=(
                "El historico fundamental es corto: el crecimiento de ventas a "
                "tres anos necesita cuatro ejercicios publicados, asi que la "
                "estrategia no puede operar hasta que llega el cuarto.",
            ),
        )

    def info(self, ticker: str) -> dict:
        """Ficha del valor, cacheada.

        Son 140 llamadas lentas y con limite de volumen, y hacen falta dos veces
        —para el sector y para las divisas—, asi que se piden una sola vez.
        """
        if ticker not in self._info:
            try:
                import yfinance as yf

                self._info[ticker] = con_reintentos(lambda: yf.Ticker(ticker).info) or {}
            except Exception:
                # Una ficha que no se puede leer no tumba la ejecucion: el valor
                # se quedara fuera por sector desconocido y saldra en el
                # diagnostico.
                self._info[ticker] = {}
        return self._info[ticker]

    # -- precios -----------------------------------------------------------

    def precios(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        import yfinance as yf

        if not tickers:
            return pd.DataFrame()

        crudo = con_reintentos(
            lambda: yf.download(
                tickers=tickers,
                start=inicio,
                end=fin + timedelta(days=1),
                auto_adjust=False,
                actions=False,
                progress=False,
                group_by="ticker",
                threads=True,
            )
        )
        if crudo is None or crudo.empty:
            raise ErrorDatos(
                "yfinance no ha devuelto precios. Comprueba la conexion y los tickers."
            )

        marco: list[pd.DataFrame] = []
        for ticker in tickers:
            try:
                bruto = crudo[ticker] if len(tickers) > 1 else crudo
            except KeyError:
                continue
            bruto = bruto.dropna(how="all")
            if bruto.empty:
                continue
            ajustado = ajustar_ohlc(bruto)
            ajustado.insert(0, "ticker", ticker)
            ajustado.insert(0, "fecha", pd.to_datetime(bruto.index).date)
            marco.append(ajustado.reset_index(drop=True))

        if not marco:
            raise ErrorDatos("ningun ticker ha devuelto precios utilizables")
        return pd.concat(marco, ignore_index=True)

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        import yfinance as yf

        pares = {
            d: self._cfg.implementacion.divisas.get(d)
            for d in divisas
            if d != self._cfg.reglas.cartera.divisa_base
        }
        pares = {d: p for d, p in pares.items() if p}
        if not pares:
            return pd.DataFrame(columns=["fecha", "divisa", "tasa"])

        crudo = con_reintentos(
            lambda: yf.download(
                tickers=list(pares.values()),
                start=inicio,
                end=fin + timedelta(days=1),
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=True,
            )
        )
        filas: list[pd.DataFrame] = []
        for divisa, par in pares.items():
            try:
                serie = crudo[par]["Close"] if len(pares) > 1 else crudo["Close"]
            except KeyError:
                continue
            serie = serie.dropna()
            filas.append(
                pd.DataFrame(
                    {
                        "fecha": pd.to_datetime(serie.index).date,
                        "divisa": divisa,
                        "tasa": serie.astype(float).to_numpy(),
                    }
                )
            )
        if not filas:
            raise ErrorDatos("no se ha podido descargar ningun tipo de cambio")
        return pd.concat(filas, ignore_index=True)

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        # Un sector que no se puede leer se queda como desconocido, y
        # `sectores.py` rechaza el valor en lugar de colarlo.
        return {t: self.info(t).get("sector") for t in tickers}

    # -- fundamentales -----------------------------------------------------

    def fundamentales(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        import yfinance as yf

        filas: list[dict] = []
        hoy = date.today()

        for ticker in tickers:
            mercado_id = self._cfg.universo.mercado_de_ticker.get(ticker)
            if mercado_id is None:
                continue
            try:
                t = yf.Ticker(ticker)
                resultados = t.income_stmt
                balance = t.balance_sheet
                caja = t.cashflow
            except Exception:
                continue
            if resultados is None or resultados.empty:
                continue

            ventas_f = _primera_fila(resultados, "Total Revenue", "Operating Revenue")
            ebit_f = _primera_fila(resultados, "EBIT", "Operating Income")
            ebitda_f = _primera_fila(resultados, "EBITDA", "Normalized EBITDA")
            neto_f = _primera_fila(resultados, "Net Income", "Net Income Common Stockholders")
            patrimonio_f = _primera_fila(
                balance, "Stockholders Equity", "Total Equity Gross Minority Interest"
            )
            deuda_f = _primera_fila(balance, "Total Debt", "Net Debt")
            efectivo_f = _primera_fila(
                balance, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"
            )
            flujo_f = _primera_fila(caja, "Free Cash Flow")
            # Acciones a cierre del periodo: es un dato del balance, o sea
            # puntual, no el numero de acciones de hoy. Con el se calcula el EV
            # en la fecha de decision.
            acciones_f = _primera_fila(
                balance, "Ordinary Shares Number", "Share Issued",
                "Common Stock Shares Outstanding",
            )

            ficha = self.info(ticker)
            # Los estados financieros vienen en la divisa en que REPORTA la
            # empresa, que no siempre es la de su cotizacion. Multiplicar
            # acciones por un precio en otra divisa da un EV sin sentido, asi
            # que se guardan las dos y quien calcule el ratio decide.
            divisa_reporte = ficha.get("financialCurrency")
            divisa_cotizacion = ficha.get("currency")

            for columna in resultados.columns:
                fin_periodo = pd.Timestamp(columna).date()
                publicacion = estimar_fecha_publicacion(
                    fin_periodo, mercado_id, self._cfg, "anual"
                )
                ventas = _valor(ventas_f, columna)
                ebit = _valor(ebit_f, columna)
                ebitda = _valor(ebitda_f, columna)
                neto = _valor(neto_f, columna)
                patrimonio = _valor(patrimonio_f, columna)
                deuda = _valor(deuda_f, columna)
                efectivo = _valor(efectivo_f, columna)
                flujo = _valor(flujo_f, columna)

                if ventas is None or ebit is None:
                    continue

                deuda_neta = None
                if deuda is not None:
                    deuda_neta = deuda - (efectivo or 0.0)

                filas.append(
                    {
                        "ticker": ticker,
                        "fin_periodo": fin_periodo,
                        "periodo": "anual",
                        "fecha_publicacion": publicacion,
                        # Yahoo no da la fecha real de publicacion.
                        "origen_fecha_publicacion": "estimada_retraso",
                        # Y las cifras vienen reexpresadas a dia de hoy, asi que
                        # no son las que se conocian entonces.
                        "origen_pit": "reconstruido",
                        "fecha_descarga": hoy,
                        "roe": (neto / patrimonio)
                        if neto is not None and patrimonio not in (None, 0)
                        else None,
                        "margen_operativo": (ebit / ventas) if ventas else None,
                        "ventas": ventas,
                        "flujo_caja_libre": flujo,
                        "deuda_neta": deuda_neta,
                        "ebitda": ebitda,
                        "ebit": ebit,
                        # El EV no se guarda: se calcula en la fecha de decision
                        # como acciones x precio + deuda neta, porque el EBIT es
                        # anual y mira hacia atras pero la valoracion tiene que
                        # reflejar el precio de ese dia.
                        "ev": None,
                        "patrimonio_neto": patrimonio,
                        "acciones_en_circulacion": _valor(acciones_f, columna),
                        "divisa_reporte": divisa_reporte,
                        "divisa_cotizacion": divisa_cotizacion,
                    }
                )

        return pd.DataFrame(filas)


def _valor(fila: pd.Series | None, columna) -> float | None:
    if fila is None or columna not in fila.index:
        return None
    v = fila[columna]
    if pd.isna(v):
        return None
    return float(v)
