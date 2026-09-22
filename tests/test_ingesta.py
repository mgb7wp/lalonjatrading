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


def test_la_frescura_de_los_fundamentales_pregunta_por_el_MERCADO(bd_ingesta, cfg):
    """La fila de `data_freshness` tiene que decir la fuente de ESE mercado.

    Los fundamentales son el unico tipo que se reparte por mercado, y la ingesta
    pedia el nombre en global: `/health/data` publicaba 'yfinance' para EE. UU.
    y Brasil mientras el API servia la SEC y la CVM, con `pit_origin` capturado.

    Se espia la llamada en lugar de mirar la fila porque aqui se ingiere con el
    proveedor sintetico, donde todas las fuentes se llaman igual y la fila
    saldria bien con las dos implementaciones. Lo que discrimina es CON QUE se
    pregunta: con el codigo anterior no llega ni un `mercado`.
    """
    import sqlalchemy as sa
    from estrategia.datos.enrutador import Enrutador

    from workers.pipeline import ingesta

    cfg_uno = cfg.con_fuente_unica("sintetico")
    enrutador = Enrutador(cfg_uno)
    original = enrutador.nombre_de
    preguntas: list[tuple] = []

    def espia(tipo, mercado=None):
        preguntas.append((tipo, mercado))
        return original(tipo, mercado)

    enrutador.nombre_de = espia
    with sa.orm.Session(bd_ingesta) as s:
        ingesta.ejecutar(s, cfg_uno, enrutador, mercados=["es"], anos=2)

    de_fundamentales = {m for tipo, m in preguntas if tipo == "fundamentales"}
    assert de_fundamentales == {"es"}, f"se pregunto en global: {preguntas}"


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


# ---------------------------------------------------------------------------
# Reparto de fundamentales por mercado
# ---------------------------------------------------------------------------


def test_cada_mercado_pide_los_fundamentales_a_su_fuente(cfg):
    """Las fuentes con fecha de publicacion real son nacionales.

    La SEC solo cubre EE. UU. y la CVM solo Brasil, asi que elegir una sola
    fuente para todo el universo seria elegir que mercado se queda sin
    point-in-time.
    """
    reparto = cfg.reglas.proveedor_datos
    assert reparto.fuente_de("fundamentales", "us") == "sec"
    assert reparto.fuente_de("fundamentales", "br") == "cvm"
    # Lo que no esta en el reparto cae en la fuente general.
    assert reparto.fuente_de("fundamentales", "es") == "yfinance"
    assert reparto.fuente_de("fundamentales", None) == "yfinance"


def test_la_calidad_fundamental_no_es_un_si_o_no(cfg):
    """yfinance devuelve fundamentales de los cinco mercados.

    Un "disponible: si/no" diria que si en todos y seria inutil. Lo que cambia
    es que en EE. UU. y Brasil son las cifras de su momento con la fecha en que
    se publicaron, y en el resto son cuatro ejercicios reexpresados con la fecha
    estimada. Sobre lo segundo no se construye un backtest creible.
    """
    from estrategia.datos.enrutador import Enrutador

    e = Enrutador(cfg, verificar=False)
    for mercado in ("us", "br"):
        q = e.calidad_fundamental(mercado)
        assert q.nivel == "completa", f"{mercado}: {q.motivo}"
        assert q.sirve_para_puntuar
        assert q.anios and q.anios >= 10

    for mercado in ("es", "de", "in"):
        q = e.calidad_fundamental(mercado)
        assert q.nivel == "degradada", f"{mercado}: {q.motivo}"
        assert not q.sirve_para_puntuar
        assert "reexpresadas" in q.motivo


def test_la_calidad_se_deduce_de_las_capacidades_no_de_una_lista(cfg):
    """Una lista escrita a mano acabaria contradiciendo al reparto.

    Si se cambia la fuente de un mercado, la calidad tiene que cambiar sola. Una
    lista aparte de "mercados sin fundamentales" se quedaria desfasada y nadie
    lo notaria.
    """
    from estrategia.datos.enrutador import Enrutador

    cfg_cambiada = cfg.model_copy(deep=True)
    object.__setattr__(
        cfg_cambiada.reglas.proveedor_datos,
        "fundamentales_por_mercado",
        {"us": "yfinance"},
    )
    q = Enrutador(cfg_cambiada, verificar=False).calidad_fundamental("us")
    assert q.nivel == "degradada", "al cambiar la fuente, la calidad la sigue"


def test_una_fuente_que_no_cubre_un_mercado_lo_declara(cfg):
    from estrategia.datos.enrutador import Enrutador

    cfg_cambiada = cfg.model_copy(deep=True)
    object.__setattr__(
        cfg_cambiada.reglas.proveedor_datos, "fundamentales_por_mercado", {"es": "sec"}
    )
    q = Enrutador(cfg_cambiada, verificar=False).calidad_fundamental("es")
    assert q.nivel == "no_disponible"
    assert "no cubre" in q.motivo


def test_las_acciones_no_se_creen_una_etiqueta_mal_escalada():
    """McDonald's declara sus acciones con unidad `shares` y valor en MILLONES.

    XBRL no lo impide, asi que la misma etiqueta viene en unidades en unas
    empresas y en millones en otras. Creersela daba una capitalizacion un millon
    de veces menor y un PER de 0,0 — y no fallaba nada: la empresa aparecia
    sencillamente como la mas barata del mercado.

    Beneficio partido por BPA es inmune a la escala, porque el BPA esta por
    accion y el beneficio en moneda.
    """
    from estrategia.datos.sec_proveedor import _acciones

    # 8.200 M$ de beneficio y 11,45 $/accion -> ~716 M acciones, no 716.
    assert _acciones(716.4, 8_200_000_000.0, 11.45) == pytest.approx(716_157_205, rel=1e-3)
    # Sin BPA no hay con que contrastar y se cree lo declarado.
    assert _acciones(716_000_000.0, 8_200_000_000.0, None) == 716_000_000.0
    # Perdidas: el cociente sigue dando un numero de acciones positivo.
    assert _acciones(None, -100.0, -0.5) == pytest.approx(200.0)


def test_una_columna_vacia_solo_es_sospechosa_en_un_lote_grande():
    """Con una empresa no distingue un mapeo roto de una que no lo publica.

    McDonald's no declara `GrossProfit` en su XBRL. Exigirlo en un lote de un
    ticker convertiria la ficha de un valor en un error que no lo es; el fallo
    que motivo la comprobacion era el de una descarga completa, y ahi se sigue
    aplicando entera.
    """
    from estrategia.datos.contrato import MINIMO_PARA_EXIGIR_COLUMNA

    base = {
        "ticker": "X",
        "fin_periodo": dt.date(2024, 12, 31),
        "periodo": "anual",
        "fecha_publicacion": dt.date(2025, 2, 1),
        "origen_fecha_publicacion": "real",
        "origen_pit": "capturado",
        "fecha_descarga": dt.date(2025, 3, 1),
        "roe": 0.2,
        "margen_operativo": 0.1,
        "ventas": 100.0,
        "flujo_caja_libre": 10.0,
        "deuda_neta": 5.0,
        "ebitda": 20.0,
        "ebit": 15.0,
        "ev": 200.0,
        "patrimonio_neto": 50.0,
        "acciones_en_circulacion": 10.0,
        "divisa_reporte": "USD",
        "divisa_cotizacion": "USD",
        "beneficio_bruto": None,
    }
    magnitudes = ("beneficio_bruto",)

    uno = contrato.verificar_fundamentales(pd.DataFrame([base]), "sec", magnitudes)
    assert uno.cumple, [str(i) for i in uno.incumplimientos]

    muchos = pd.DataFrame([{**base, "ticker": f"T{i}"} for i in range(MINIMO_PARA_EXIGIR_COLUMNA)])
    assert not contrato.verificar_fundamentales(muchos, "sec", magnitudes).cumple


def test_un_valor_dado_de_baja_no_se_descarga_pero_no_se_borra(cfg):
    """Borrar la fila deja un universo que finge que la empresa nunca existio.

    Eso es sesgo de supervivencia metido a mano. Se marca la baja con su motivo
    y su sucesor, y se excluye de las descargas —pedir a diario cinco valores
    que ya no existen garantiza cinco errores por ejecucion que nadie mira—.
    """
    activos = cfg.universo.tickers("br")
    todos = cfg.universo.tickers("br", incluir_inactivos=True)
    bajas = {v.ticker: v for v in cfg.universo.inactivos()}

    assert set(todos) - set(activos) == set(bajas)
    assert bajas, "el universo brasileno tiene bajas verificadas"
    for valor in bajas.values():
        assert valor.motivo_baja, f"{valor.ticker} sin motivo de baja"
        assert valor.sucesor, f"{valor.ticker} sin sucesor anotado"


def test_las_bajas_verificadas_son_fusiones_y_traslados(cfg):
    """No son renombres, y la diferencia importa.

    Un renombre es la misma empresa con otro ticker: se actualiza y ya. Una
    fusion produce otra compañia, y apuntar las cuentas historicas de BRF al
    precio de MBRF3 mezclaria dos. Un traslado a NYSE deja en B3 un BDR, que es
    otro instrumento, no la accion.
    """
    bajas = {v.ticker: v for v in cfg.universo.inactivos()}
    assert "BRFS3.SA" in bajas and bajas["BRFS3.SA"].sucesor == "MBRF3.SA"
    assert "JBSS3.SA" in bajas and "BDR" in bajas["JBSS3.SA"].motivo_baja
    # Los renombres SI se aplicaron sobre el propio ticker.
    activos = set(cfg.universo.tickers("br"))
    assert "AXIA3.SA" in activos and "ELET3.SA" not in activos
    assert "CPLE3.SA" in activos and "CPLE6.SA" not in activos


def test_toda_magnitud_del_contrato_llega_a_la_base_de_datos():
    """El contrato vigila al proveedor; esto vigila la escritura.

    Las nueve magnitudes de §14 estuvieron en el contrato sin estar en el mapeo
    de escritura: los adaptadores las calculaban y el ingest las tiraba. 1.394
    filas con las nueve columnas a cero, sin que fallara nada — los ratios que
    dependian de ellas salian simplemente vacios, que es indistinguible de "esta
    empresa no lo publica".

    Un dato que se calcula y no se guarda es peor que uno que no se calcula: da
    la impresion de estar cubierto.
    """
    from estrategia.datos.proveedor import COLUMNAS_FUNDAMENTALES, MAGNITUDES_OPCIONALES

    from backend.adapters.nucleo import COLUMNAS_FUNDAMENTAL, FUNDAMENTALES
    from backend.db.models import Base

    tabla = Base.metadata.tables["fundamental_snapshot"]
    sin_camino = []
    for magnitud in (*MAGNITUDES_OPCIONALES, *COLUMNAS_FUNDAMENTALES):
        if magnitud in ("ticker", "periodo", "origen_pit", "fecha_descarga"):
            continue  # se traducen aparte, no por el mapa de columnas
        columna = FUNDAMENTALES.get(magnitud, magnitud)
        if columna not in tabla.c:
            continue  # el esquema no la guarda a proposito
        if columna not in COLUMNAS_FUNDAMENTAL:
            sin_camino.append(f"{magnitud} -> {columna}")

    assert not sin_camino, "estas magnitudes se calculan y no se escriben: " + ", ".join(sin_camino)


def test_las_magnitudes_opcionales_tienen_columna_propia():
    """Si una se guardara solo en `extra`, no se podria filtrar por ella."""
    from estrategia.datos.proveedor import MAGNITUDES_OPCIONALES

    from backend.adapters.nucleo import FUNDAMENTALES
    from backend.db.models import Base

    tabla = Base.metadata.tables["fundamental_snapshot"]
    faltan = [m for m in MAGNITUDES_OPCIONALES if FUNDAMENTALES.get(m, m) not in tabla.c]
    assert not faltan, f"sin columna en la tabla: {faltan}"


def test_un_tiempo_agotado_del_bce_sale_como_error_del_contrato(cfg):
    """El fallo que tumbo la etapa de divisas en produccion.

    `TimeoutError` NO es subclase de `URLError`, asi que el `except` del
    proveedor no lo capturaba: un tiempo agotado al LEER se escapaba crudo y el
    pipeline anotaba "TimeoutError" en lugar del error del contrato. Quien lea
    ese log no tiene forma de saber que fuente fallo ni por que.
    """
    import urllib.request

    from estrategia.datos.bce_proveedor import ProveedorBCE
    from estrategia.errores import ErrorDatos

    def falla(*_args, **_kwargs):
        raise TimeoutError("The read operation timed out")

    original = urllib.request.urlopen
    urllib.request.urlopen = falla
    try:
        with pytest.raises(ErrorDatos, match="no ha respondido"):
            ProveedorBCE(cfg)._pedir("USD", dt.date(2024, 1, 1), dt.date(2024, 2, 1))
    finally:
        urllib.request.urlopen = original


def test_el_bce_reintenta_antes_de_rendirse(cfg):
    """Una API publica y gratuita tiene malos ratos.

    Rendirse al primer intento convierte un tropiezo de treinta segundos en un
    dia entero sin tipos de cambio, y sin tipos de cambio no se puede valorar
    una cartera que mezcle dolares y reales.
    """
    import urllib.request

    from estrategia.datos import bce_proveedor
    from estrategia.datos.bce_proveedor import ProveedorBCE

    intentos = {"n": 0}

    class _Respuesta:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"CSV"

    def falla_dos_veces(*_args, **_kwargs):
        intentos["n"] += 1
        if intentos["n"] < 3:
            raise TimeoutError("lento")
        return _Respuesta()

    original_open = urllib.request.urlopen
    original_sleep = bce_proveedor.time.sleep
    urllib.request.urlopen = falla_dos_veces
    bce_proveedor.time.sleep = lambda _s: None  # sin esperas reales en el test
    try:
        assert ProveedorBCE(cfg)._pedir("USD", dt.date(2024, 1, 1), dt.date(2024, 2, 1)) == "CSV"
        assert intentos["n"] == 3, "tiene que haber reintentado dos veces"
    finally:
        urllib.request.urlopen = original_open
        bce_proveedor.time.sleep = original_sleep


def test_un_404_del_bce_no_se_reintenta(cfg):
    """Una serie que no existe no empieza a existir por insistir.

    Tres esperas de 180 segundos por una divisa mal escrita son nueve minutos
    tirados y un mensaje de error peor.
    """
    import urllib.error
    import urllib.request

    from estrategia.datos.bce_proveedor import ProveedorBCE
    from estrategia.errores import ErrorDatos

    intentos = {"n": 0}

    def cuatrocientos_cuatro(*_args, **_kwargs):
        intentos["n"] += 1
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)

    original = urllib.request.urlopen
    urllib.request.urlopen = cuatrocientos_cuatro
    try:
        with pytest.raises(ErrorDatos, match="no publica la serie"):
            ProveedorBCE(cfg)._pedir("XXX", dt.date(2024, 1, 1), dt.date(2024, 2, 1))
        assert intentos["n"] == 1, "un 404 no se reintenta"
    finally:
        urllib.request.urlopen = original


def test_con_divisas_false_deja_la_etapa_fuera(bd_ingesta, cfg):
    """El planificador descarga las divisas aparte, y esto es lo que se lo permite.

    No es un matiz: el primer mercado que cierra cada dia es la India, a las
    10:00 UTC, y el BCE publica sus tipos a media tarde. Si la ingesta de un
    mercado arrastrara las divisas, se anotarian como hechas con el tipo de AYER
    y las ejecuciones de la tarde las saltarian por idempotencia. El tipo de hoy
    no entraria hasta el dia siguiente.
    """
    import sqlalchemy as sa

    resultados = _ejecutar(bd_ingesta, cfg, con_divisas=False)
    etapas = [r.etapa for r in resultados]

    assert "divisas" not in etapas, f"la etapa no puede correr: {etapas}"
    assert "precios" in etapas, "pero el resto si"
    with sa.orm.Session(bd_ingesta) as s:
        assert s.execute(text("SELECT count(*) FROM fx_rate")).scalar() == 0


def test_por_defecto_las_divisas_si_entran(bd_ingesta, cfg):
    """El valor por defecto no cambia: quien llame sin pedir nada lo sigue
    teniendo todo. Sin este test, invertir el defecto pasaria inadvertido."""
    resultados = _ejecutar(bd_ingesta, cfg)
    assert "divisas" in [r.etapa for r in resultados]


def test_el_historico_por_defecto_llega_a_los_quince_anios_que_pide_d7():
    """D-7 exige 15 anios en dos mercados para poder entrenar. Con el valor
    anterior —8— no lo cumplia ninguno, y el limite lo ponia este numero y no el
    proveedor: se comprobo que yfinance sirve 20 anios de los cinco mercados.

    Va en una constante y no repartido por el script y el pipeline: con el valor
    en dos sitios basta con cambiar uno para que la descarga diaria y la de
    linea de ordenes cubran periodos distintos sin que nada avise.
    """
    from ml.condiciones import MINIMO_ANIOS
    from workers.pipeline.ingesta import ANOS_HISTORICO

    assert ANOS_HISTORICO >= MINIMO_ANIOS, "el historico descargado no puede quedarse corto de D-7"


def test_un_valor_sin_ni_un_precio_se_avisa_aunque_la_cobertura_sea_alta(bd_ingesta, cfg):
    """El caso de Tata Motors, 22/09/2026.

    `TATAMOTORS.NS` devuelve 404 en la fuente desde una accion corporativa. La
    India cubria 29 de 30 valores —el 97%, muy por encima del 80% de
    COBERTURA_MINIMA—, asi que no saltaba ni un aviso: el valor salia sin
    puntuar con su motivo escrito, que es lo correcto, y nadie se iba a enterar.

    Un ticker que no ha tenido NUNCA un precio no es un dia malo del proveedor,
    y por eso no se mide con la misma vara.
    """
    import sqlalchemy as sa

    _ejecutar(bd_ingesta, cfg)

    with sa.orm.Session(bd_ingesta) as s:
        # Se borran los precios de UN valor, dejando los demas intactos: la
        # cobertura sigue muy por encima del umbral y solo discrimina el aviso
        # nuevo. Con el viejo, esto pasaria sin decir nada.
        huerfano = s.execute(
            text(
                "SELECT s.ticker FROM security s WHERE s.market_id='es' "
                "AND s.asset_type <> 'index' ORDER BY s.ticker LIMIT 1"
            )
        ).scalar()
        s.execute(
            text(
                "DELETE FROM price WHERE security_id = "
                "(SELECT id FROM security WHERE ticker = :t)"
            ),
            {"t": huerfano},
        )
        s.execute(text("DELETE FROM data_quality_check"))
        s.commit()

    # Se relanza con `forzar=False`: la etapa de precios se salta por
    # idempotencia, y el aviso tiene que salir igual. Atado a la descarga,
    # desapareceria justo el dia que no se descarga.
    _ejecutar(bd_ingesta, cfg)

    with sa.orm.Session(bd_ingesta) as s:
        fila = s.execute(
            text(
                "SELECT status, detail, context FROM data_quality_check "
                "WHERE check_name='valores_sin_ni_un_precio' AND market_id='es'"
            )
        ).first()

    assert fila is not None, "la comprobacion tiene que registrarse siempre"
    assert fila[0] == "warning", f"con un huerfano hay que avisar: {fila}"
    assert huerfano in fila[1], "el aviso tiene que decir CUAL, no solo cuantos"
    assert huerfano in fila[2]["tickers"]
