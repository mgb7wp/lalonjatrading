"""Proveedor de datos sinteticos, determinista y sin red.

Existe por dos razones. La primera es practica: el entorno donde se desarrolla
esta app no tiene salida a Yahoo Finance, asi que sin esto no habria forma de
ejercitar el motor. La segunda es mejor: un backtest contra datos reales no
sirve para comprobar que el codigo hace lo que dice, porque los casos
interesantes —un hueco por debajo del stop, una empresa que deja de pasar el
filtro, un mercado con dos candidatas— aparecen cuando quieren. Aqui se guionan.

Determinismo. La semilla de cada ticker sale de `crc32(ticker)`, nunca de
`hash()`, que Python aleatoriza entre procesos: unos datos "deterministas" con
`hash()` cambian en cada ejecucion y el fallo tarda semanas en aparecer.

Los indices se generan primero, con un calendario de tendencias escrito a mano,
y los valores se cuelgan de ellos con una beta. Asi el regimen de mercado se
apaga en fechas conocidas y se puede afirmar en un test que no hubo compras en
ese tramo, en vez de esperar a que la aleatoriedad lo produzca.

AVISO: lo que sale de aqui no son datos de mercado. Cualquier informe generado
con este proveedor va marcado como sintetico, en la cabecera y en el nombre del
fichero, porque una curva de capital sintetica confundida con una real es un
error barato de evitar y caro de descubrir.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..config import Config
from .proveedor import Capacidades, Proveedor

SEMILLA_MAESTRA = 20240915

#: Tramos en que el indice de un mercado cae, para apagar el regimen.
#: (mercado, inicio, fin). Se eligen a proposito en mercados distintos y en
#: momentos distintos para que nunca esten todos apagados a la vez.
TRAMOS_BAJISTAS: list[tuple[str, str, str]] = [
    ("es", "2021-03-01", "2021-11-30"),
    ("in", "2022-05-01", "2023-02-28"),
    ("br", "2020-02-01", "2020-10-31"),
]

#: Guion de sucesos por ticker. Cada uno fuerza una rama del motor.
@dataclass(frozen=True, slots=True)
class Suceso:
    ticker: str
    fecha: str
    tipo: str
    magnitud: float = 0.0


SUCESOS: list[Suceso] = [
    # Hueco bajista brutal: debe salir a la apertura, no al precio del stop.
    Suceso("ITX.MC", "2022-06-15", "hueco_bajista", -0.14),
    Suceso("INFY.NS", "2023-03-08", "hueco_bajista", -0.16),
    # Minimo que perfora el stop y cierra recuperado: salida al precio del stop.
    Suceso("SAP.DE", "2022-09-21", "mecha_bajista", -0.11),
    Suceso("WEGE3.SA", "2023-07-12", "mecha_bajista", -0.13),
    # Subida sostenida: el stop dinamico acaba por encima del inicial.
    Suceso("MSFT", "2021-01-04", "subida_sostenida", 0.85),
    # Serie que se corta: cierre forzoso por falta de datos.
    Suceso("MEL.MC", "2023-05-02", "truncar", 0.0),
]

#: Empresas con guion fundamental especifico, para las trampas de signo.
FUNDAMENTAL_ESPECIAL: dict[str, str] = {
    "GRF.MC": "ebit_negativo",       # EV/EBIT invertido: no debe salir "barata"
    "BAYN.DE": "ebitda_negativo",    # deuda/EBITDA cambia de signo: debe fallar
    "TATASTEEL.NS": "patrimonio_negativo",  # ROE positivo por doble negativo
    "MGLU3.SA": "se_rompe",          # deja de pasar el filtro a mitad
    "CSNA3.SA": "caja_neta",         # deuda neta negativa: debe pasar
}


def _rng(*partes: object) -> np.random.Generator:
    """Generador reproducible a partir de las partes de una clave."""
    semilla = SEMILLA_MAESTRA
    for p in partes:
        semilla = (semilla * 1000003) ^ zlib.crc32(str(p).encode("utf-8"))
    return np.random.default_rng(semilla & 0xFFFFFFFF)


def _precio_inicial(ticker: str) -> float:
    """Precio de partida de un valor, con su propia semilla.

    Tiene generador propio para que los fundamentales puedan dimensionar las
    acciones en circulacion contra el mismo precio que va a tener la serie, y asi
    el EV/EBIT sintetico salga en un rango realista en vez de depender de dos
    escalas independientes.
    """
    return float(_rng("precio_inicial", ticker).uniform(8.0, 220.0))


class ProveedorSintetico(Proveedor):
    """Genera precios, fundamentales y divisas deterministas."""

    nombre = "sintetico"

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._cache_indices: dict[str, pd.Series] = {}

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("precios", "fundamentales", "divisas", "sectores"),
            anios_fundamentales=None,
            # Las fechas de publicacion son inventadas a partir del retraso, no
            # reales: el informe tiene que seguir avisando de que el dato es
            # reconstruido tambien con el proveedor sintetico.
            fechas_publicacion_reales=False,
            cifras_reexpresadas=True,
            incluye_deslistadas=False,
            mercados=tuple(self._cfg.reglas.mercados_por_id),
            necesita_clave=False,
            notas=(
                "DATOS INVENTADOS. No describen ningun mercado; sirven para "
                "comprobar que el motor hace lo que dice.",
            ),
        )

    # -- precios -----------------------------------------------------------

    def _sesiones(self, mercado_id: str, inicio: date, fin: date) -> list[date]:
        """Sesiones reales del mercado.

        Se usan los calendarios de verdad (que son reglas de festivos en Python,
        sin red) para que el camino sin conexion ejercite el mismo codigo de
        calendario que el camino con datos reales.
        """
        from ..calendario import Calendarios

        cal = Calendarios(self._cfg, inicio, fin)
        return cal.sesiones(mercado_id)

    def _serie_indice(self, mercado_id: str, sesiones: list[date]) -> pd.Series:
        """Nivel del indice del mercado, con sus tramos bajistas guionados."""
        clave = f"{mercado_id}:{sesiones[0]}:{sesiones[-1]}"
        if clave in self._cache_indices:
            return self._cache_indices[clave]

        rng = _rng("indice", mercado_id)
        n = len(sesiones)
        # Deriva base positiva y suave; la volatilidad del indice es menor que
        # la de un valor suelto, como en la realidad.
        deriva = np.full(n, 0.00035)
        for mercado, ini, fin in TRAMOS_BAJISTAS:
            if mercado != mercado_id:
                continue
            d_ini, d_fin = date.fromisoformat(ini), date.fromisoformat(fin)
            # Caida sostenida y bien por debajo de la media de 200 sesiones.
            mascara = np.array([d_ini <= s <= d_fin for s in sesiones])
            deriva[mascara] = -0.0022

        ruido = rng.normal(0.0, 0.0075, n)
        nivel = 1000.0 * np.exp(np.cumsum(deriva + ruido))
        serie = pd.Series(nivel, index=pd.Index(sesiones, name="fecha"))
        self._cache_indices[clave] = serie
        return serie

    def precios(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        marco: list[pd.DataFrame] = []
        indices_regimen = self._cfg.reglas.tecnico.indices_regimen
        por_indice = {v: k for k, v in indices_regimen.items()}
        # Los ETF de referencia del informe se generan como indices amplios:
        # cotizan en el calendario aleman y siguen una tendencia suave.
        referencias = {
            r.ticker: ("de" if r.divisa == "EUR" else "us")
            for r in self._cfg.implementacion.referencias.values()
        }

        for ticker in tickers:
            if ticker in referencias and ticker not in por_indice:
                mercado_ref = referencias[ticker]
                sesiones = self._sesiones(mercado_ref, inicio, fin)
                if not sesiones:
                    continue
                rng = _rng("referencia", ticker)
                n = len(sesiones)
                cierres = 50.0 * np.exp(
                    np.cumsum(rng.normal(0.00028, 0.0068, n))
                )
                marco.append(self._ohlcv(ticker, sesiones, cierres, es_indice=True))
                continue

            if ticker in por_indice:
                mercado_id = por_indice[ticker]
                sesiones = self._sesiones(mercado_id, inicio, fin)
                if not sesiones:
                    continue
                cierres = self._serie_indice(mercado_id, sesiones).to_numpy()
                marco.append(self._ohlcv(ticker, sesiones, cierres, es_indice=True))
                continue

            mercado_id = self._cfg.universo.mercado_de_ticker.get(ticker)
            if mercado_id is None:
                continue
            sesiones = self._sesiones(mercado_id, inicio, fin)
            if not sesiones:
                continue
            cierres = self._serie_valor(ticker, mercado_id, sesiones)
            marco.append(self._ohlcv(ticker, sesiones, cierres))

        if not marco:
            return pd.DataFrame(
                columns=[
                    "fecha", "ticker", "apertura", "maximo", "minimo",
                    "cierre", "cierre_bruto", "volumen",
                ]
            )
        return pd.concat(marco, ignore_index=True)

    def _serie_valor(
        self, ticker: str, mercado_id: str, sesiones: list[date]
    ) -> np.ndarray:
        rng = _rng("precio", ticker)
        n = len(sesiones)
        indice = self._serie_indice(mercado_id, sesiones).to_numpy()
        ret_indice = np.diff(np.log(indice), prepend=np.log(indice[0]))

        beta = float(rng.uniform(0.6, 1.4))
        alfa = float(rng.normal(0.00012, 0.00028))
        vol_propia = float(rng.uniform(0.010, 0.022))
        idiosincratico = rng.normal(0.0, vol_propia, n)

        retornos = alfa + beta * ret_indice + idiosincratico

        for s in SUCESOS:
            if s.ticker != ticker:
                continue
            f = date.fromisoformat(s.fecha)
            if f < sesiones[0] or f > sesiones[-1]:
                continue
            pos = min(range(n), key=lambda i: abs((sesiones[i] - f).days))
            if s.tipo == "subida_sostenida":
                # Tendencia fuerte durante un ano: el trailing se despega.
                fin = min(n, pos + 250)
                retornos[pos:fin] += s.magnitud / max(fin - pos, 1)

        return _precio_inicial(ticker) * np.exp(np.cumsum(retornos))

    def _ohlcv(
        self,
        ticker: str,
        sesiones: list[date],
        cierres: np.ndarray,
        es_indice: bool = False,
    ) -> pd.DataFrame:
        rng = _rng("ohlc", ticker)
        n = len(cierres)
        cierres = cierres.astype(float).copy()

        # La apertura parte del cierre anterior con un pequeno salto.
        previos = np.concatenate([[cierres[0]], cierres[:-1]])
        aperturas = previos * (1.0 + rng.normal(0.0, 0.004, n))

        amplitud = np.abs(rng.normal(0.0, 0.010, n)) + 0.004
        maximos = np.maximum(aperturas, cierres) * (1.0 + amplitud)
        minimos = np.minimum(aperturas, cierres) * (1.0 - amplitud)

        # Sucesos guionados: se aplican sobre el OHLC ya formado.
        truncar_desde: int | None = None
        for s in SUCESOS:
            if s.ticker != ticker:
                continue
            f = date.fromisoformat(s.fecha)
            if f < sesiones[0] or f > sesiones[-1]:
                continue
            pos = min(range(n), key=lambda i: abs((sesiones[i] - f).days))
            if s.tipo == "hueco_bajista":
                # Abre muy por debajo del cierre previo y no recupera.
                aperturas[pos] = previos[pos] * (1.0 + s.magnitud)
                cierres[pos] = aperturas[pos] * 0.995
                maximos[pos] = max(aperturas[pos], cierres[pos]) * 1.002
                minimos[pos] = min(aperturas[pos], cierres[pos]) * 0.992
            elif s.tipo == "mecha_bajista":
                # Se hunde intradia y cierra casi plano: toca el stop y vuelve.
                minimos[pos] = previos[pos] * (1.0 + s.magnitud)
                aperturas[pos] = previos[pos] * 0.999
                cierres[pos] = previos[pos] * 0.995
                maximos[pos] = max(aperturas[pos], cierres[pos]) * 1.003
            elif s.tipo == "truncar":
                truncar_desde = pos

        # Invariante del generador: un OHLC incoherente hace que la logica de
        # stops produzca disparates que parecen fallos de la estrategia.
        minimos = np.minimum(minimos, np.minimum(aperturas, cierres))
        maximos = np.maximum(maximos, np.maximum(aperturas, cierres))

        # Volumen: se busca que unos cuantos valores queden cerca del umbral de
        # liquidez y que alguno lo cruce a mitad de camino.
        base = float(_rng("vol", ticker).uniform(0.4, 60.0)) * 1e5
        rampa = np.linspace(0.55, 1.6, n)
        volumen = base * rampa * (1.0 + rng.normal(0.0, 0.25, n))
        volumen = np.maximum(volumen, 1.0)

        df = pd.DataFrame(
            {
                "fecha": sesiones,
                "ticker": ticker,
                "apertura": aperturas,
                "maximo": maximos,
                "minimo": minimos,
                "cierre": cierres,
                # Sin dividendos sinteticos, bruto y ajustado coinciden; la
                # columna existe para que el camino de codigo sea el mismo.
                "cierre_bruto": cierres,
                "volumen": volumen if not es_indice else 0.0,
            }
        )
        if truncar_desde is not None:
            df = df.iloc[:truncar_desde]
        return df

    # -- divisas -----------------------------------------------------------

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        dias = pd.date_range(inicio, fin, freq="D")
        filas: list[pd.DataFrame] = []
        # Nivel de partida EUR -> divisa, del orden de magnitud real.
        partida = {"USD": 1.10, "INR": 90.0, "BRL": 5.5, "EUR": 1.0}
        for divisa in divisas:
            if divisa == self._cfg.reglas.cartera.divisa_base:
                continue
            rng = _rng("fx", divisa)
            n = len(dias)
            vol = 0.0055 if divisa == "BRL" else 0.0028
            deriva = 0.00020 if divisa == "BRL" else 0.00002
            tasa = partida.get(divisa, 1.0) * np.exp(
                np.cumsum(rng.normal(deriva, vol, n))
            )
            filas.append(
                pd.DataFrame({"fecha": dias, "divisa": divisa, "tasa": tasa})
            )
        if not filas:
            return pd.DataFrame(columns=["fecha", "divisa", "tasa"])
        return pd.concat(filas, ignore_index=True)

    # -- sectores ----------------------------------------------------------

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        """Sectores "del proveedor", en ingles y con algunos sin mapear.

        Se deja a proposito algun sector que el mapeo no conoce: el informe
        tiene que listarlos y el valor tiene que quedarse fuera, no colarse.
        """
        inverso = {
            "electricas": "Utilities",
            "energia": "Energy",
            "materiales": "Basic Materials",
            "industrial": "Industrials",
            "tecnologia": "Technology",
            "telecomunicaciones": "Communication Services",
            "consumo_discrecional": "Consumer Cyclical",
            "consumo_basico": "Consumer Defensive",
            "salud": "Healthcare",
        }
        fuera = {"LOG.MC", "TOTS3.SA"}  # sectores que el mapeo no reconoce
        salida: dict[str, str | None] = {}
        for t in tickers:
            valor = self._cfg.universo.valores_por_ticker.get(t)
            if valor is None:
                continue
            salida[t] = "Conglomerates" if t in fuera else inverso.get(
                valor.sector_declarado
            )
        return salida

    # -- fundamentales -----------------------------------------------------

    def fundamentales(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        filas: list[dict] = []
        cfg_datos = self._cfg.reglas.datos

        for ticker in tickers:
            mercado_id = self._cfg.universo.mercado_de_ticker.get(ticker)
            if mercado_id is None:
                continue
            rng = _rng("fund", ticker)
            especial = FUNDAMENTAL_ESPECIAL.get(ticker)

            # Perfil estable de la empresa, con ruido por ejercicio encima.
            roe_base = float(rng.normal(0.145, 0.065))
            margen_base = float(rng.normal(0.125, 0.050))
            crecimiento_base = float(rng.normal(0.055, 0.075))
            deuda_base = float(rng.normal(1.9, 1.15))
            ev_ebit_base = float(rng.uniform(7.0, 26.0))
            ventas_base = float(rng.uniform(300.0, 9000.0))
            precio_tipico = _precio_inicial(ticker)
            divisa = self._cfg.reglas.mercado(mercado_id).divisa

            ano_ini, ano_fin = inicio.year - 1, fin.year
            for ano in range(ano_ini, ano_fin + 1):
                fin_periodo = date(ano, 12, 31)
                retraso = cfg_datos.retraso(mercado_id, "anual")
                publicacion = fin_periodo + timedelta(days=retraso)
                if publicacion > fin + timedelta(days=400):
                    continue

                ruido = rng.normal(0.0, 0.022)
                roe = roe_base + ruido
                margen = margen_base + ruido * 0.7
                crecimiento = crecimiento_base + rng.normal(0.0, 0.03)
                deuda_ebitda = max(deuda_base + rng.normal(0.0, 0.35), -1.5)
                ventas = ventas_base * (1.0 + crecimiento) ** (ano - ano_ini)
                ebit = ventas * margen
                ebitda = ebit * 1.28
                flujo = ebit * float(rng.uniform(0.35, 0.95))
                patrimonio = ventas * float(rng.uniform(0.35, 1.1))
                if especial == "ebit_negativo" and ano >= ano_ini + 1:
                    # EBIT negativo: un percentil inverso ingenuo la pondria
                    # como la mas barata del mercado.
                    ebit = -abs(ebit) * 0.4
                    ev = abs(ev)
                elif especial == "ebitda_negativo" and ano >= ano_ini + 1:
                    # EBITDA negativo: deuda/EBITDA sale negativo y pasaria un
                    # "<= 3.0" ingenuo.
                    ebitda = -abs(ebitda) * 0.3
                    deuda_ebitda = 1.5
                elif especial == "patrimonio_negativo" and ano >= ano_ini + 1:
                    # Patrimonio negativo con beneficio negativo: ROE sale
                    # positivo por doble negativo.
                    patrimonio = -abs(patrimonio) * 0.5
                    roe = abs(roe)
                elif especial == "se_rompe" and ano >= ano_ini + 3:
                    roe = 0.02
                    margen = 0.01
                elif especial == "caja_neta":
                    deuda_ebitda = -0.8  # caja neta: correcto que pase

                deuda_neta = deuda_ebitda * ebitda

                # El EV objetivo fija cuantas acciones hay en circulacion, para
                # que al recalcularlo en la fecha de decision con el precio de
                # ese dia salga un EV/EBIT en un rango realista en lugar de
                # depender de dos escalas independientes.
                ev = ebit * ev_ebit_base
                acciones = max((ev - deuda_neta) / precio_tipico, 1.0)

                filas.append(
                    {
                        "ticker": ticker,
                        "fin_periodo": fin_periodo,
                        "periodo": "anual",
                        "fecha_publicacion": publicacion,
                        "origen_fecha_publicacion": "estimada_retraso",
                        # Reconstruido, no capturado: estos datos no existian
                        # en su momento, se deducen ahora. El informe lo dice.
                        "origen_pit": "reconstruido",
                        "fecha_descarga": fin,
                        "roe": roe,
                        "margen_operativo": margen,
                        "ventas": ventas,
                        "flujo_caja_libre": flujo,
                        "deuda_neta": deuda_neta,
                        "ebitda": ebitda,
                        "ebit": ebit,
                        "ev": ev,
                        "patrimonio_neto": patrimonio,
                        "acciones_en_circulacion": acciones,
                        "divisa_reporte": divisa,
                        "divisa_cotizacion": divisa,
                    }
                )

        return pd.DataFrame(filas)
