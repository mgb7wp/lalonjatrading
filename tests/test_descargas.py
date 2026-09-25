"""Descargas robustas con datos reales (tarea B6).

Con 140 valores, Yahoo devuelve casi siempre algo raro: una fila con el minimo
por encima del cierre, una fecha repetida, un valor que no responde, un tipo de
cambio que deja de actualizarse. Antes cualquiera de esas cosas tumbaba la
descarga entera, o pasaba en silencio. Estos tests fijan que ahora:

- las filas malas se reparan o se apartan, y se avisa;
- cada tipo de dato se guarda por separado: si fallan los fundamentales, los
  precios buenos no se pierden;
- los estados financieros se reintentan y entre valor y valor hay una pausa;
- faltar una divisa o tener el cambio congelado es un error, no un silencio;
- un volumen con huecos no pasa el filtro de liquidez;
- la sesion del dia en curso no se usa;
- el diagnostico mira el ejercicio mas reciente, y tambien los indices, las
  divisas y los ETF de referencia.
"""

from __future__ import annotations

import datetime as dt
import shutil
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from ayudas import instantanea_de, serie_precios
from estrategia import cli
from estrategia import diagnostico as diagnostico_mod
from estrategia import universo as universo_mod
from estrategia.datos import contrato
from estrategia.datos.almacen import Instantanea
from estrategia.datos.enrutador import Enrutador
from estrategia.datos.yfinance_proveedor import ProveedorYFinance
from estrategia.errores import ErrorDatos

DIR_CONFIG_PRUEBA = Path(__file__).resolve().parent / "config_prueba"


def _fila(ticker, fecha, o, h, lo, c, v=1_000.0):
    return {
        "fecha": fecha,
        "ticker": ticker,
        "apertura": o,
        "maximo": h,
        "minimo": lo,
        "cierre": c,
        "cierre_bruto": c,
        "volumen": v,
    }


# --------------------------------------------------------------------------
# Filas malas: se reparan o se apartan
# --------------------------------------------------------------------------


def _lote_con_filas_malas():
    d = dt.date
    return pd.DataFrame(
        [
            _fila("A", d(2024, 1, 2), 10, 11, 9, 10.5),  # buena
            _fila("A", d(2024, 1, 3), 10, 10.2, 10.1, 10.5),  # minimo > apertura y maximo < cierre
            _fila("A", d(2024, 1, 4), 10, 11, 9, np.nan),  # sin cierre
            _fila("A", d(2024, 1, 5), 10, 11, 9, 10.0),  # repetida (se queda la ultima)
            _fila("A", d(2024, 1, 5), 10, 11, 9, 10.2),
            _fila("A", d(2024, 1, 8), np.nan, np.nan, np.nan, 10.4),  # solo cierre
            _fila("A", d(2024, 1, 9), -1, 11, 9, 10.0),  # precio negativo
            _fila("A", d(2024, 1, 10), 10, 11, 9, 10.1),  # sesion en curso
        ]
    )


def test_una_fila_mala_ya_no_tumba_el_lote():
    lote = _lote_con_filas_malas()
    # Con el contrato solo, el lote entero se rechazaba.
    assert not contrato.verificar_precios(lote, "prueba").cumple

    limpio, info = contrato.limpiar_precios(lote, hoy=dt.date(2024, 1, 10))
    assert contrato.verificar_precios(limpio, "prueba").cumple

    assert info.sin_cierre == 1
    assert info.duplicadas == 1
    assert info.precios_negativos == 1
    assert info.sesion_en_curso == 1
    assert info.ohlc_rellenadas == 1
    assert info.ohlc_reparadas == 1
    assert len(limpio) == 4

    reparada = limpio[limpio["fecha"] == dt.date(2024, 1, 3)].iloc[0]
    assert reparada["minimo"] == pytest.approx(10.0)
    assert reparada["maximo"] == pytest.approx(10.5)
    # De la fecha repetida se queda la ultima que llego.
    assert limpio[limpio["fecha"] == dt.date(2024, 1, 5)].iloc[0]["cierre"] == 10.2
    rellena = limpio[limpio["fecha"] == dt.date(2024, 1, 8)].iloc[0]
    assert rellena[["apertura", "maximo", "minimo"]].tolist() == [10.4, 10.4, 10.4]

    avisos = info.avisos("prueba")
    assert len(avisos) == 6
    assert any("sesion en curso" in a for a in avisos)


class _FuenteFalsa:
    nombre = "falsa"

    def __init__(self, precios=None, fx=None):
        self._precios, self._fx = precios, fx
        self.avisos: list[str] = []

    def precios(self, tickers, inicio, fin):
        return self._precios

    def fx(self, divisas, inicio, fin):
        return self._fx


def test_el_enrutador_limpia_y_avisa(cfg, monkeypatch):
    fuente = _FuenteFalsa(precios=_lote_con_filas_malas())
    fuente.avisos.append("[falsa/precios] 1 valor sin precios: B")
    e = Enrutador(cfg, hoy=dt.date(2024, 1, 10))
    monkeypatch.setattr(e, "fuente", lambda tipo: fuente)

    df = e.precios(["A", "B"], dt.date(2024, 1, 1), dt.date(2024, 1, 10))
    assert len(df) == 4
    assert (df["fuente"] == "falsa").all()
    assert any("1 valor sin precios: B" in a for a in e.avisos)
    assert any("reparadas" in a for a in e.avisos)
    # Los avisos de la fuente se recogen una sola vez.
    assert fuente.avisos == []


# --------------------------------------------------------------------------
# Divisas: todas y al dia
# --------------------------------------------------------------------------


def _fx(divisas, desde, hasta):
    fechas = pd.bdate_range(desde, hasta).date
    return pd.DataFrame([{"fecha": f, "divisa": d, "tasa": 1.1} for d in divisas for f in fechas])


def test_falta_una_divisa_es_un_error(cfg, monkeypatch):
    fuente = _FuenteFalsa(fx=_fx(["USD", "INR"], "2024-11-01", "2024-12-30"))
    e = Enrutador(cfg, hoy=dt.date(2024, 12, 31))
    monkeypatch.setattr(e, "fuente", lambda tipo: fuente)
    with pytest.raises(ErrorDatos, match="faltan divisas.*BRL"):
        e.fx(["EUR", "USD", "INR", "BRL"], dt.date(2024, 11, 1), dt.date(2024, 12, 31))


def test_un_cambio_congelado_es_un_error(cfg, monkeypatch):
    lote = pd.concat(
        [
            _fx(["USD", "INR"], "2024-11-01", "2024-12-30"),
            _fx(["BRL"], "2024-11-01", "2024-12-10"),  # dejo de actualizarse
        ]
    )
    e = Enrutador(cfg, hoy=dt.date(2024, 12, 31))
    monkeypatch.setattr(e, "fuente", lambda tipo: _FuenteFalsa(fx=lote))
    with pytest.raises(ErrorDatos, match="antiguedad.*BRL"):
        e.fx(["USD", "INR", "BRL"], dt.date(2024, 11, 1), dt.date(2024, 12, 31))


def test_un_hueco_en_el_historico_de_cambios_se_avisa(cfg, monkeypatch):
    lote = pd.concat(
        [
            _fx(["USD"], "2024-01-01", "2024-03-01"),
            _fx(["USD"], "2024-04-01", "2024-12-30"),
        ]
    )
    e = Enrutador(cfg, hoy=dt.date(2024, 12, 31))
    monkeypatch.setattr(e, "fuente", lambda tipo: _FuenteFalsa(fx=lote))
    e.fx(["USD"], dt.date(2024, 1, 1), dt.date(2024, 12, 31))
    assert any("USD" in a and "tramos sin cotizacion" in a for a in e.avisos)


def test_la_sesion_de_hoy_no_se_usa_en_los_cambios(cfg, monkeypatch):
    lote = _fx(["USD"], "2024-11-01", "2024-12-31")
    e = Enrutador(cfg, hoy=dt.date(2024, 12, 31))
    monkeypatch.setattr(e, "fuente", lambda tipo: _FuenteFalsa(fx=lote))
    df = e.fx(["USD"], dt.date(2024, 11, 1), dt.date(2024, 12, 31))
    assert max(df["fecha"]) == dt.date(2024, 12, 30)


# --------------------------------------------------------------------------
# Cada tipo de dato se guarda por separado
# --------------------------------------------------------------------------


@pytest.fixture
def carpetas(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DIR_CACHE", tmp_path / "datos" / "cache")
    monkeypatch.setattr(cli, "DIR_FOTOS", tmp_path / "datos" / "fotos")
    monkeypatch.setattr(cli, "DIR_RESULTADOS", tmp_path / "datos" / "resultados")
    monkeypatch.setattr(cli, "DIR_SITIO", tmp_path / "sitio")
    return tmp_path


@pytest.fixture
def config_sintetica(tmp_path):
    destino = tmp_path / "config"
    shutil.copytree(DIR_CONFIG_PRUEBA, destino)
    reglas = destino / "reglas.yaml"
    texto = reglas.read_text(encoding="utf-8")
    reglas.write_text(texto.replace("nombre: yfinance", "nombre: sintetico", 1), encoding="utf-8")
    return destino


def _romper_fundamentales(monkeypatch):
    def falla(self, tickers, inicio, fin):
        raise ErrorDatos("la fuente de fundamentales no responde")

    monkeypatch.setattr(Enrutador, "fundamentales", falla)


def test_si_fallan_los_fundamentales_los_precios_se_guardan(
    carpetas, config_sintetica, monkeypatch
):
    _romper_fundamentales(monkeypatch)
    with pytest.raises(SystemExit) as salida:
        cli.main(["--config", str(config_sintetica), "datos", "--anos", "2"])
    assert salida.value.code == 1

    cache = carpetas / "datos" / "cache" / "sintetico"
    inst = Instantanea.cargar(cache)
    assert not inst.precios.empty
    assert not inst.fx.empty
    assert inst.fundamentales.empty
    assert inst.incompletos == ["fundamentales"]


def test_si_fallan_los_fundamentales_se_conservan_los_anteriores(
    carpetas, config_sintetica, monkeypatch
):
    base = ["--config", str(config_sintetica)]
    assert cli.main([*base, "datos", "--anos", "2"]) == 0
    cache = carpetas / "datos" / "cache" / "sintetico"
    antes = pd.read_parquet(cache / "fundamentales.parquet")
    assert not antes.empty

    _romper_fundamentales(monkeypatch)
    with pytest.raises(SystemExit):
        cli.main([*base, "datos", "--anos", "2"])
    inst = Instantanea.cargar(cache)
    assert len(inst.fundamentales) == len(antes)
    assert inst.incompletos == ["fundamentales"]


def test_sin_precios_no_se_toca_la_cache(carpetas, config_sintetica, monkeypatch):
    base = ["--config", str(config_sintetica)]
    assert cli.main([*base, "datos", "--anos", "2"]) == 0
    cache = carpetas / "datos" / "cache" / "sintetico"
    marca = (cache / "precios.parquet").stat().st_mtime_ns

    def falla(self, tickers, inicio, fin):
        raise ErrorDatos("sin conexion")

    monkeypatch.setattr(Enrutador, "precios", falla)
    with pytest.raises(SystemExit):
        cli.main([*base, "datos", "--anos", "2"])
    assert (cache / "precios.parquet").stat().st_mtime_ns == marca
    assert Instantanea.cargar(cache).incompletos == []


def test_el_informe_avisa_de_una_descarga_incompleta(cfg, instantanea):
    from estrategia import backtest as backtest_mod
    from estrategia import informe as informe_mod

    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2024, 1, 1), dt.date(2024, 6, 30))
    instantanea.incompletos = ["fundamentales"]
    try:
        inf = informe_mod.construir(r, cfg, instantanea)
    finally:
        instantanea.incompletos = []
    assert any(a.clave == "descarga_incompleta" for a in inf.avisos)


# --------------------------------------------------------------------------
# yfinance: reintentos en los estados financieros y pausas
# --------------------------------------------------------------------------


def _cfg_red(cfg, pausa=0.0):
    descargas = cfg.implementacion.descargas.model_copy(
        update={"espera_inicial_s": 0.0, "pausa_entre_peticiones_s": pausa}
    )
    impl = cfg.implementacion.model_copy(update={"descargas": descargas})
    return cfg.model_copy(update={"implementacion": impl})


def _estados(anos=4):
    columnas = [pd.Timestamp(f"{2023 - i}-12-31") for i in range(anos)]
    resultados = pd.DataFrame(
        {c: [1000.0, 150.0, 200.0, 100.0] for c in columnas},
        index=["Total Revenue", "EBIT", "EBITDA", "Net Income"],
    )
    balance = pd.DataFrame(
        {c: [800.0, 300.0, 100.0, 50.0] for c in columnas},
        index=[
            "Stockholders Equity",
            "Total Debt",
            "Cash And Cash Equivalents",
            "Ordinary Shares Number",
        ],
    )
    caja = pd.DataFrame({c: [90.0] for c in columnas}, index=["Free Cash Flow"])
    return resultados, balance, caja


def _yfinance_falso(monkeypatch, fallos_por_ticker):
    """Un modulo `yfinance` que falla N veces por ticker al pedir resultados."""
    llamadas: dict[str, int] = {}
    resultados, balance, caja = _estados()

    class Ticker:
        def __init__(self, ticker):
            self.ticker = ticker
            self.info = {"financialCurrency": "EUR", "currency": "EUR"}

        @property
        def income_stmt(self):
            llamadas[self.ticker] = llamadas.get(self.ticker, 0) + 1
            if llamadas[self.ticker] <= fallos_por_ticker.get(self.ticker, 0):
                raise ConnectionError("429 Too Many Requests")
            return resultados

        balance_sheet = balance
        cashflow = caja

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Ticker))
    return llamadas


def _dos_tickers(cfg):
    return [t for t in cfg.universo.tickers() if cfg.universo.mercado_de_ticker[t] == "es"][:2]


def test_los_estados_financieros_se_reintentan(cfg, monkeypatch):
    a, b = _dos_tickers(cfg)
    llamadas = _yfinance_falso(monkeypatch, {a: 2})
    p = ProveedorYFinance(_cfg_red(cfg))
    df = p.fundamentales([a, b], dt.date(2020, 1, 1), dt.date(2024, 12, 31))
    assert set(df["ticker"]) == {a, b}
    assert llamadas[a] == 3
    assert p.avisos == []


def test_un_valor_que_sigue_fallando_se_avisa_y_no_para_el_resto(cfg, monkeypatch):
    a, b = _dos_tickers(cfg)
    intentos = cfg.implementacion.descargas.intentos
    _yfinance_falso(monkeypatch, {a: intentos + 5})
    p = ProveedorYFinance(_cfg_red(cfg))
    df = p.fundamentales([a, b], dt.date(2020, 1, 1), dt.date(2024, 12, 31))
    assert set(df["ticker"]) == {b}
    assert any(a in aviso and "reintentar" in aviso for aviso in p.avisos)


def test_hay_pausa_entre_valor_y_valor(cfg, monkeypatch):
    a, b = _dos_tickers(cfg)
    _yfinance_falso(monkeypatch, {})
    pausas: list[float] = []
    import estrategia.datos.yfinance_proveedor as yfp

    monkeypatch.setattr(yfp.time, "sleep", lambda s: pausas.append(s))
    p = ProveedorYFinance(_cfg_red(cfg, pausa=0.5))
    p.fundamentales([a, b], dt.date(2020, 1, 1), dt.date(2024, 12, 31))
    assert pausas.count(0.5) >= 2


# --------------------------------------------------------------------------
# Liquidez con volumen a huecos
# --------------------------------------------------------------------------


def _ticker_es(cfg):
    return next(t for t in cfg.universo.tickers() if cfg.universo.mercado_de_ticker[t] == "es")


def test_un_volumen_con_huecos_no_pasa_el_filtro_por_las_buenas(cfg):
    ticker = _ticker_es(cfg)
    fechas = list(pd.bdate_range("2024-01-01", periods=80).date)
    volumen = [1_000_000.0] * 80
    volumen[-5] = np.nan
    inst = instantanea_de(cfg, serie_precios(ticker, fechas, [10.0] * 80, volumen=volumen))
    medio = universo_mod.volumen_medio_base(ticker, "es", fechas[-1], inst.vista(fechas[-1]), cfg)
    # Antes salia NaN, y NaN < minimo es falso: pasaba el filtro.
    assert np.isfinite(medio)
    # El hueco cuenta como una sesion sin negociacion.
    sesiones = cfg.reglas.universo.sesiones_volumen
    assert medio == pytest.approx(10.0 * 1_000_000.0 * (sesiones - 1) / sesiones)


def test_un_volumen_todo_huecos_no_es_liquido(cfg):
    ticker = _ticker_es(cfg)
    fechas = list(pd.bdate_range("2024-01-01", periods=80).date)
    inst = instantanea_de(cfg, serie_precios(ticker, fechas, [10.0] * 80, volumen=[np.nan] * 80))
    medio = universo_mod.volumen_medio_base(ticker, "es", fechas[-1], inst.vista(fechas[-1]), cfg)
    assert medio == 0.0
    assert medio < cfg.reglas.universo.volumen_minimo("desarrollado")


# --------------------------------------------------------------------------
# Diagnostico
# --------------------------------------------------------------------------


def _fundamentales_desordenados(ticker):
    """Como los da Yahoo: del ejercicio mas reciente al mas antiguo. El mas
    antiguo no tiene acciones en circulacion; el mas reciente, si."""
    filas = []
    for ano, acciones in ((2023, 50.0), (2022, 50.0), (2021, 50.0), (2020, None)):
        filas.append(
            {
                "ticker": ticker,
                "fin_periodo": dt.date(ano, 12, 31),
                "periodo": "anual",
                "fecha_publicacion": dt.date(ano + 1, 4, 30),
                "origen_fecha_publicacion": "estimada_retraso",
                "origen_pit": "reconstruido",
                "roe": 0.2,
                "margen_operativo": 0.15,
                "ventas": 1000.0,
                "flujo_caja_libre": 90.0,
                "deuda_neta": 200.0,
                "ebitda": 200.0,
                "ebit": 150.0,
                "ev": None,
                "patrimonio_neto": 800.0,
                "acciones_en_circulacion": acciones,
                "divisa_reporte": "EUR",
                "divisa_cotizacion": "EUR",
            }
        )
    return pd.DataFrame(filas)


def test_el_diagnostico_mira_el_ejercicio_mas_reciente(cfg, monkeypatch):
    ticker = _ticker_es(cfg)
    fechas = list(pd.bdate_range("2024-10-01", "2024-12-30").date)
    precios = serie_precios(ticker, fechas, [10.0] * len(fechas))
    monkeypatch.setattr(Enrutador, "precios", lambda self, t, i, f: precios)
    monkeypatch.setattr(
        Enrutador, "fundamentales", lambda self, t, i, f: _fundamentales_desordenados(ticker)
    )
    monkeypatch.setattr(Enrutador, "sectores", lambda self, t: {ticker: "Industrials"})

    filas = diagnostico_mod.ejecutar(cfg, dt.date(2020, 1, 1), dt.date(2024, 12, 31), [ticker])
    # Con el ejercicio mas antiguo, sin acciones, salia "sin EV".
    assert filas[0].ev_calculable, filas[0].problemas


def test_el_diagnostico_comprueba_indices_referencias_y_divisas(cfg, instantanea, monkeypatch):
    hasta = dt.date(2024, 12, 31)
    precios = instantanea.precios
    fx = instantanea.fx[instantanea.fx["divisa"] != "BRL"]  # falta una divisa
    monkeypatch.setattr(
        Enrutador, "precios", lambda self, t, i, f: precios[precios["ticker"].isin(t)]
    )
    monkeypatch.setattr(Enrutador, "fx", lambda self, d, i, f: fx)

    aux = diagnostico_mod.comprobar_auxiliares(
        cfg, dt.date(2022, 1, 1), hasta, hoy=hasta + dt.timedelta(days=1)
    )
    tipos = {a.tipo for a in aux}
    assert tipos == {"indice", "referencia", "divisa"}
    assert len([a for a in aux if a.tipo == "indice"]) == len(cfg.reglas.tecnico.indices_regimen)

    malos = {a.nombre for a in aux if not a.utilizable}
    assert malos == {"BRL"}

    texto = diagnostico_mod.a_texto([], cfg, auxiliares=aux)
    assert "Indices, referencias y divisas" in texto
    assert "BRL" in texto and "sin tipo de cambio" in texto
