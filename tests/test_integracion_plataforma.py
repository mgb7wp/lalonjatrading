"""Lo que se rompia al juntar los arreglos del motor (B1-B10) con la plataforma.

Cada test cubre un sitio donde un arreglo correcto para el motor en solitario
cambiaba el comportamiento de la plataforma sin que ningun test lo notara.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from estrategia import backtest as backtest_mod
from estrategia.datos.almacen import Instantanea
from estrategia.datos.enrutador import Enrutador
from estrategia.informe import es_sintetico
from estrategia.sectores import MapaSectores

# --- Sectores que ya son categorias -----------------------------------------


def test_un_sector_que_ya_es_categoria_no_se_rechaza(cfg):
    """La base de datos guarda la categoria (`tecnologia`), no la etiqueta del
    proveedor (`Technology`). Tiene que admitirse tal cual."""
    mapa = MapaSectores(cfg)
    c = mapa.clasificar("SAP.DE", "tecnologia")
    assert c.admitido and c.sector == "tecnologia"
    assert not mapa.sin_mapear


def test_una_categoria_excluida_sigue_excluida(cfg):
    c = MapaSectores(cfg).clasificar("X", "bancos")
    assert not c.admitido and c.sector == "bancos"


def test_una_etiqueta_desconocida_sigue_rechazandose(cfg):
    """El arreglo B8 se mantiene: lo que no es ni etiqueta conocida ni
    categoria no se tapa con el sector declarado."""
    mapa = MapaSectores(cfg)
    c = mapa.clasificar("ITX.MC", "Conglomerates")
    assert not c.admitido
    assert "Conglomerates" in mapa.sin_mapear


def test_un_backtest_con_los_sectores_de_la_base_abre_posiciones(cfg, instantanea):
    """Es lo que hace `backend/adapters/desde_bd.py`: pasa `security.sector`,
    que es la categoria de `universo.yaml`. Antes del arreglo, cada valor salia
    como sector desconocido y el backtest no abria ni una posicion."""
    categorias = {t: v.sector_declarado for t, v in cfg.universo.valores_por_ticker.items()}
    desde_bd = Instantanea(
        precios=instantanea.precios,
        fundamentales=instantanea.fundamentales,
        fx=instantanea.fx,
        sectores=categorias,
        fecha_descarga=instantanea.fecha_descarga,
        origen="base de datos (sintetico)",
    )
    r = backtest_mod.ejecutar(desde_bd, cfg, dt.date(2021, 1, 1), dt.date(2024, 12, 31))
    assert not r.operaciones_df.empty


# --- La sesion del dia en la descarga programada ------------------------------


def _precios_hasta(dia: dt.date) -> pd.DataFrame:
    fechas = pd.bdate_range(dia - dt.timedelta(days=10), dia).date
    n = len(fechas)
    return pd.DataFrame(
        {
            "ticker": ["ITX.MC"] * n,
            "fecha": fechas,
            "apertura": [10.0] * n,
            "maximo": [11.0] * n,
            "minimo": [9.0] * n,
            "cierre": [10.5] * n,
            "cierre_bruto": [10.5] * n,
            "volumen": [1000.0] * n,
        }
    )


class _FuenteFija:
    nombre = "sintetico"

    def __init__(self, df):
        self._df = df

    def precios(self, tickers, inicio, fin):
        return self._df


def _enrutador_con(cfg, df, hoy):
    e = Enrutador(cfg.con_fuente_unica("sintetico"), verificar=False, hoy=hoy)
    fuente = _FuenteFija(df)
    e.fuente = lambda tipo: fuente
    return e


def test_por_defecto_la_sesion_de_hoy_se_aparta(cfg):
    dia = dt.date(2024, 6, 14)
    df = _enrutador_con(cfg, _precios_hasta(dia), hoy=dia).precios(["ITX.MC"], dia, dia)
    assert dia not in set(df["fecha"])


def test_tras_el_cierre_la_sesion_de_hoy_se_conserva(cfg):
    """El pipeline programado descarga despues del cierre y pasa `hoy` = manana."""
    dia = dt.date(2024, 6, 14)
    df = _enrutador_con(cfg, _precios_hasta(dia), hoy=dia + dt.timedelta(days=1)).precios(
        ["ITX.MC"], dia, dia
    )
    assert dia in set(df["fecha"])


class _Parar(Exception):
    pass


def test_la_tarea_de_mercado_le_dice_al_enrutador_que_hoy_ha_cerrado(monkeypatch):
    from estrategia.datos import enrutador as enrutador_mod

    from workers import planificador, runner

    vistos: list[dt.date] = []

    def espia(cfg, verificar=True, hoy=None):
        vistos.append(hoy)
        raise _Parar

    monkeypatch.setattr(enrutador_mod, "Enrutador", espia)
    monkeypatch.setattr(planificador, "ha_negociado", lambda *_: True)
    with pytest.raises(_Parar):
        runner.ejecutar_mercado("es", "XMAD")
    assert vistos == [dt.date.today() + dt.timedelta(days=1)]


def test_la_tarea_de_divisas_conserva_el_cambio_de_hoy(monkeypatch):
    from estrategia.datos import enrutador as enrutador_mod

    from workers import runner

    vistos: list[dt.date] = []

    def espia(cfg, verificar=True, hoy=None):
        vistos.append(hoy)
        raise _Parar

    monkeypatch.setattr(enrutador_mod, "Enrutador", espia)
    with pytest.raises(_Parar):
        runner.ejecutar_divisas()
    assert vistos == [dt.date.today() + dt.timedelta(days=1)]


# --- El proveedor sintetico no sale a la red ----------------------------------


def test_forzar_sintetico_no_deja_fundamentales_en_la_sec_ni_en_la_cvm(cfg_real):
    """Riesgo RT-6: `--proveedor sintetico` seguia pidiendo los fundamentales de
    EE. UU. a la SEC y los de Brasil a la CVM."""
    forzada = cfg_real.con_fuente_unica("sintetico")
    datos = forzada.reglas.proveedor_datos
    for mercado in forzada.reglas.mercados_por_id:
        assert datos.fuente_de("fundamentales", mercado) == "sintetico"
    assert Enrutador(forzada).fuentes_usadas == ["sintetico"]


def test_el_backtest_desde_la_base_sintetica_se_marca_como_sintetico():
    assert es_sintetico("base de datos (sintetico)")
    assert es_sintetico("eodhd+sintetico")
    assert not es_sintetico("base de datos (sec+yfinance)")
    assert not es_sintetico("bce+cvm+sec+yfinance")
