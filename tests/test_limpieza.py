"""Limpieza de fallos menores (tarea B10).

Uno por fallo del plan:

- `foto` fallaba en una carpeta recien clonada.
- Una venta programada se perdia sin rastro si ese dia no habia precio.
- Un `except Exception` silencioso al pedir el tipo de cambio.
- `senales --detalle` filtraba los rechazos por la fecha equivocada.
- Los errores de configuracion salian como una traza cruda.
- Numeros sueltos en el codigo que tenian que estar en la configuracion.
- Codigo muerto en `tecnico.py`.
- Faltaban enes y tildes en los textos publicos.
"""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ayudas import instantanea_de, serie_precios
from estrategia import backtest as backtest_mod
from estrategia import cli
from estrategia import config as config_mod
from estrategia import informe as informe_mod
from estrategia import tecnico as tecnico_mod
from estrategia import universo as universo_mod
from estrategia.datos.almacen import Instantanea
from estrategia.errores import ErrorAnticipacion, ErrorConfiguracion, ErrorDatos
from estrategia.tipos import Evento

DIR_CONFIG_PRUEBA = Path(__file__).resolve().parent / "config_prueba"
RAIZ = Path(__file__).resolve().parents[1]


def _con(cfg, *pares):
    datos = cfg.reglas.model_dump(mode="json")
    for ruta, valor in zip(pares[::2], pares[1::2]):
        partes = ruta.split(".")
        actual = datos
        for p in partes[:-1]:
            actual = actual[p]
        actual[partes[-1]] = valor
    return cfg.model_copy(update={"reglas": config_mod.Reglas.model_validate(datos)})


@pytest.fixture
def config_copia(tmp_path):
    destino = tmp_path / "config"
    shutil.copytree(DIR_CONFIG_PRUEBA, destino)
    return destino


# --------------------------------------------------------------------------
# foto en una carpeta recien clonada
# --------------------------------------------------------------------------


def test_foto_funciona_sin_carpeta_de_datos(tmp_path, config_copia, monkeypatch):
    """En una copia recien clonada no existe `datos/`: antes `mkdtemp` fallaba."""
    datos = tmp_path / "clon" / "datos"
    assert not datos.exists()
    monkeypatch.setattr(cli, "DIR_FOTOS", datos / "fotos")
    reglas = config_copia / "reglas.yaml"
    reglas.write_text(
        reglas.read_text(encoding="utf-8").replace("nombre: yfinance", "nombre: sintetico", 1),
        encoding="utf-8",
    )
    assert cli.main(["--config", str(config_copia), "foto", "--anos", "1"]) == 0
    fotos = list((datos / "fotos").iterdir())
    assert len(fotos) == 1 and (fotos[0] / "precios.parquet").is_file()
    # Y no queda ninguna carpeta temporal a medias.
    assert [p.name for p in datos.iterdir()] == ["fotos"]


# --------------------------------------------------------------------------
# Venta programada sin precio
# --------------------------------------------------------------------------


def test_una_venta_sin_precio_se_aplaza_a_la_siguiente_sesion(cfg, instantanea):
    """Se busca una venta programada del backtest, se quita el precio del dia
    en que se ejecutaba y se vuelve a correr: la venta tiene que pasar a la
    siguiente sesion del mercado, no perderse."""
    inicio, fin = dt.date(2021, 1, 1), dt.date(2023, 12, 31)
    base = backtest_mod.ejecutar(instantanea, cfg, inicio, fin).eventos_df
    programadas = base[base["tipo"] == "salida_programada"]
    assert not programadas.empty, "el caso no se ejercita"
    salida = programadas.iloc[0]
    ventas = base[
        (base["tipo"] == "venta") & (base["ticker"] == salida["ticker"])
        & (base["fecha"] > salida["fecha"])
    ]
    dia_venta = ventas["fecha"].min()

    p = instantanea.precios
    sin_ese_dia = p[~((p["ticker"] == salida["ticker"]) & (p["fecha"] == dia_venta))]
    otra = Instantanea(
        precios=sin_ese_dia, fundamentales=instantanea.fundamentales, fx=instantanea.fx,
        sectores=instantanea.sectores, fecha_descarga=instantanea.fecha_descarga,
        origen=instantanea.origen,
    ).preparar(cfg)
    ev = backtest_mod.ejecutar(otra, cfg, inicio, fin).eventos_df

    aplazadas = ev[(ev["tipo"] == "venta_aplazada") & (ev["ticker"] == salida["ticker"])]
    assert not aplazadas.empty
    assert aplazadas.iloc[0]["fecha"] == dia_venta
    assert aplazadas.iloc[0]["motivo"] == salida["motivo"]
    despues = ev[
        (ev["tipo"] == "venta") & (ev["ticker"] == salida["ticker"])
        & (ev["fecha"] > dia_venta)
    ]
    assert not despues.empty
    assert despues.iloc[0]["motivo"] == salida["motivo"]


# --------------------------------------------------------------------------
# Tipos de cambio: sin except silencioso
# --------------------------------------------------------------------------


def test_sin_cambio_de_una_divisa_se_anota_el_motivo(cfg, instantanea):
    fx = instantanea.fx[instantanea.fx["divisa"] != "BRL"]
    sin_brl = Instantanea(
        precios=instantanea.precios, fundamentales=instantanea.fundamentales, fx=fx,
        sectores=instantanea.sectores, fecha_descarga=instantanea.fecha_descarga,
        origen=instantanea.origen,
    ).preparar(cfg)
    tecnico = _con(cfg, "fundamental.activo", False)
    ev = backtest_mod.ejecutar(sin_brl, tecnico, dt.date(2021, 1, 1), dt.date(2022, 12, 31)).eventos_df
    sin_cambio = ev[ev["tipo"] == "sin_tipo_de_cambio"]
    assert not sin_cambio.empty
    assert set(sin_cambio["mercado"]) == {"br"}
    assert sin_cambio["motivo"].str.contains("BRL").all()


class _VistaQueFalla:
    def __init__(self, error):
        self.error = error
        self._serie = SimpleNamespace(cierre_bruto=[10.0] * 5, volumen=[1e6] * 5)

    def serie(self, ticker):
        return self._serie

    def posicion_hasta(self, ticker):
        return 4

    def fx(self, *args, **kwargs):
        raise self.error


def test_la_liquidez_solo_se_traga_los_errores_de_datos(cfg):
    """Un error de datos deja el valor sin liquidez; uno de anticipacion es un
    fallo del codigo y tiene que saltar. Antes se tragaban los dos."""
    fecha = dt.date(2024, 6, 3)
    vista = _VistaQueFalla(ErrorDatos("no hay tipo de cambio de USD"))
    assert universo_mod.volumen_medio_base("X", "us", fecha, vista, cfg) == 0.0
    with pytest.raises(ErrorAnticipacion):
        universo_mod.volumen_medio_base(
            "X", "us", fecha, _VistaQueFalla(ErrorAnticipacion("futuro")), cfg
        )


# --------------------------------------------------------------------------
# senales --detalle
# --------------------------------------------------------------------------


def test_senales_detalle_ensena_los_rechazos_de_la_ultima_revision(cfg, monkeypatch, capsys):
    """La ultima revision es la del 7 de junio; despues hubo una venta el 11.
    Antes los rechazos se filtraban por el 11 y no salia ninguno."""
    d_revision, d_venta = dt.date(2024, 6, 7), dt.date(2024, 6, 11)
    eventos = [
        Evento(d_revision, "orden", "es", "AAA", detalles={"rango": 1}),
        Evento(d_revision, "rechazo", "es", "BBB", "tope_sector", {"rango": 2}),
        Evento(d_venta, "venta", "us", "CCC", "stop_intradia"),
    ]
    falsa = SimpleNamespace(
        preparar=lambda c: falsa, rango_precios=(dt.date(2020, 1, 1), d_venta)
    )
    monkeypatch.setattr(cli, "_cargar_instantanea", lambda args, c: falsa)
    monkeypatch.setattr(
        backtest_mod, "ejecutar",
        lambda *a, **k: SimpleNamespace(eventos_df=pd.DataFrame(
            [{"fecha": e.fecha, "tipo": e.tipo, "mercado": e.mercado, "ticker": e.ticker,
              "motivo": e.motivo, **e.detalles} for e in eventos]
        )),
    )
    args = cli.construir_parser().parse_args(["senales", "--detalle"])
    cli.cmd_senales(args, cfg)
    salida = capsys.readouterr().out
    assert f"revision del {d_revision}" in salida
    assert "AAA" in salida
    assert "Rechazos de esa revision" in salida and "BBB" in salida
    assert "CCC" not in salida


# --------------------------------------------------------------------------
# Errores de configuracion legibles
# --------------------------------------------------------------------------


def _romper(config, viejo, nuevo):
    reglas = config / "reglas.yaml"
    texto = reglas.read_text(encoding="utf-8")
    assert viejo in texto
    reglas.write_text(texto.replace(viejo, nuevo, 1), encoding="utf-8")


def test_un_valor_mal_escrito_da_un_mensaje_claro(config_copia, capsys):
    _romper(config_copia, "max_posiciones: 8", "max_posiciones: ocho")
    assert cli.main(["--config", str(config_copia), "universo"]) == 1
    err = capsys.readouterr().err
    assert "cartera.max_posiciones" in err
    assert "reglas.yaml" in err
    assert "Traceback" not in err


def test_una_clave_mal_escrita_dice_que_es_desconocida(config_copia):
    _romper(config_copia, "  peso_maximo: 0.15", "  peso_maxmo: 0.15")
    with pytest.raises(ErrorConfiguracion) as exc:
        config_mod.cargar(config_copia)
    texto = str(exc.value)
    assert "cartera.peso_maxmo: clave desconocida" in texto
    assert "cartera.peso_maximo: falta esta clave" in texto


def test_un_yaml_roto_dice_donde(config_copia):
    _romper(config_copia, "max_posiciones: 8", "max_posiciones: [8")
    with pytest.raises(ErrorConfiguracion, match="(?s)no es YAML valido.*line"):
        config_mod.cargar(config_copia)


def test_una_carpeta_sin_ficheros_da_un_mensaje_claro(tmp_path):
    with pytest.raises(ErrorConfiguracion, match="no existe el fichero"):
        config_mod.cargar(tmp_path)


# --------------------------------------------------------------------------
# Numeros que ahora salen de la configuracion
# --------------------------------------------------------------------------


def test_los_dias_sin_precio_salen_de_la_configuracion(cfg):
    ticker = cfg.universo.tickers()[0]
    mercado = cfg.universo.mercado_de_ticker[ticker]
    fechas = list(pd.bdate_range("2023-01-02", "2024-05-24").date)
    inst = instantanea_de(cfg, serie_precios(ticker, fechas, [10.0 + i * 0.01 for i in range(len(fechas))]))
    decision = dt.date(2024, 6, 7)  # 14 dias despues del ultimo precio
    vista = inst.vista(decision)
    assert tecnico_mod.senal(ticker, mercado, decision, vista, cfg) is None
    holgado = _con(cfg, "datos.dias_maximos_sin_precio", 20)
    assert tecnico_mod.senal(ticker, mercado, decision, vista, holgado) is not None


def test_la_alarma_de_consultas_sale_de_la_configuracion(cfg, instantanea):
    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2022, 1, 1), dt.date(2022, 6, 30))

    def gravedad(c, n):
        inf = informe_mod.construir(r, c, instantanea, consultas_validacion=n)
        return next(a.gravedad for a in inf.avisos if a.clave == "consultas_validacion")

    assert gravedad(cfg, 3) == "aviso"
    assert gravedad(cfg, 4) == "importante"
    assert gravedad(_con(cfg, "validacion.consultas_para_alarma", 1), 2) == "importante"


def test_el_margen_de_reserva_sale_de_la_configuracion(cfg):
    from estrategia import ordenes as ordenes_mod
    from estrategia.cartera import Cartera
    from estrategia.tipos import Candidata, SenalTecnica

    senal = SenalTecnica(
        ticker="X", mercado="es", fecha=dt.date(2024, 6, 7), cierre=100.0,
        media_corta=98.0, media_larga=95.0, momentum=0.2, atr=10.0,
        historial_suficiente=True,
    )
    cand = Candidata(
        ticker="X", mercado="es", sector="industrial", fecha_decision=dt.date(2024, 6, 7),
        puntuacion_fundamental=50.0, percentil_momentum=50.0, puntuacion_final=50.0,
        senal=senal, n_cohorte=10, cohorte_usada="mercado",
    )

    def asigna(c, efectivo):
        a = ordenes_mod.asignar(
            dt.date(2024, 6, 7), [cand], Cartera(efectivo=efectivo), {"es": True},
            {"EUR": 1.0}, 10_000.0, c,
        )
        return a.ordenes

    ordenes = asigna(cfg, 10_000.0)
    assert ordenes
    nominal = ordenes[0].acciones * 100.0
    justo = nominal * (1 + cfg.reglas.cartera.margen_reserva_pct) + cfg.reglas.costes.comision_fija_eur
    assert asigna(cfg, justo)
    # Con un margen mayor, ese mismo efectivo ya no llega.
    assert not asigna(_con(cfg, "cartera.margen_reserva_pct", 0.05), justo)


def test_el_aviso_de_periodo_muerto_sale_de_la_configuracion(cfg, instantanea):
    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2019, 1, 1), dt.date(2023, 12, 31))
    claves = lambda c: {a.clave for a in informe_mod.construir(r, c, instantanea).avisos}  # noqa: E731
    assert "periodo_muerto_inicial" in claves(cfg)
    assert "periodo_muerto_inicial" not in claves(
        _con(cfg, "metricas.fraccion_periodo_muerto_aviso", 1.0)
    )


# --------------------------------------------------------------------------
# Codigo muerto y textos publicos
# --------------------------------------------------------------------------


def test_tecnico_ya_no_duplica_los_indicadores():
    """Los indicadores viven en `indicadores.py`; las copias de `tecnico.py`
    no las usaba nadie y podian divergir sin que se notara."""
    for nombre in ("media_movil", "atr_wilder", "momentum_12_1", "_desplazar_meses"):
        assert not hasattr(tecnico_mod, nombre)


def test_los_textos_publicos_llevan_tildes_y_enes(cfg, instantanea):
    r = backtest_mod.ejecutar(instantanea, cfg, dt.date(2021, 1, 1), dt.date(2022, 12, 31))
    inf = informe_mod.construir(r, cfg, instantanea)
    texto = informe_mod.a_markdown(inf)
    from estrategia.informe_html import a_html

    html = a_html(inf)
    for publico in (texto, html):
        assert "Drawdown máximo" in publico
        assert "Exposición media" in publico
        assert "Drawdown maximo" not in publico
    assert "Por año" in texto and "Por ano" not in texto
    assert ">Año<" in html or "Año" in html
    panel = (RAIZ / "panel" / "app.py").read_text(encoding="utf-8")
    assert '"Señales"' in panel and '"Senales"' not in panel
