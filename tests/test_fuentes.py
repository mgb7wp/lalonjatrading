"""Tests de la arquitectura de fuentes: contrato, registro, enrutador y EV.

El test que mas valor tiene de todo este fichero es
`test_el_contrato_caza_una_columna_obligatoria_entera_a_nulo`. Reproduce un fallo
que estuvo de verdad en el repositorio: el proveedor de yfinance devolvia la
columna `ev` entera a nulo, y el efecto era que la valoracion puntuaba cero para
todas las empresas y la mitad del peso de la puntuacion fundamental dejaba de
hacer nada. Sin caerse y sin avisar.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from estrategia import config as config_mod
from estrategia import fundamental as fundamental_mod
from estrategia.datos import contrato, registro
from estrategia.datos.enrutador import Enrutador
from estrategia.datos.eodhd_proveedor import (
    parsear_fundamentales,
    parsear_sector,
    ticker_eodhd,
)
from estrategia.errores import ErrorConfiguracion, ErrorDatos

from ayudas import serie_precios


# --------------------------------------------------------------------------
# Contrato
# --------------------------------------------------------------------------


def _fundamentales_validos(n: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "X",
                "fin_periodo": dt.date(2020 + i, 12, 31),
                "periodo": "anual",
                "fecha_publicacion": dt.date(2021 + i, 4, 30),
                "origen_fecha_publicacion": "proveedor",
                "origen_pit": "reconstruido",
                "fecha_descarga": dt.date(2025, 1, 1),
                "roe": 0.2,
                "margen_operativo": 0.15,
                "ventas": 1000.0,
                "flujo_caja_libre": 50.0,
                "deuda_neta": 100.0,
                "ebitda": 200.0,
                "ebit": 150.0,
                "ev": 1800.0,
                "patrimonio_neto": 500.0,
                "acciones_en_circulacion": 100.0,
                "divisa_reporte": "EUR",
                "divisa_cotizacion": "EUR",
            }
            for i in range(n)
        ]
    )


def test_el_contrato_acepta_datos_bien_formados():
    assert contrato.verificar_fundamentales(_fundamentales_validos(), "x").cumple
    fechas = [dt.date(2023, 1, 2) + dt.timedelta(days=i) for i in range(5)]
    assert contrato.verificar_precios(serie_precios("X", fechas, [10.0] * 5), "x").cumple


def test_el_contrato_caza_una_columna_obligatoria_entera_a_nulo():
    """El fallo real que motivo el contrato.

    Una columna entera a nulo no es un dato que falte: es un mapeo roto. Con el
    `ev` a nulo, EV/EBIT no se podia calcular nunca y la valoracion puntuaba cero
    para todas las empresas, dejando la mitad del peso fundamental sin efecto.
    """
    df = _fundamentales_validos()
    df["ev"] = None
    df["acciones_en_circulacion"] = None  # ningun camino para calcularlo

    inf = contrato.verificar_fundamentales(df, "yfinance")
    assert not inf.cumple
    texto = " ".join(str(i) for i in inf.incumplimientos)
    assert "ev" in texto and "acciones_en_circulacion" in texto

    with pytest.raises(ErrorDatos, match="contrato"):
        inf.exigir()


def test_basta_con_uno_de_los_dos_caminos_del_ev():
    """Con acciones en circulacion no hace falta un EV precalculado."""
    df = _fundamentales_validos()
    df["ev"] = None
    assert contrato.verificar_fundamentales(df, "x").cumple

    otro = _fundamentales_validos()
    otro["acciones_en_circulacion"] = None
    assert contrato.verificar_fundamentales(otro, "x").cumple


def test_el_contrato_caza_un_ohlc_incoherente():
    """Un OHLC incoherente hace que los stops produzcan disparates."""
    fechas = [dt.date(2023, 1, 2) + dt.timedelta(days=i) for i in range(5)]
    df = serie_precios("X", fechas, [10.0] * 5)
    df.loc[2, "minimo"] = 99.0  # minimo por encima del cierre

    inf = contrato.verificar_precios(df, "x")
    assert not inf.cumple
    assert any("OHLC" in str(i) for i in inf.incumplimientos)


def test_el_contrato_caza_fundamentales_sin_fecha_de_publicacion():
    """Sin fecha de publicacion no se puede saber que se conocia en cada momento."""
    df = _fundamentales_validos()
    df.loc[1, "fecha_publicacion"] = None
    inf = contrato.verificar_fundamentales(df, "x")
    assert not inf.cumple
    assert any("fecha de publicacion" in str(i) for i in inf.incumplimientos)


def test_el_contrato_caza_periodos_repetidos():
    df = pd.concat([_fundamentales_validos(2), _fundamentales_validos(2)])
    inf = contrato.verificar_fundamentales(df, "x")
    assert any("repetidos" in str(i) for i in inf.incumplimientos)


def test_el_contrato_junta_todos_los_problemas():
    """De una vez y no de uno en uno: al conectar una fuente interesa la lista."""
    df = _fundamentales_validos()
    df["roe"] = None
    df["ventas"] = None
    df.loc[0, "fecha_publicacion"] = None
    inf = contrato.verificar_fundamentales(df, "x")
    assert len(inf.incumplimientos) >= 2


# --------------------------------------------------------------------------
# Registro y enrutador
# --------------------------------------------------------------------------


def test_las_fuentes_de_serie_estan_registradas():
    assert set(registro.disponibles()) >= {"sintetico", "yfinance", "eodhd"}


def test_una_fuente_desconocida_da_un_error_claro(cfg):
    with pytest.raises(ErrorConfiguracion, match="desconocida"):
        registro.crear("no_existe", cfg)


def test_el_reparto_por_especialidad_manda_sobre_el_atajo(cfg):
    """`nombre` es el atajo; una clave por tipo de dato gana."""
    datos = cfg.reglas.model_dump(mode="json")
    datos["proveedor_datos"] = {
        "nombre": "sintetico",
        "fundamentales": "eodhd",
        "fundamentales_anos_disponibles": 4,
        "ampliacion_futura": "eodhd",
    }
    reglas = config_mod.Reglas.model_validate(datos)
    assert reglas.proveedor_datos.fuente_de("precios") == "sintetico"
    assert reglas.proveedor_datos.fuente_de("divisas") == "sintetico"
    assert reglas.proveedor_datos.fuente_de("fundamentales") == "eodhd"


def test_la_configuracion_del_documento_sigue_cargando(cfg):
    """La forma corta `nombre: x` tiene que seguir valiendo para todo."""
    solo = cfg.con_fuente_unica("sintetico")
    for tipo in ("precios", "fundamentales", "divisas", "sectores"):
        assert solo.reglas.proveedor_datos.fuente_de(tipo) == "sintetico"


def test_una_fuente_sin_precios_no_puede_ser_dueña_de_los_precios(cfg):
    """EODHD declara que no sirve precios; asignarselos debe fallar pronto."""
    datos = cfg.reglas.model_dump(mode="json")
    datos["proveedor_datos"] = {
        "nombre": "sintetico",
        "precios": "eodhd",
        "fundamentales_anos_disponibles": 4,
    }
    otra = cfg.model_copy(
        update={"reglas": config_mod.Reglas.model_validate(datos)}
    )
    with pytest.raises(ErrorConfiguracion, match="solo sirve"):
        Enrutador(otra).fuente("precios")


def test_el_enrutador_estampa_la_procedencia(cfg, instantanea):
    """Sin procedencia por fila, mezclar fuentes hace el backtest irrastreable."""
    e = Enrutador(cfg.con_fuente_unica("sintetico"))
    df = e.precios(["ITX.MC"], dt.date(2022, 1, 1), dt.date(2022, 6, 30))
    assert "fuente" in df.columns
    assert (df["fuente"] == "sintetico").all()


def test_el_enrutador_avisa_de_una_clave_que_falta(cfg):
    """Que falte una clave debe verse al arrancar, no a media descarga."""
    datos = cfg.reglas.model_dump(mode="json")
    datos["proveedor_datos"] = {
        "nombre": "sintetico",
        "fundamentales": "eodhd",
        "fundamentales_anos_disponibles": 4,
    }
    otra = cfg.model_copy(update={"reglas": config_mod.Reglas.model_validate(datos)})
    problemas = Enrutador(otra).comprobar_disponibilidad()
    assert any("clave" in p for p in problemas)


def test_las_capacidades_describen_la_fuente(cfg):
    e = Enrutador(cfg.con_fuente_unica("sintetico"))
    caps = e.capacidades()["sintetico"]
    assert caps.sirve("precios") and caps.sirve("fundamentales")
    # El sintetico inventa las fechas de publicacion: el informe debe seguir
    # avisando de que el dato es reconstruido.
    assert not caps.fechas_publicacion_reales


# --------------------------------------------------------------------------
# EV en la fecha de decision
# --------------------------------------------------------------------------


def _fila(**extra) -> pd.Series:
    base = {
        "ev": None,
        "acciones_en_circulacion": 100.0,
        "deuda_neta": 500.0,
        "divisa_reporte": "EUR",
        "divisa_cotizacion": "EUR",
    }
    base.update(extra)
    return pd.Series(base)


def test_el_ev_se_calcula_con_el_precio_del_dia():
    ev, motivo = fundamental_mod.valor_empresa(_fila(), precio_local=10.0)
    assert motivo is None
    assert ev == pytest.approx(100.0 * 10.0 + 500.0)


def test_el_ev_baja_cuando_baja_el_precio():
    """La valoracion tiene que moverse con el precio, no quedarse congelada.

    Es lo que separa este diseno de guardar un EV fijo por ejercicio: entre dos
    publicaciones de resultados, una accion que cae a la mitad esta mas barata, y
    el EV/EBIT tiene que reflejarlo.
    """
    caro, _ = fundamental_mod.valor_empresa(_fila(), precio_local=20.0)
    barato, _ = fundamental_mod.valor_empresa(_fila(), precio_local=10.0)
    assert barato < caro


def test_sin_precio_se_usa_el_ev_almacenado():
    """El proveedor sintetico da el EV hecho, y sus tests siguen valiendo."""
    ev, motivo = fundamental_mod.valor_empresa(_fila(ev=1234.0), precio_local=None)
    assert ev == pytest.approx(1234.0) and motivo is None


def test_divisas_distintas_dejan_sin_ev():
    """Multiplicar acciones por un precio en otra divisa da un EV sin sentido."""
    ev, motivo = fundamental_mod.valor_empresa(
        _fila(divisa_reporte="USD", divisa_cotizacion="EUR"), precio_local=10.0
    )
    assert ev is None
    assert motivo is not None and "divisas_distintas" in motivo


def test_sin_acciones_ni_ev_no_hay_valoracion():
    ev, motivo = fundamental_mod.valor_empresa(
        _fila(acciones_en_circulacion=None), precio_local=10.0
    )
    assert ev is None and motivo == "sin_acciones_en_circulacion"


def test_sin_ev_la_valoracion_va_al_peor_percentil(cfg):
    """No saber si esta barata no es lo mismo que estar barata."""
    filas = pd.DataFrame([{
        "ticker": "X", "fin_periodo": dt.date(y, 12, 31), "periodo": "anual",
        "fecha_publicacion": dt.date(2024, 4, 30), "origen_pit": "reconstruido",
        "roe": 0.2, "margen_operativo": 0.15, "ventas": 1000.0,
        "flujo_caja_libre": 50.0, "deuda_neta": 100.0, "ebitda": 200.0,
        "ebit": 150.0, "ev": None, "patrimonio_neto": 500.0,
        "acciones_en_circulacion": None,
        "divisa_reporte": "EUR", "divisa_cotizacion": "EUR",
    } for y in (2020, 2021, 2022, 2023)])

    r = fundamental_mod.ratios_de("X", filas, cfg, dt.date(2024, 6, 1), precio_local=10.0)
    assert r is not None
    assert r.ev_ebit is None
    assert r.motivo_sin_ev == "sin_acciones_en_circulacion"

    # Pasa los minimos (el EV no interviene en el filtro) pero puntua 0 en
    # valoracion, no en un percentil neutro.
    puntos = fundamental_mod.puntuar({"X": (r, "es", "industrial")}, cfg)
    assert puntos["X"].aprueba
    assert puntos["X"].valoracion == pytest.approx(0.0)


# --------------------------------------------------------------------------
# EODHD: solo lo que se puede probar sin clave ni red
# --------------------------------------------------------------------------


def test_los_codigos_de_bolsa_de_eodhd_no_son_los_de_yahoo(cfg):
    """`RELIANCE.NS` en Yahoo es `RELIANCE.NSE` en EODHD, y `.DE` es `.XETRA`."""
    assert ticker_eodhd("RELIANCE.NS", "in", cfg) == "RELIANCE.NSE"
    assert ticker_eodhd("SAP.DE", "de", cfg) == "SAP.XETRA"
    assert ticker_eodhd("AAPL", "us", cfg) == "AAPL.US"


def _payload_eodhd() -> dict:
    """Respuesta de EODHD recortada a lo que usa el adaptador."""
    return {
        "General": {
            "Code": "ITX",
            "Sector": "Consumer Cyclical",
            "CurrencyCode": "EUR",
            "CurrencySymbol": "EUR",
        },
        "Financials": {
            "Income_Statement": {
                "yearly": {
                    "2023-12-31": {
                        "date": "2023-12-31",
                        "filing_date": "2024-03-13",
                        "totalRevenue": "35947000000.00",
                        "operatingIncome": "6600000000.00",
                        "ebitda": "9800000000.00",
                        "netIncome": "5400000000.00",
                    }
                }
            },
            "Balance_Sheet": {
                "yearly": {
                    "2023-12-31": {
                        "date": "2023-12-31",
                        "totalStockholderEquity": "17000000000.00",
                        "shortLongTermDebtTotal": "6000000000.00",
                        "cash": "11000000000.00",
                        "commonStockSharesOutstanding": "3117000000",
                    }
                }
            },
            "Cash_Flow": {
                "yearly": {
                    "2023-12-31": {
                        "date": "2023-12-31",
                        "totalCashFromOperatingActivities": "8000000000.00",
                        "capitalExpenditures": "-1800000000.00",
                    }
                }
            },
        },
    }


def test_eodhd_usa_la_fecha_real_de_presentacion(cfg):
    """Es la razon de ser de esta fuente: no estimar la fecha, saberla."""
    filas = parsear_fundamentales(
        _payload_eodhd(), "ITX.MC", "es", cfg, dt.date(2025, 1, 1)
    )
    assert len(filas) == 1
    fila = filas[0]
    assert fila["fecha_publicacion"] == dt.date(2024, 3, 13)
    assert fila["origen_fecha_publicacion"] == "proveedor"
    # La estimacion por retraso habria dado el 30 de abril: mes y medio tarde.
    assert fila["fecha_publicacion"] < dt.date(2024, 4, 30)


def test_eodhd_estima_la_fecha_cuando_falta(cfg):
    payload = _payload_eodhd()
    del payload["Financials"]["Income_Statement"]["yearly"]["2023-12-31"]["filing_date"]
    fila = parsear_fundamentales(payload, "ITX.MC", "es", cfg, dt.date(2025, 1, 1))[0]
    assert fila["origen_fecha_publicacion"] == "estimada_retraso"
    assert fila["fecha_publicacion"] == dt.date(2024, 4, 29)


def test_eodhd_deja_el_dato_marcado_como_reconstruido(cfg):
    """Una fecha real arregla CUANDO se supo, no QUE version se supo.

    Las cifras siguen reexpresadas a hoy, asi que `origen_pit` sigue siendo
    reconstruido. Solo la foto semanal lo convierte en capturado.
    """
    fila = parsear_fundamentales(
        _payload_eodhd(), "ITX.MC", "es", cfg, dt.date(2025, 1, 1)
    )[0]
    assert fila["origen_pit"] == "reconstruido"


def test_eodhd_calcula_deuda_neta_y_flujo_libre(cfg):
    fila = parsear_fundamentales(
        _payload_eodhd(), "ITX.MC", "es", cfg, dt.date(2025, 1, 1)
    )[0]
    # Deuda neta = deuda total - efectivo, aqui negativa: es caja neta.
    assert fila["deuda_neta"] == pytest.approx(6_000_000_000 - 11_000_000_000)
    # El capex viene negativo; el valor absoluto hace que salga bien igual.
    assert fila["flujo_caja_libre"] == pytest.approx(8_000_000_000 - 1_800_000_000)
    assert fila["acciones_en_circulacion"] == pytest.approx(3_117_000_000)


def test_eodhd_aporta_las_piezas_del_ev_pero_no_el_ev(cfg):
    """El EV se calcula despues, con el precio de la fecha de decision."""
    fila = parsear_fundamentales(
        _payload_eodhd(), "ITX.MC", "es", cfg, dt.date(2025, 1, 1)
    )[0]
    assert fila["ev"] is None
    assert fila["acciones_en_circulacion"] is not None
    assert fila["divisa_reporte"] == "EUR"


def test_eodhd_saca_el_sector_sin_traducir(cfg):
    assert parsear_sector(_payload_eodhd()) == "Consumer Cyclical"
    # Y `sectores.py` es quien lo traduce y decide.
    from estrategia.sectores import MapaSectores

    assert MapaSectores(cfg).clasificar("ITX.MC", "Consumer Cyclical").sector == (
        "consumo_discrecional"
    )


def test_lo_que_devuelve_eodhd_cumple_el_contrato(cfg):
    """Un adaptador nuevo se valida contra el mismo contrato que los demas."""
    filas = parsear_fundamentales(
        _payload_eodhd(), "ITX.MC", "es", cfg, dt.date(2025, 1, 1)
    )
    inf = contrato.verificar_fundamentales(pd.DataFrame(filas), "eodhd")
    assert inf.cumple, [str(i) for i in inf.incumplimientos]
