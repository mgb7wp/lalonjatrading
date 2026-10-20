"""Fuentes de precios nuevas de la tarea M5: Tiingo y los ficheros de la B3.

Sin red: las respuestas siguen el formato publicado por cada proveedor (la API
de Tiingo y el layout de COTAHIST de la B3). Lo que se comprueba es lo que se
puede comprobar sin ellos: que el parseo respeta el contrato de precios, que no
mezcla precios ajustados con precios sin ajustar, y como se tratan los errores
de red.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import sys
import urllib.error
import zipfile

import pandas as pd
import pytest
from estrategia.datos import contrato
from estrategia.datos.b3_proveedor import (
    ProveedorB3,
    filas_de_cotahist,
    lineas_de_zip,
    parsear_registro,
)
from estrategia.datos.tiingo_proveedor import (
    ClaveRechazada,
    LimiteAlcanzado,
    ProveedorTiingo,
    parsear_precios,
    simbolo_tiingo,
)
from estrategia.errores import ErrorDatos

# --------------------------------------------------------------------------
# Tiingo
# --------------------------------------------------------------------------


def _dia(fecha: str, cierre: float, factor: float = 0.98) -> dict:
    """Un dia de `/tiingo/daily/{ticker}/prices`, con el formato documentado."""
    return {
        "date": f"{fecha}T00:00:00.000Z",
        "open": cierre - 1,
        "high": cierre + 2,
        "low": cierre - 2,
        "close": cierre,
        "volume": 1_000_000,
        "adjOpen": (cierre - 1) * factor,
        "adjHigh": (cierre + 2) * factor,
        "adjLow": (cierre - 2) * factor,
        "adjClose": cierre * factor,
        "adjVolume": 1_000_000,
        "divCash": 0.0,
        "splitFactor": 1.0,
    }


def test_tiingo_usa_los_precios_ajustados_y_guarda_el_bruto():
    filas = parsear_precios([_dia("2024-06-12", 100.0), _dia("2024-06-13", 101.0)], "AAPL")
    assert [f["fecha"] for f in filas] == [dt.date(2024, 6, 12), dt.date(2024, 6, 13)]
    primera = filas[0]
    assert primera["cierre"] == pytest.approx(98.0)
    assert primera["maximo"] == pytest.approx(102 * 0.98)
    assert primera["cierre_bruto"] == pytest.approx(100.0)
    assert primera["volumen"] == 1_000_000
    assert primera["ticker"] == "AAPL"


def test_tiingo_cumple_el_contrato_de_precios():
    filas = parsear_precios([_dia(f"2024-06-{d:02d}", 100.0 + d) for d in (10, 11, 12)], "AAPL")
    inf = contrato.verificar_precios(pd.DataFrame(filas), "tiingo")
    assert inf.cumple, [str(i) for i in inf.incumplimientos]


def test_tiingo_no_mezcla_un_dia_sin_ajustar_en_una_serie_ajustada():
    """Rellenar con el precio de cotizacion meteria un escalon falso."""
    sin_ajuste = _dia("2024-06-13", 101.0)
    del sin_ajuste["adjHigh"]
    filas = parsear_precios([_dia("2024-06-12", 100.0), sin_ajuste], "AAPL")
    assert [f["fecha"] for f in filas] == [dt.date(2024, 6, 12)]


@pytest.mark.parametrize(
    "roto",
    [
        {"date": "no-es-fecha"},
        {"adjClose": 0.0},
        {"adjLow": -1.0},
        {"close": None},
    ],
)
def test_tiingo_descarta_los_dias_rotos(roto):
    dia = {**_dia("2024-06-12", 100.0), **roto}
    assert parsear_precios([dia], "AAPL") == []


def test_tiingo_ignora_una_respuesta_que_no_es_una_lista():
    assert parsear_precios({"detail": "Not found."}, "AAPL") == []


@pytest.mark.parametrize(
    ("ticker", "esperado"),
    [("AAPL", "aapl"), ("BRK-B", "brk-b"), ("^GSPC", None), ("SAP.DE", None), ("", None)],
)
def test_simbolo_de_tiingo(ticker, esperado):
    assert simbolo_tiingo(ticker) == esperado


def test_tiingo_sin_clave_lo_dice_antes_de_salir_a_la_red(cfg):
    fuente = ProveedorTiingo(cfg, clave="")
    ok, motivo = fuente.disponible()
    assert not ok and "TIINGO_API_KEY" in motivo
    with pytest.raises(ErrorDatos, match="TIINGO_API_KEY"):
        fuente.precios(["AAPL"], dt.date(2024, 6, 1), dt.date(2024, 6, 14))


def test_tiingo_solo_cubre_eeuu_y_ajusta(cfg):
    cap = ProveedorTiingo(cfg, clave="x").capacidades
    assert cap.mercados == ("us",)
    assert cap.precios_ajustados
    assert cap.necesita_clave


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


def test_tiingo_manda_la_clave_en_la_cabecera_y_no_en_la_url(cfg, monkeypatch):
    vistas = []

    def falso(peticion, timeout):
        vistas.append(peticion)
        return _Respuesta(json.dumps([_dia("2024-06-12", 100.0)]).encode())

    monkeypatch.setattr("urllib.request.urlopen", falso)
    df = ProveedorTiingo(_sin_esperas(cfg), clave="secreta").precios(
        ["AAPL"], dt.date(2024, 6, 1), dt.date(2024, 6, 14)
    )
    assert len(df) == 1
    assert "secreta" not in vistas[0].full_url
    assert vistas[0].get_header("Authorization") == "Token secreta"
    assert "/aapl/prices?startDate=2024-06-01&endDate=2024-06-14" in vistas[0].full_url


def _http(codigo):
    def falso(peticion, timeout):
        raise urllib.error.HTTPError(peticion.full_url, codigo, "x", {}, None)

    return falso


def test_tiingo_clave_rechazada_corta_la_descarga(cfg, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _http(401))
    with pytest.raises(ClaveRechazada):
        ProveedorTiingo(_sin_esperas(cfg), clave="mala").precios(
            ["AAPL", "MSFT"], dt.date(2024, 6, 1), dt.date(2024, 6, 14)
        )


def test_tiingo_sin_cuota_corta_la_descarga(cfg, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _http(429))
    with pytest.raises(LimiteAlcanzado):
        ProveedorTiingo(_sin_esperas(cfg), clave="x").precios(
            ["AAPL"], dt.date(2024, 6, 1), dt.date(2024, 6, 14)
        )


def test_tiingo_un_valor_que_no_conoce_se_anota_y_se_sigue(cfg, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _http(404))
    fuente = ProveedorTiingo(_sin_esperas(cfg), clave="x")
    df = fuente.precios(["NOEXISTE"], dt.date(2024, 6, 1), dt.date(2024, 6, 14))
    assert df.empty
    assert any("NOEXISTE" in a for a in fuente.avisos)


def test_tiingo_reintenta_un_fallo_del_servidor(cfg, monkeypatch):
    llamadas = []

    def falso(peticion, timeout):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise urllib.error.HTTPError(peticion.full_url, 503, "x", {}, None)
        return _Respuesta(json.dumps([_dia("2024-06-12", 100.0)]).encode())

    monkeypatch.setattr("urllib.request.urlopen", falso)
    df = ProveedorTiingo(_sin_esperas(cfg), clave="x").precios(
        ["AAPL"], dt.date(2024, 6, 1), dt.date(2024, 6, 14)
    )
    assert len(llamadas) == 2 and len(df) == 1


# --------------------------------------------------------------------------
# B3 (COTAHIST)
# --------------------------------------------------------------------------


def _registro(
    dia: str,
    codneg: str,
    cierre_centavos: int,
    *,
    tpmerc: int = 10,
    factor: int = 1,
    cantidad: int = 1000,
    moneda: str = "R$",
) -> str:
    """Un registro de cotizacion de 245 caracteres, con el layout de la B3."""
    campos = [
        "01",
        dia,
        "02",
        codneg.ljust(12),
        f"{tpmerc:03d}",
        "PETROBRAS".ljust(12),
        "PN      N2".ljust(10),
        " " * 3,
        moneda.ljust(4),
        f"{cierre_centavos - 10:013d}",  # PREABE
        f"{cierre_centavos + 20:013d}",  # PREMAX
        f"{cierre_centavos - 30:013d}",  # PREMIN
        f"{cierre_centavos:013d}",  # PREMED
        f"{cierre_centavos:013d}",  # PREULT
        f"{cierre_centavos - 1:013d}",  # PREOFC
        f"{cierre_centavos + 1:013d}",  # PREOFV
        f"{150:05d}",  # TOTNEG
        f"{cantidad:018d}",  # QUATOT
        f"{cantidad * cierre_centavos:018d}",  # VOLTOT
        f"{0:013d}",  # PREEXE
        "0",  # INDOPC
        "99991231",  # DATVEN
        f"{factor:07d}",  # FATCOT
        f"{0:013d}",  # PTOEXE
        "BRPETRACNPR6",  # CODISI
        "123",  # DISMES
    ]
    linea = "".join(campos)
    assert len(linea) == 245
    return linea


def _cotahist() -> str:
    return "\n".join(
        [
            "00COTAHIST.2024BOVESPA 20240103" + " " * 214,
            _registro("20240102", "PETR4", 3712),
            _registro("20240103", "PETR4", 3750),
            _registro("20240103", "PETR4F", 3751, tpmerc=20),  # fraccionario
            _registro("20240103", "VALE3", 6500),  # no pedido
            _registro("20240103", "XPTO3", 150000, factor=1000),
            "99COTAHIST.2024BOVESPA 20240103" + " " * 214,
        ]
    )


def test_b3_lee_decimales_implicitos_y_factor_de_cotizacion():
    reg = parsear_registro(_registro("20240102", "PETR4", 3712))
    assert reg["fecha"] == dt.date(2024, 1, 2)
    assert reg["codneg"] == "PETR4"
    assert reg["cierre"] == pytest.approx(37.12)
    assert reg["maximo"] == pytest.approx(37.32)
    assert reg["volumen"] == 1000
    por_lote = parsear_registro(_registro("20240103", "XPTO3", 150000, factor=1000))
    assert por_lote["cierre"] == pytest.approx(1.5), "el precio va por FATCOT acciones"


@pytest.mark.parametrize(
    "linea",
    [
        "00COTAHIST.2024BOVESPA 20240103" + " " * 214,  # cabecera
        "99COTAHIST.2024BOVESPA 20240103" + " " * 214,  # cola
        _registro("20240102", "PETR4", 3712)[:200],  # cortada
        _registro("20240102", "PETR4", 3712, moneda="CR$"),  # moneda anterior al real
        _registro("20240102", "PETR4", 3712, factor=0),
        _registro("20241302", "PETR4", 3712),  # fecha imposible
    ],
)
def test_b3_descarta_lo_que_no_es_una_cotizacion_valida(linea):
    assert parsear_registro(linea) is None


def test_b3_solo_el_contado_de_los_valores_pedidos_y_en_el_rango():
    filas = filas_de_cotahist(
        _cotahist().splitlines(), ["PETR4.SA", "XPTO3.SA"], dt.date(2024, 1, 3), dt.date(2024, 1, 3)
    )
    assert {(f["ticker"], f["fecha"]) for f in filas} == {
        ("PETR4.SA", dt.date(2024, 1, 3)),
        ("XPTO3.SA", dt.date(2024, 1, 3)),
    }
    for f in filas:
        assert f["cierre"] == f["cierre_bruto"], "sin ajustar: los dos son el mismo"


def test_b3_lee_el_zip_en_flujo():
    datos = io.BytesIO()
    with zipfile.ZipFile(datos, "w") as z:
        z.writestr("COTAHIST_A2024.TXT", _cotahist().encode("latin-1"))
    assert len(list(lineas_de_zip(datos.getvalue()))) == 7


def test_b3_cumple_el_contrato_y_declara_que_no_ajusta(cfg, monkeypatch):
    def descargar(self, ano, destino):
        with zipfile.ZipFile(destino, "w") as z:
            z.writestr(f"COTAHIST_A{ano}.TXT", _cotahist().encode("latin-1"))

    monkeypatch.setattr(ProveedorB3, "_descargar", descargar)
    fuente = ProveedorB3(cfg)
    df = fuente.precios(["PETR4.SA", "NOHAY3.SA"], dt.date(2024, 1, 1), dt.date(2024, 1, 31))

    assert sorted(df["fecha"]) == [dt.date(2024, 1, 2), dt.date(2024, 1, 3)]
    inf = contrato.verificar_precios(df, "b3")
    assert inf.cumple, [str(i) for i in inf.incumplimientos]
    assert any("NOHAY3.SA" in a for a in fuente.avisos)
    assert not fuente.capacidades.precios_ajustados
    assert fuente.capacidades.mercados == ("br",)


# --------------------------------------------------------------------------
# La comprobacion de scripts/verify_sources.py
# --------------------------------------------------------------------------


def _verify_sources():
    import importlib.util
    from pathlib import Path

    ruta = Path(__file__).resolve().parents[1] / "scripts" / "verify_sources.py"
    spec = importlib.util.spec_from_file_location("verify_sources", ruta)
    modulo = importlib.util.module_from_spec(spec)
    # Las dataclasses del script buscan su modulo en `sys.modules`.
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _cierres(ticker: str, cierres: list[float]) -> pd.DataFrame:
    fechas = pd.bdate_range("2024-01-02", periods=len(cierres)).date
    return pd.DataFrame(
        {"ticker": ticker, "fecha": fechas, "cierre": cierres, "cierre_bruto": cierres}
    )


def test_la_comparacion_con_la_b3_senala_los_dias_que_yfinance_tiene_mal(cfg, monkeypatch):
    """Un split aplicado deja el cociente constante; un tramo mal ajustado no."""
    vs = _verify_sources()
    from estrategia.datos.b3_proveedor import ProveedorB3
    from estrategia.datos.yfinance_proveedor import ProveedorYFinance

    oficial = pd.concat(
        [
            _cierres("PETR4.SA", [30.0, 31.0, 32.0, 33.0]),
            _cierres("VALE3.SA", [60.0, 62.0, 64.0, 66.0]),
            _cierres("UGPA3.SA", [20.0, 21.0, 22.0, 23.0]),
        ]
    )
    yahoo = pd.concat(
        [
            _cierres("PETR4.SA", [30.0, 31.0, 32.0, 33.0]),  # coincide
            _cierres("VALE3.SA", [30.0, 31.0, 32.0, 33.0]),  # split 2:1: constante
            _cierres("UGPA3.SA", [20.0 / 2.19, 21.0 / 2.19, 22.0, 23.0]),  # tramo roto
        ]
    )
    monkeypatch.setattr(ProveedorB3, "precios", lambda self, t, i, f: oficial)
    monkeypatch.setattr(ProveedorYFinance, "precios", lambda self, t, i, f: yahoo)

    informe = vs.Informe()
    vs.verificar_b3(cfg, informe)
    resultado = {c.prueba: c.resultado for c in informe.comprobaciones}

    assert resultado["PETR4.SA frente a yfinance"] == "ok"
    assert resultado["VALE3.SA frente a yfinance"] == "ok"
    assert resultado["UGPA3.SA frente a yfinance"] == "aviso"
