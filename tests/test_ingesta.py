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


def test_cose_la_serie_cuando_cambia_la_etiqueta_contable():
    """La forma real de Apple, que es la de media EE. UU.

    Apple declara sus ventas como `SalesRevenueNet` hasta 2017 y como
    `RevenueFromContractWithCustomerExcludingAssessedTax` desde entonces, porque
    la norma ASC 606 cambio la etiqueta. Quedandose solo con el concepto
    preferido salen 9 de 19 ejercicios y **diez anos desaparecen en silencio**:
    el crecimiento de ventas a tres anos deja de poder calcularse y nadie sabe
    por que.

    Los huecos se rellenan en orden de preferencia.
    """
    from estrategia.datos.sec_proveedor import CONCEPTOS

    hechos = {
        **_hecho(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            [
                _anual("2018-12-31", 1200.0, "2019-02-09"),
                _anual("2019-12-31", 1300.0, "2020-02-09"),
            ],
        ),
        **_hecho(
            "SalesRevenueNet",
            [
                _anual("2016-12-31", 900.0, "2017-02-10"),
                _anual("2017-12-31", 1000.0, "2018-02-10"),
            ],
        ),
    }
    resultado = primera_publicacion(hechos, CONCEPTOS["ventas"])
    assert sorted(f.year for f in resultado) == [2016, 2017, 2018, 2019]
    assert resultado[dt.date(2016, 12, 31)]["valor"] == 900.0
    assert resultado[dt.date(2019, 12, 31)]["valor"] == 1300.0


def test_el_concepto_preferido_no_lo_pisa_uno_menos_preferido():
    """Rellenar huecos si; sobrescribir nunca.

    Donde dos etiquetas coexisten tiene que ganar siempre la preferida, o habria
    dos versiones de la misma cifra compitiendo y el resultado dependeria del
    orden en que se recorren los datos.
    """
    from estrategia.datos.sec_proveedor import CONCEPTOS

    hechos = {
        **_hecho(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            [_anual("2018-12-31", 1200.0, "2019-02-09")],
        ),
        # Mismo ejercicio, otra etiqueta, y publicada ANTES: aun asi no gana.
        **_hecho("SalesRevenueNet", [_anual("2018-12-31", 9999.0, "2019-01-02")]),
    }
    resultado = primera_publicacion(hechos, CONCEPTOS["ventas"])
    assert resultado[dt.date(2018, 12, 31)]["valor"] == 1200.0
    assert resultado[dt.date(2018, 12, 31)]["concepto"].startswith("RevenueFromContract")


def test_una_reexpresion_no_gana_dentro_del_mismo_concepto():
    """La regla de la primera publicacion sigue valiendo tras el cosido."""
    hechos = _hecho(
        "Revenues",
        [
            _anual("2022-12-31", 1000.0, "2023-02-10"),
            _anual("2022-12-31", 1150.0, "2024-02-09"),
        ],
    )
    resultado = primera_publicacion(hechos, ("Revenues",))
    assert resultado[dt.date(2022, 12, 31)]["valor"] == 1000.0


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


# ---------------------------------------------------------------------------
# Indicadores (FASE 4)
# ---------------------------------------------------------------------------


def test_alinear_referencia_toma_el_ultimo_cierre_conocido():
    """Nunca el mas cercano: el del dia siguiente seria mirar hacia delante.

    Dos series no comparten calendario, y ni dentro del mismo mercado coinciden
    siempre. Si un valor no cotiza un martes en que el indice si, el valor del
    lunes es lo unico que se sabia.
    """
    import numpy as np

    from workers.pipeline.indicadores import alinear_referencia

    fechas_valor = np.array([dt.date(2024, 1, 2), dt.date(2024, 1, 4)])
    fechas_indice = np.array([dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 5)])
    cierres = np.array([100.0, 101.0, 999.0])

    alineado = alinear_referencia(fechas_valor, fechas_indice, cierres)
    assert alineado[0] == 100.0
    assert alineado[1] == 101.0, "el del dia 3, no el del 5"


def test_una_fecha_anterior_al_indice_no_inventa_referencia():
    import numpy as np

    from workers.pipeline.indicadores import alinear_referencia

    alineado = alinear_referencia(
        np.array([dt.date(2023, 1, 1)]), np.array([dt.date(2024, 1, 2)]), np.array([100.0])
    )
    assert np.isnan(alineado[0])


def test_los_indices_de_referencia_se_dan_de_alta_como_valores(sesion):
    """Sin esto sus precios se descargan y se tiran, y no hay beta ni fuerza."""
    import sqlalchemy as sa

    from backend.db.models import Security
    from backend.db.models.enums import AssetType
    from backend.db.seed import cargar

    cargar(sesion)
    sesion.flush()

    indices = sesion.scalars(
        sa.select(Security).where(Security.asset_type == AssetType.INDEX.value)
    ).all()
    tickers = {i.ticker for i in indices}
    assert {"^IBEX", "^GSPC", "^NSEI", "^BVSP"} <= tickers
    assert all(not i.is_primary_listing for i in indices), "no compiten en rankings"


def test_los_indicadores_se_calculan_y_se_guardan(bd_ingesta, cfg):
    import sqlalchemy as sa

    from workers.pipeline import indicadores

    _ejecutar(bd_ingesta, cfg)
    with sa.orm.Session(bd_ingesta) as s:
        calculados = indicadores.ejecutar(s, cfg, mercados=["es"])

    assert calculados["es"] > 0
    with sa.orm.Session(bd_ingesta) as s:
        fila = s.execute(
            text(
                "SELECT rsi_14, sma_200, beta, relative_strength, extra "
                "FROM technical_indicator "
                "WHERE rsi_14 IS NOT NULL AND beta IS NOT NULL LIMIT 1"
            )
        ).first()
    assert fila is not None, "deberia haber filas con RSI y beta"
    assert 0 <= float(fila[0]) <= 100
    assert fila[4] is not None, "los indicadores sin columna propia van a extra"


def test_recalcular_los_indicadores_no_cambia_los_numeros(bd_ingesta, cfg):
    """Idempotencia de la etapa derivada, no solo de la ingesta."""
    import sqlalchemy as sa

    from backend.db.ingest import huella
    from workers.pipeline import indicadores

    _ejecutar(bd_ingesta, cfg)
    with sa.orm.Session(bd_ingesta) as s:
        indicadores.ejecutar(s, cfg, mercados=["es"])
    with sa.orm.Session(bd_ingesta) as s:
        antes = huella(s, "technical_indicator")

    with sa.orm.Session(bd_ingesta) as s:
        indicadores.ejecutar(s, cfg, mercados=["es"])
    with sa.orm.Session(bd_ingesta) as s:
        assert huella(s, "technical_indicator") == antes
    assert antes, "la huella vacia haria pasar el test sin datos"


def test_la_huella_ignora_cuando_se_calculo_pero_no_de_donde_salio(bd_ingesta, cfg):
    """`computed_at` es auditoria; `downloaded_at` es la instantanea de origen.

    Yahoo revisa el pasado hacia atras, asi que dos descargas distintas pueden
    traer numeros distintos para el mismo dia. Esa columna SI tiene que salir en
    la huella; el reloj del proceso, no.
    """
    import sqlalchemy as sa

    from backend.db.ingest import COLUMNAS_DE_AUDITORIA, columnas_de

    _ejecutar(bd_ingesta, cfg)
    with sa.orm.Session(bd_ingesta) as s:
        assert "computed_at" in columnas_de(s, "technical_indicator")
        assert "downloaded_at" in columnas_de(s, "price")
    assert "computed_at" in COLUMNAS_DE_AUDITORIA
    assert "downloaded_at" not in COLUMNAS_DE_AUDITORIA


# ---------------------------------------------------------------------------
# yfinance: la forma de lo que devuelve
# ---------------------------------------------------------------------------


def test_un_solo_ticker_se_desenvuelve_igual_que_varios():
    """Regresion: yfinance 1.x devuelve MultiIndex tambien con un ticker.

    El adaptador preguntaba `len(tickers) > 1` para decidir si desenvolver, y
    con las versiones antiguas acertaba porque un ticker suelto llegaba con las
    columnas planas. Desde la 1.x llegan siempre en dos niveles, asi que esa
    pregunta empezo a dar la respuesta contraria y **cualquier descarga de un
    valor suelto fallaba con "faltan columnas"**.

    No se vio antes porque el pipeline descarga un mercado entero de una vez, y
    con veinte tickers el camino que se toma es el bueno. Solo rompia al pedir
    uno, que es justo lo que hace una ficha de valor.

    La forma la decide ahora el dato, no el numero de tickers pedidos.
    """
    from estrategia.datos.yfinance_proveedor import _por_ticker

    campos = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    datos = {c: [1.0, 2.0] for c in campos}

    dos_niveles = pd.DataFrame({(t, c): v for t in ("KO", "AAPL") for c, v in datos.items()})
    dos_niveles.columns = pd.MultiIndex.from_tuples(dos_niveles.columns)
    assert list(_por_ticker(dos_niveles, "KO").columns) == campos

    # Un solo ticker, pero igualmente en dos niveles: el caso que rompia.
    uno = pd.DataFrame({("KO", c): v for c, v in datos.items()})
    uno.columns = pd.MultiIndex.from_tuples(uno.columns)
    assert list(_por_ticker(uno, "KO").columns) == campos

    # Y la forma antigua, plana, sigue funcionando.
    plano = pd.DataFrame(datos)
    assert list(_por_ticker(plano, "KO").columns) == campos


def test_pedir_un_ticker_que_no_esta_no_revienta():
    """Un valor que el proveedor no reconoce se salta; no tumba la descarga."""
    from estrategia.datos.yfinance_proveedor import _por_ticker

    marco = pd.DataFrame({("KO", "Close"): [1.0]})
    marco.columns = pd.MultiIndex.from_tuples(marco.columns)
    with pytest.raises(KeyError):
        _por_ticker(marco, "NOEXISTE")


# ---------------------------------------------------------------------------
# CVM (Brasil)
# ---------------------------------------------------------------------------

_CAB_DRE = (
    "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;"
    "ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA"
)


def _dre(cuentas, cnpj="33.000.167/0001-01", orden="ÚLTIMO", escala="MIL", versao="1"):
    filas = [_CAB_DRE]
    for codigo, descripcion, valor in cuentas:
        filas.append(
            f"{cnpj};2024-12-31;{versao};X S.A.;009512;DF Consolidado;REAL;{escala};"
            f"{orden};2024-01-01;2024-12-31;{codigo};{descripcion};{valor};S"
        )
    return "\n".join(filas) + "\n"


def test_la_cvm_solo_mira_el_ejercicio_que_cierra():
    """El `PENULTIMO` es el ano anterior repetido como comparativo.

    Puede venir reexpresado, igual que en EE. UU. Usarlo destruiria la propiedad
    point-in-time, que es la razon de ser de esta fuente.
    """
    from estrategia.datos.cvm_proveedor import parsear_cuentas

    texto = (
        _dre([("3.01", "Receita", "100.0")])
        + _dre([("3.01", "Receita", "999.0")], orden="PENÚLTIMO").split("\n", 1)[1]
    )
    cuentas = parsear_cuentas(texto)
    assert len(cuentas) == 1
    assert next(iter(cuentas.values()))["3.01"] == 100_000.0


def test_la_escala_no_se_aplica_a_las_cifras_por_accion():
    """`MIL` vale para los importes; el grupo 3.99 ya viene en reales por accion.

    Aplicarselo multiplicaba el BPA por mil, y como las acciones en circulacion
    se derivan de el, el error se propagaba al EV y de ahi a toda la valoracion
    sin que nada fallara por el camino. Petrobras salia con un BPA de 2.840
    reales por accion en lugar de 2,84.
    """
    from estrategia.datos.cvm_proveedor import parsear_cuentas

    cuentas = next(
        iter(
            parsear_cuentas(
                _dre([("3.01", "Receita", "100.0"), ("3.99.01.01", "ON", "2.84")])
            ).values()
        )
    )
    assert cuentas["3.01"] == 100_000.0, "los importes si llevan escala"
    assert cuentas["3.99.01.01"] == 2.84, "el beneficio por accion no"


def test_la_amortizacion_no_se_confunde_con_costes_financieros():
    """Buscar `amortiza` a secas captura la amortizacion de costes de deuda.

    Es un gasto financiero, no amortizacion de activos, y sumarlo al EBIT
    infla el EBITDA. Por eso el patron exige `deprecia`.
    """
    from estrategia.datos.cvm_proveedor import PATRON_AMORTIZACION

    assert PATRON_AMORTIZACION.search("Depreciacao, depleção e amortização")
    assert not PATRON_AMORTIZACION.search("Amortizacao de custos de emprestimos")
    assert not PATRON_AMORTIZACION.search("Amortizacao Custo Emissao de Debentures")


def test_el_capex_excluye_las_ventas_de_inmovilizado():
    """Una venta de inmovilizado es una entrada, no una inversion."""
    from estrategia.datos.cvm_proveedor import PATRON_CAPEX, PATRON_NO_CAPEX

    compra = "Aquisicoes de ativos imobilizados e intangiveis"
    venta = "Recebimento pela venda de ativo imobilizado"
    assert PATRON_CAPEX.search(compra) and not PATRON_NO_CAPEX.search(compra)
    assert PATRON_CAPEX.search(venta) and PATRON_NO_CAPEX.search(venta)


def test_el_mapeo_de_empresas_cubre_el_universo_brasileno(cfg):
    """Un ticker sin CNPJ no se puede analizar; dos con el mismo, peor."""
    import yaml

    ruta = cfg.dir_config / "cvm_empresas.yaml"
    empresas = yaml.safe_load(ruta.read_text(encoding="utf-8"))["empresas"]
    tickers = set(cfg.universo.tickers("br"))

    assert tickers == set(empresas), f"descuadre: {tickers ^ set(empresas)}"
    cnpjs = [v["cnpj"] for v in empresas.values()]
    assert len(cnpjs) == len(set(cnpjs)), "hay un CNPJ asignado a dos tickers"


def test_la_cvm_declara_que_sus_cifras_no_estan_reexpresadas(cfg):
    """Es lo que la distingue, y las capacidades son de donde sale el aviso."""
    from estrategia.datos.cvm_proveedor import ProveedorCVM

    cap = ProveedorCVM(cfg).capacidades
    assert cap.fechas_publicacion_reales
    assert not cap.cifras_reexpresadas
    assert cap.mercados == ("br",)
