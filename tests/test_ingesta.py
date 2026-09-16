"""Tests de la FASE 3: adaptadores nuevos e ingesta idempotente.

Los adaptadores se prueban contra respuestas grabadas, como el de EODHD. Ninguno
se ha podido ejecutar contra su API —el entorno de desarrollo bloquea sec.gov,
stooq.com y data-api.ecb.europa.eu—, asi que lo que se valida es el parseo, que
es donde de verdad se puede uno equivocar. Lo que no se puede saber sin red lo
comprueba `scripts/verify_sources.py`, y hasta entonces sigue siendo una
hipotesis.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from estrategia.datos import contrato
from estrategia.datos.bce_proveedor import parsear_csv as parsear_bce
from estrategia.datos.sec_proveedor import (
    parsear_companyfacts,
    parsear_mapa_cik,
    primera_publicacion,
)
from estrategia.datos.stooq_proveedor import parsear_csv as parsear_stooq
from estrategia.datos.stooq_proveedor import simbolo_stooq
from sqlalchemy import text

HOY = dt.date(2025, 6, 1)


# ---------------------------------------------------------------------------
# SEC EDGAR
# ---------------------------------------------------------------------------


def _hecho(concepto: str, entradas: list[dict]) -> dict:
    return {concepto: {"units": {"USD": entradas}}}


def _anual(fin: str, valor: float, presentado: str, inicio: str | None = None) -> dict:
    return {
        "start": inicio or f"{int(fin[:4])}-01-01",
        "end": fin,
        "val": valor,
        "filed": presentado,
        "form": "10-K",
        "accn": f"acc-{presentado}",
    }


def test_se_queda_con_la_primera_publicacion_de_cada_periodo():
    """El nucleo de por que esta fuente puede decir `capturado`.

    Cuando una empresa reexpresa sus cuentas, o repite las del ano anterior como
    comparativa, aparece otra entrada del mismo periodo con `filed` posterior. La
    de `filed` mas antiguo es la cifra tal y como se publico entonces, que es lo
    unico que un backtest tiene derecho a ver.
    """
    hechos = _hecho(
        "Revenues",
        [
            _anual("2022-12-31", 1000.0, "2023-02-10"),
            # Reexpresion publicada un ano despues: NO puede ganar.
            _anual("2022-12-31", 1150.0, "2024-02-09"),
            _anual("2023-12-31", 1200.0, "2024-02-09"),
        ],
    )
    resultado = primera_publicacion(hechos, ("Revenues",))
    assert resultado[dt.date(2022, 12, 31)]["valor"] == 1000.0
    assert resultado[dt.date(2022, 12, 31)]["presentado"] == dt.date(2023, 2, 10)
    assert resultado[dt.date(2023, 12, 31)]["valor"] == 1200.0


def test_no_mezcla_dos_conceptos_en_la_misma_serie():
    """Mezclar etiquetas produce saltos de crecimiento que no ocurrieron.

    Si el concepto preferido cubre un ejercicio, no se completa la serie con otro
    para los demas: son magnitudes definidas de forma distinta.
    """
    hechos = {
        **_hecho(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            [_anual("2023-12-31", 1200.0, "2024-02-09")],
        ),
        **_hecho("Revenues", [_anual("2022-12-31", 9999.0, "2023-02-10")]),
    }
    from estrategia.datos.sec_proveedor import CONCEPTOS

    resultado = primera_publicacion(hechos, CONCEPTOS["ventas"])
    assert set(resultado) == {dt.date(2023, 12, 31)}, "no debe colarse el otro concepto"


def test_descarta_las_magnitudes_trimestrales_de_un_10k():
    """Un 10-K trae tambien cifras de trimestre; sin filtrar entran como anuales."""
    hechos = _hecho(
        "Revenues",
        [
            _anual("2023-12-31", 1200.0, "2024-02-09"),
            # Mismo cierre, pero solo tres meses de duracion.
            _anual("2023-12-31", 310.0, "2024-02-09", inicio="2023-10-01"),
        ],
    )
    resultado = primera_publicacion(hechos, ("Revenues",))
    assert resultado[dt.date(2023, 12, 31)]["valor"] == 1200.0


def _companyfacts() -> dict:
    return {
        "facts": {
            "us-gaap": {
                **_hecho("Revenues", [_anual("2023-12-31", 1000.0, "2024-02-09")]),
                **_hecho("OperatingIncomeLoss", [_anual("2023-12-31", 200.0, "2024-02-09")]),
                **_hecho(
                    "DepreciationDepletionAndAmortization",
                    [_anual("2023-12-31", 50.0, "2024-02-09")],
                ),
                **_hecho("NetIncomeLoss", [_anual("2023-12-31", 150.0, "2024-02-09")]),
                **_hecho(
                    "StockholdersEquity",
                    [{"end": "2023-12-31", "val": 750.0, "filed": "2024-02-09", "form": "10-K"}],
                ),
                **_hecho(
                    "LongTermDebtNoncurrent",
                    [{"end": "2023-12-31", "val": 400.0, "filed": "2024-02-09", "form": "10-K"}],
                ),
                **_hecho(
                    "CashAndCashEquivalentsAtCarryingValue",
                    [{"end": "2023-12-31", "val": 100.0, "filed": "2024-02-09", "form": "10-K"}],
                ),
                **_hecho(
                    "NetCashProvidedByUsedInOperatingActivities",
                    [_anual("2023-12-31", 300.0, "2024-02-09")],
                ),
                **_hecho(
                    "PaymentsToAcquirePropertyPlantAndEquipment",
                    [_anual("2023-12-31", 80.0, "2024-02-09")],
                ),
                **_hecho(
                    "CommonStockSharesOutstanding",
                    [{"end": "2023-12-31", "val": 500.0, "filed": "2024-02-09", "form": "10-K"}],
                ),
            }
        }
    }


def test_parsea_un_ejercicio_completo():
    fila = parsear_companyfacts(_companyfacts(), "AAPL", HOY)[0]

    assert fila["ticker"] == "AAPL"
    assert fila["periodo"] == "anual"
    assert fila["fecha_publicacion"] == dt.date(2024, 2, 9)
    assert fila["origen_pit"] == "capturado"
    assert fila["ventas"] == 1000.0
    assert fila["ebit"] == 200.0
    assert fila["ebitda"] == 250.0, "EBIT + amortizaciones"
    assert fila["deuda_neta"] == 300.0, "deuda 400 menos caja 100"
    assert fila["flujo_caja_libre"] == 220.0, "flujo operativo 300 menos capex 80"
    assert fila["roe"] == pytest.approx(150.0 / 750.0)
    assert fila["margen_operativo"] == pytest.approx(0.2)
    assert fila["ev"] is None, "la SEC publica cuentas, no cotizaciones"
    assert fila["acciones_en_circulacion"] == 500.0


def test_la_fecha_de_la_fila_es_la_mas_tardia_de_sus_magnitudes():
    """Tomar la mas temprana dejaria ver la fila entera antes de existir entera.

    Es sesgo de anticipacion por la puerta de atras: la fila se compone de varias
    magnitudes y solo esta completa cuando se publico la ultima.
    """
    payload = _companyfacts()
    payload["facts"]["us-gaap"]["StockholdersEquity"]["units"]["USD"][0]["filed"] = "2024-05-20"
    fila = parsear_companyfacts(payload, "AAPL", HOY)[0]
    assert fila["fecha_publicacion"] == dt.date(2024, 5, 20)


def test_lo_que_devuelve_la_sec_cumple_el_contrato():
    """La comprobacion que caza un mapeo roto antes de que mate media puntuacion."""
    filas = []
    for ticker in ("AAPL", "MSFT", "KO"):
        filas += parsear_companyfacts(_companyfacts(), ticker, HOY)
    inf = contrato.verificar_fundamentales(pd.DataFrame(filas), "sec")
    assert inf.cumple, [str(i) for i in inf.incumplimientos]


def test_un_companyfacts_vacio_no_revienta():
    assert parsear_companyfacts({}, "AAPL", HOY) == []
    assert parsear_companyfacts({"facts": {}}, "AAPL", HOY) == []


def test_el_cik_se_rellena_a_diez_digitos():
    """La API los exige con ceros a la izquierda y el fichero los da sin ellos."""
    mapa = parsear_mapa_cik({"0": {"cik_str": 320193, "ticker": "aapl", "title": "Apple"}})
    assert mapa == {"AAPL": "0000320193"}


# ---------------------------------------------------------------------------
# BCE
# ---------------------------------------------------------------------------

CSV_BCE = """KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-01-02,1.0956,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-01-03,1.0919,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-01-04,NaN,A
EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-01-05,,A
"""


def test_el_bce_descarta_los_dias_sin_cotizacion():
    """Arrastrarlos como ceros daria tipos de cambio imposibles."""
    filas = parsear_bce(CSV_BCE, "USD")
    assert len(filas) == 2
    assert filas[0] == {"fecha": dt.date(2024, 1, 2), "divisa": "USD", "tasa": 1.0956}


def test_lo_que_devuelve_el_bce_cumple_el_contrato():
    df = pd.DataFrame(parsear_bce(CSV_BCE, "USD"))
    inf = contrato.verificar_fx(df, "bce")
    assert inf.cumple, [str(i) for i in inf.incumplimientos]


def test_el_bce_avisa_si_no_reconoce_las_columnas():
    """Fiarse de la posicion es lo que rompe el dia que anaden una columna."""
    from estrategia.errores import ErrorDatos

    with pytest.raises(ErrorDatos, match="TIME_PERIOD"):
        parsear_bce("a,b,c\n1,2,3\n", "USD")


# ---------------------------------------------------------------------------
# Stooq
# ---------------------------------------------------------------------------

CSV_STOOQ = """Date,Open,High,Low,Close,Volume
2024-01-02,10.0,10.5,9.8,10.2,120000
2024-01-03,10.2,10.4,10.0,10.1,95000
"""


def test_stooq_traduce_los_sufijos_de_cada_mercado(cfg):
    """No coinciden con los de Yahoo y el mapeo vive en la configuracion."""
    assert simbolo_stooq("AAPL", "us", cfg) == "aapl.us"
    assert simbolo_stooq("ITX.MC", "es", cfg) == "itx.es"
    assert simbolo_stooq("PETR4.SA", "br", cfg) == "petr4.br"
    assert simbolo_stooq("RELIANCE.NS", "in", cfg) == "reliance.in"


def test_lo_que_devuelve_stooq_cumple_el_contrato():
    df = pd.DataFrame(parsear_stooq(CSV_STOOQ, "ITX.MC"))
    inf = contrato.verificar_precios(df, "stooq")
    assert inf.cumple, [str(i) for i in inf.incumplimientos]


def test_stooq_no_finge_distinguir_el_cierre_bruto_del_ajustado():
    """No se ha podido comprobar que los distinga; inventarlo seria peor."""
    filas = parsear_stooq(CSV_STOOQ, "ITX.MC")
    assert all(f["cierre"] == f["cierre_bruto"] for f in filas)


def test_stooq_declara_que_su_ajuste_esta_sin_verificar(cfg):
    """Las capacidades no son documentacion: el informe las lee para avisar.

    Mientras `verify_sources.py` no se haya pasado con red de verdad, esta
    fuente no puede presentarse como equivalente a las demas.
    """
    from estrategia.datos.stooq_proveedor import ProveedorStooq

    notas = " ".join(ProveedorStooq(cfg).capacidades.notas).upper()
    assert "SIN VERIFICAR" in notas


def test_stooq_devuelve_vacio_cuando_no_hay_datos():
    """Stooq responde texto plano tambien cuando no tiene el valor."""
    assert parsear_stooq("No data", "XXX") == []


# ---------------------------------------------------------------------------
# Ingesta: el criterio de aceptacion de la FASE 3
# ---------------------------------------------------------------------------


@pytest.fixture
def bd_ingesta(engine, cfg):
    """Base de datos con referencia cargada y lista para ingerir."""
    import sqlalchemy as sa

    from backend.db.seed import cargar

    with sa.orm.Session(engine) as s:
        cargar(s)
        for tabla in ("price", "fundamental_snapshot", "fx_rate", "data_freshness"):
            s.execute(text(f"DELETE FROM {tabla}"))
        s.execute(text("DELETE FROM pipeline_run"))
        s.commit()
    return engine


def _ejecutar(engine, cfg, proveedor="sintetico", **kwargs):
    import sqlalchemy as sa
    from estrategia.datos.enrutador import Enrutador

    from workers.pipeline import ingesta

    cfg_uno = cfg.con_fuente_unica(proveedor)
    with sa.orm.Session(engine) as s:
        return ingesta.ejecutar(s, cfg_uno, Enrutador(cfg_uno), mercados=["es"], anos=2, **kwargs)


def test_la_ingesta_carga_precios_y_fundamentales(bd_ingesta, cfg):
    import sqlalchemy as sa

    resultados = _ejecutar(bd_ingesta, cfg)
    assert all(r.estado != "failed" for r in resultados), [str(r) for r in resultados]

    with sa.orm.Session(bd_ingesta) as s:
        assert s.execute(text("SELECT count(*) FROM price")).scalar() > 0
        assert s.execute(text("SELECT count(*) FROM fundamental_snapshot")).scalar() > 0


def test_ejecutarla_dos_veces_no_cambia_una_sola_fila(bd_ingesta, cfg):
    """El criterio de aceptacion de la FASE 3, comprobado y no prometido.

    Con `forzar` se vuelve a descargar y a escribir TODO, en lugar de saltarse
    las etapas ya hechas. Es la comprobacion dura: no basta con no repetir el
    trabajo, es que repetirlo tiene que dar exactamente lo mismo.
    """
    import sqlalchemy as sa

    from backend.db.ingest import huella

    _ejecutar(bd_ingesta, cfg)
    with sa.orm.Session(bd_ingesta) as s:
        antes = {t: huella(s, t) for t in ("price", "fundamental_snapshot", "fx_rate")}

    _ejecutar(bd_ingesta, cfg, forzar=True)
    with sa.orm.Session(bd_ingesta) as s:
        despues = {t: huella(s, t) for t in ("price", "fundamental_snapshot", "fx_rate")}

    assert antes == despues
    assert antes["price"], "la huella vacia haria pasar el test sin datos"


def test_una_etapa_ya_terminada_se_salta(bd_ingesta, cfg):
    _ejecutar(bd_ingesta, cfg)
    segunda = _ejecutar(bd_ingesta, cfg)
    assert all(r.estado == "skipped" for r in segunda), [str(r) for r in segunda]


def test_el_fallo_de_un_mercado_no_tumba_el_resto(bd_ingesta, cfg):
    """§48: un proveedor caido degrada el servicio, no lo tumba.

    Con cinco mercados y fuentes gratuitas, que la India no responda no puede
    dejar sin actualizar a EE. UU.
    """
    import sqlalchemy as sa
    from estrategia.datos.enrutador import Enrutador
    from estrategia.errores import ErrorDatos

    from workers.pipeline import ingesta

    cfg_uno = cfg.con_fuente_unica("sintetico")
    enrutador = Enrutador(cfg_uno)
    original = enrutador.precios

    def precios_que_fallan_en_india(tickers, inicio, fin):
        if any(t.endswith(".NS") for t in tickers):
            raise ErrorDatos("la fuente no responde")
        return original(tickers, inicio, fin)

    enrutador.precios = precios_que_fallan_en_india

    with sa.orm.Session(bd_ingesta) as s:
        resultados = ingesta.ejecutar(s, cfg_uno, enrutador, mercados=["in", "es"], anos=2)

    por_clave = {(r.mercado, r.etapa): r for r in resultados}
    assert por_clave[("in", "precios")].estado == "failed"
    assert por_clave[("es", "precios")].estado == "succeeded"
    assert por_clave[("es", "precios")].filas > 0

    with sa.orm.Session(bd_ingesta) as s:
        fallos = s.execute(
            text("SELECT count(*) FROM data_quality_check WHERE status='failed' AND market_id='in'")
        ).scalar()
    assert fallos >= 1, "el fallo tiene que quedar registrado, no solo en un log"


def test_la_frescura_ignora_las_publicaciones_futuras(bd_ingesta, cfg):
    """Una fila que dice publicarse manana no es el ultimo dato disponible.

    Tomarla como referencia daria una frescura inmejorable justo cuando algo va
    mal. El proveedor sintetico fabrica el ejercicio en curso, asi que este caso
    se da siempre y es un buen banco de pruebas.
    """
    import sqlalchemy as sa

    _ejecutar(bd_ingesta, cfg)
    with sa.orm.Session(bd_ingesta) as s:
        ultima = s.execute(
            text(
                "SELECT last_data_date FROM data_freshness "
                "WHERE dataset='fundamentales' AND market_id='es'"
            )
        ).scalar()
        futuras = s.execute(
            text(
                "SELECT count(*) FROM data_quality_check "
                "WHERE check_name='publicacion_futura' AND status='warning'"
            )
        ).scalar()

    assert ultima is None or ultima <= dt.date.today()
    assert futuras >= 1, "y si las hay, tiene que avisar"


def test_los_fundamentales_no_se_marcan_rancios_con_la_vara_de_los_precios(bd_ingesta, cfg):
    """Se publican una o cuatro veces al ano; medirlos en dias los marca siempre.

    Y una alarma que siempre esta encendida es una alarma que nadie mira.
    """
    import sqlalchemy as sa

    _ejecutar(bd_ingesta, cfg)
    with sa.orm.Session(bd_ingesta) as s:
        rancios = s.execute(
            text("SELECT count(*) FROM data_freshness WHERE dataset='fundamentales' AND is_stale")
        ).scalar()
    assert rancios == 0
