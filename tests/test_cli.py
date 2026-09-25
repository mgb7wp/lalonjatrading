"""Linea de comandos: de donde salen los datos y adonde van.

El fallo que cubren estos tests es silencioso por naturaleza: si el CLI usa la
fuente sintetica por defecto, todo funciona, los informes salen bonitos y
ninguno describe un mercado real. Por eso se comprueba el camino entero, del
reparto de `reglas.yaml` a la carpeta de la cache y al sitio publicable.
"""

from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from estrategia import cli
from estrategia import config as config_mod
from estrategia.datos.enrutador import Enrutador
from estrategia.informe import es_sintetico

DIR_CONFIG_PRUEBA = Path(__file__).resolve().parent / "config_prueba"


def _con_reparto(cfg, **reparto):
    datos = cfg.reglas.model_dump(mode="json")
    datos["proveedor_datos"] = {"fundamentales_anos_disponibles": 4, **reparto}
    return cfg.model_copy(update={"reglas": config_mod.Reglas.model_validate(datos)})


def _args(*argv):
    # Basta con un subcomando cualquiera: lo que se mira es `--proveedor`.
    return cli.construir_parser().parse_args([*argv, "universo"])


@pytest.fixture
def carpetas(tmp_path, monkeypatch):
    """Las carpetas de datos del CLI, llevadas a un directorio temporal."""
    monkeypatch.setattr(cli, "DIR_CACHE", tmp_path / "datos" / "cache")
    monkeypatch.setattr(cli, "DIR_FOTOS", tmp_path / "datos" / "fotos")
    monkeypatch.setattr(cli, "DIR_RESULTADOS", tmp_path / "datos" / "resultados")
    monkeypatch.setattr(cli, "DIR_SITIO", tmp_path / "sitio")
    monkeypatch.setattr(cli, "RUTA_CONSULTAS", tmp_path / "datos" / "consultas.json")
    return tmp_path


@pytest.fixture
def config_sintetica(tmp_path):
    """Copia de la configuracion de prueba cuyo `reglas.yaml` pide la fuente
    sintetica. Es la forma de probar sin red que el CLI obedece a `reglas.yaml`
    cuando no se le pasa `--proveedor`."""
    destino = tmp_path / "config"
    shutil.copytree(DIR_CONFIG_PRUEBA, destino)
    reglas = destino / "reglas.yaml"
    texto = reglas.read_text(encoding="utf-8")
    assert "nombre: yfinance" in texto
    texto = texto.replace("nombre: yfinance", "nombre: sintetico", 1)
    # Estos tests descargan solo los dos ultimos anos: el corte tiene que caer
    # dentro de ellos.
    corte = date.today() - timedelta(days=365)
    texto = texto.replace("fecha_corte: 2023-03-13", f"fecha_corte: {corte.isoformat()}", 1)
    reglas.write_text(texto, encoding="utf-8")
    return destino


# --------------------------------------------------------------------------
# Por defecto manda reglas.yaml
# --------------------------------------------------------------------------


def test_sin_proveedor_no_se_fuerza_ninguna_fuente():
    assert cli.construir_parser().parse_args(["universo"]).proveedor is None


def test_sin_proveedor_se_usa_el_reparto_de_reglas(cfg):
    mixto = _con_reparto(cfg, nombre="yfinance", fundamentales="eodhd")
    e = cli._enrutador(mixto, None)
    assert e.nombre_de("precios") == "yfinance"
    assert e.nombre_de("fundamentales") == "eodhd"


def test_con_proveedor_se_fuerza_una_sola_fuente(cfg):
    mixto = _con_reparto(cfg, nombre="yfinance", fundamentales="eodhd")
    e = cli._enrutador(mixto, "sintetico")
    assert set(e.reparto.values()) == {"sintetico"}


# --------------------------------------------------------------------------
# La carpeta de cache es la misma para el CLI y el panel
# --------------------------------------------------------------------------


def test_la_cache_se_llama_como_el_origen(cfg):
    """El panel ofrece una opcion por carpeta de `datos/cache/`: el nombre tiene
    que ser el origen de los datos, el mismo que se anota en la instantanea."""
    assert cli._nombre_cache(_args(), cfg) == "yfinance"
    assert cli._nombre_cache(_args("--proveedor", "sintetico"), cfg) == "sintetico"

    mixto = _con_reparto(cfg, nombre="yfinance", fundamentales="eodhd")
    assert cli._nombre_cache(_args(), mixto) == "eodhd+yfinance"
    assert Enrutador(mixto).origen == "eodhd+yfinance"


def test_datos_escribe_donde_leen_los_demas_comandos(carpetas, config_sintetica):
    """Sin `--proveedor`: `datos` sigue a `reglas.yaml`, guarda en la carpeta
    de su origen y `universo` la encuentra sin que haya que repetir nada."""
    assert cli.main(["--config", str(config_sintetica), "datos", "--anos", "2"]) == 0
    cache = carpetas / "datos" / "cache"
    assert [d.name for d in cache.iterdir()] == ["sintetico"]
    assert (cache / "sintetico" / "precios.parquet").is_file()

    assert cli.main(["--config", str(config_sintetica), "universo"]) == 0


def test_sin_datos_en_cache_se_explica_que_descargar(carpetas, cfg, capsys):
    with pytest.raises(SystemExit):
        cli._cargar_instantanea(_args(), cfg)
    err = capsys.readouterr().err
    assert "'yfinance'" in err
    assert "estrategia datos" in err
    assert "--proveedor" not in err


# --------------------------------------------------------------------------
# Lo sintetico se marca y no se publica
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origen, esperado",
    [
        ("sintetico", True),
        ("eodhd+sintetico", True),
        ("sintetico+yfinance", True),
        ("yfinance", False),
        ("eodhd+yfinance", False),
        ("desconocido", False),
    ],
)
def test_un_origen_mixto_con_sintetico_es_sintetico(origen, esperado):
    assert es_sintetico(origen) is esperado


def test_un_informe_sintetico_no_llega_al_sitio(carpetas, config_sintetica):
    """`sitio/` se despliega entero: nada sintetico puede acabar dentro."""
    base = ["--config", str(config_sintetica)]
    assert cli.main([*base, "datos", "--anos", "2"]) == 0
    assert cli.main([*base, "informe", "--periodo", "diseno", "--formato", "ambos"]) == 0

    sitio = carpetas / "sitio"
    assert not sitio.exists() or not any(sitio.rglob("*.html"))

    resultados = carpetas / "datos" / "resultados"
    html = list(resultados.glob("informe_sintetico_*.html"))
    assert len(html) == 1
    assert "DATOS SINTÉTICOS" in html[0].read_text(encoding="utf-8")
    assert list(resultados.glob("informe_sintetico_*.md"))
    assert (resultados / "curva_sintetico.parquet").is_file()
