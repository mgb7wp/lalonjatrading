"""Fuente `yahoo`: el grafico v8 de Yahoo sin la libreria yfinance (tarea M5).

Sin red: las respuestas siguen el formato del grafico v8. Lo que se comprueba es
que el ajuste por dividendos se aplica igual que en el adaptador de yfinance,
que no se mezclan dias ajustados y sin ajustar, que cada barra se fecha con la
hora de su bolsa y como se tratan los errores.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import urllib.error

import pandas as pd
import pytest
from estrategia.datos import contrato, registro
from estrategia.datos.enrutador import Enrutador
from estrategia.datos.yahoo_proveedor import LimiteAlcanzado, ProveedorYahoo, parsear_grafico
from estrategia.errores import ErrorDatos

#: 2024-06-12 13:30 UTC, la apertura de Nueva York.
NY = 1718199000


def _grafico(marcas, cierres, ajustados, gmtoffset=-14400):
    """Respuesta del grafico v8 con el formato de Yahoo."""
    n = len(marcas)
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"currency": "USD", "gmtoffset": gmtoffset},
                    "timestamp": marcas,
                    "indicators": {
                        "quote": [
                            {
                                "open": [None if c is None else c - 1 for c in cierres],
                                "high": [None if c is None else c + 2 for c in cierres],
                                "low": [None if c is None else c - 2 for c in cierres],
                                "close": cierres,
                                "volume": [1000] * n,
                            }
                        ],
                        "adjclose": [{"adjclose": ajustados}],
                    },
                }
            ],
        }
    }


def test_ajusta_los_cuatro_precios_por_dividendos_y_guarda_el_bruto():
    filas = parsear_grafico(_grafico([NY], [100.0], [98.0]), "AAPL")
    assert len(filas) == 1
    f = filas[0]
    assert f["cierre"] == pytest.approx(98.0)
    assert f["cierre_bruto"] == pytest.approx(100.0)
    assert f["apertura"] == pytest.approx(99 * 0.98)
    assert f["maximo"] == pytest.approx(102 * 0.98)
    assert f["minimo"] == pytest.approx(98 * 0.98)
    assert f["volumen"] == 1000


def test_cumple_el_contrato_de_precios():
    dia = 86_400
    filas = parsear_grafico(
        _grafico([NY, NY + dia, NY + 2 * dia], [100.0, 101.0, 102.0], [99.0, 100.0, 101.0]),
        "AAPL",
    )
    inf = contrato.verificar_precios(pd.DataFrame(filas), "yahoo")
    assert inf.cumple, [str(i) for i in inf.incumplimientos]


def test_las_ranuras_sin_negociacion_no_son_dias():
    filas = parsear_grafico(_grafico([NY, NY + 86_400], [100.0, None], [98.0, None]), "AAPL")
    assert len(filas) == 1


def test_un_dia_sin_ajuste_no_se_mezcla_con_los_ajustados():
    filas = parsear_grafico(_grafico([NY, NY + 86_400], [100.0, 101.0], [98.0, None]), "AAPL")
    assert [f["fecha"] for f in filas] == [dt.date(2024, 6, 12)]


def test_un_factor_disparatado_es_un_dato_roto():
    assert parsear_grafico(_grafico([NY], [100.0], [100_000.0]), "AAPL") == []


def test_sin_ningun_ajuste_la_respuesta_no_se_usa():
    datos = _grafico([NY], [100.0], [98.0])
    del datos["chart"]["result"][0]["indicators"]["adjclose"]
    assert parsear_grafico(datos, "AAPL") == []


def test_un_valor_que_yahoo_no_conoce_es_una_lista_vacia():
    datos = {"chart": {"result": None, "error": {"code": "Not Found", "description": "x"}}}
    assert parsear_grafico(datos, "NOEXISTE") == []
    assert parsear_grafico({}, "NOEXISTE") == []


def test_cada_barra_se_fecha_con_la_hora_de_su_bolsa():
    """23:00 UTC del 11 es el 12 en una bolsa a UTC+9: la fecha es la local."""
    once_23h_utc = int(dt.datetime(2024, 6, 11, 23, 0, tzinfo=dt.UTC).timestamp())
    filas = parsear_grafico(_grafico([once_23h_utc], [100.0], [100.0], gmtoffset=9 * 3600), "X")
    assert filas[0]["fecha"] == dt.date(2024, 6, 12)


def test_cubre_todo_lo_que_cubre_yfinance(cfg):
    """Mercados, indices de regimen y referencias del informe."""
    cap = ProveedorYahoo(cfg).capacidades
    assert cap.mercados is None
    assert cap.precios_ajustados
    assert not cap.necesita_clave
    assert registro.crear("yahoo", cfg).nombre == "yahoo"


class _Respuesta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _sin_esperas(cfg):
    red = cfg.implementacion.descargas.model_copy(
        update={"espera_inicial_s": 0.0, "pausa_entre_peticiones_s": 0.0}
    )
    impl = cfg.implementacion.model_copy(update={"descargas": red})
    return cfg.model_copy(update={"implementacion": impl})


def test_pide_el_rango_con_cabecera_de_navegador(cfg, monkeypatch):
    vistas = []

    def falso(peticion, timeout):
        vistas.append(peticion)
        return _Respuesta(json.dumps(_grafico([NY], [100.0], [98.0])).encode())

    monkeypatch.setattr("urllib.request.urlopen", falso)
    df = ProveedorYahoo(_sin_esperas(cfg)).precios(
        ["^GSPC"], dt.date(2024, 6, 1), dt.date(2024, 6, 14)
    )
    assert len(df) == 1
    url = vistas[0].full_url
    assert "/chart/%5EGSPC?" in url
    assert "period1=1717200000" in url and "period2=1718409600" in url
    assert "Mozilla" in vistas[0].get_header("User-agent")


def test_lo_que_queda_fuera_del_rango_pedido_se_aparta(cfg, monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda p, timeout: _Respuesta(json.dumps(_grafico([NY], [100.0], [98.0])).encode()),
    )
    df = ProveedorYahoo(_sin_esperas(cfg)).precios(
        ["AAPL"], dt.date(2024, 6, 13), dt.date(2024, 6, 14)
    )
    assert df.empty


def _http(codigo):
    def falso(peticion, timeout):
        raise urllib.error.HTTPError(peticion.full_url, codigo, "x", {}, None)

    return falso


def test_un_429_corta_la_descarga(cfg, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _http(429))
    with pytest.raises(LimiteAlcanzado):
        ProveedorYahoo(_sin_esperas(cfg)).precios(
            ["AAPL", "MSFT"], dt.date(2024, 6, 1), dt.date(2024, 6, 14)
        )


def test_un_valor_desconocido_se_anota_y_se_sigue(cfg, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _http(404))
    fuente = ProveedorYahoo(_sin_esperas(cfg))
    df = fuente.precios(["NOEXISTE"], dt.date(2024, 6, 1), dt.date(2024, 6, 14))
    assert df.empty
    assert any("NOEXISTE" in a for a in fuente.avisos)


def test_un_servidor_caido_tras_los_reintentos_es_un_aviso(cfg, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _http(503))
    fuente = ProveedorYahoo(_sin_esperas(cfg))
    df = fuente.precios(["AAPL"], dt.date(2024, 6, 1), dt.date(2024, 6, 14))
    assert df.empty
    assert any("Yahoo no responde" in a for a in fuente.avisos)


def test_como_respaldo_sirve_el_indice_que_tiingo_no_tiene(cfg, monkeypatch):
    """La cadena tipica de EE. UU.: Tiingo para las acciones, Yahoo para ^GSPC."""
    from estrategia.datos import yfinance_proveedor
    from estrategia.datos.tiingo_proveedor import ProveedorTiingo, simbolo_tiingo

    def principal_caida(self, tickers, inicio, fin):
        raise ErrorDatos("yfinance caida")

    def tiingo(self, tickers, inicio, fin):
        filas = [
            {
                "fecha": dt.date(2024, 6, 12),
                "ticker": t,
                "apertura": 99.0,
                "maximo": 102.0,
                "minimo": 98.0,
                "cierre": 100.0,
                "cierre_bruto": 100.0,
                "volumen": 1.0,
            }
            for t in tickers
            if simbolo_tiingo(t) is not None  # como la de verdad: sin indices
        ]
        return pd.DataFrame(filas)

    monkeypatch.setattr(yfinance_proveedor.ProveedorYFinance, "precios", principal_caida)
    monkeypatch.setattr(ProveedorTiingo, "precios", tiingo)
    monkeypatch.setattr(ProveedorTiingo, "disponible", lambda self: (True, ""))
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda p, timeout: _Respuesta(json.dumps(_grafico([NY], [5000.0], [5000.0])).encode()),
    )
    datos = cfg.reglas.proveedor_datos.model_copy(
        update={"nombre": "yfinance", "precios_respaldo": ["tiingo", "yahoo"]}
    )
    cfg_r = _sin_esperas(cfg).model_copy(
        update={"reglas": cfg.reglas.model_copy(update={"proveedor_datos": datos})}
    )
    indice = cfg.reglas.tecnico.indices_regimen["us"]

    df = Enrutador(cfg_r, hoy=dt.date(2024, 6, 13)).precios(
        ["AAPL", indice], dt.date(2024, 6, 1), dt.date(2024, 6, 12)
    )

    assert dict(zip(df["ticker"], df["fuente"], strict=True)) == {"AAPL": "tiingo", indice: "yahoo"}
