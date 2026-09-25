"""Proteger el periodo de validacion (tarea B9).

Tres fugas que gastaban el periodo reservado sin que quedara rastro:

- La fecha de corte se calculaba como una fraccion de las sesiones
  descargadas, asi que avanzaba cada semana: lo que ayer era validacion pasaba
  a ser diseno sin que nadie lo decidiera.
- `estrategia informe` mostraba por defecto el periodo entero ("todo"), que
  incluye la validacion, y no anotaba la consulta. Y el informe se genera y
  se publica cada semana.
- El panel ensenaba la validacion (vistas "todo" y "validacion", y el
  historial de ordenes de "Senales") sin anotar nada.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from estrategia import cli
from estrategia import config as config_mod
from estrategia import validacion as validacion_mod
from estrategia.datos.almacen import Instantanea
from estrategia.errores import ErrorConfiguracion

DIR_CONFIG_PRUEBA = Path(__file__).resolve().parent / "config_prueba"


def _con_corte(cfg, fecha):
    datos = cfg.reglas.model_dump(mode="json")
    datos["validacion"]["fecha_corte"] = fecha.isoformat()
    return cfg.model_copy(update={"reglas": config_mod.Reglas.model_validate(datos)})


def _recortada(instantanea, hasta):
    p = instantanea.precios
    return Instantanea(
        precios=p[p["fecha"] <= hasta],
        fundamentales=instantanea.fundamentales,
        fx=instantanea.fx,
        sectores=instantanea.sectores,
        fecha_descarga=instantanea.fecha_descarga,
        origen=instantanea.origen,
    )


# --------------------------------------------------------------------------
# La fecha de corte no se mueve
# --------------------------------------------------------------------------


def test_el_corte_no_se_mueve_cuando_llegan_datos_nuevos(cfg, instantanea):
    """Con la fraccion, medio ano mas de datos movia el corte unos cuatro
    meses hacia delante. Con la fecha fija, solo se alarga la validacion."""
    antes = validacion_mod.dividir(_recortada(instantanea, dt.date(2024, 6, 28)), cfg)
    despues = validacion_mod.dividir(instantanea, cfg)
    assert antes.corte == despues.corte
    assert despues.fin > antes.fin


def test_el_corte_es_la_primera_sesion_desde_la_fecha_configurada(cfg, instantanea):
    sabado = dt.date(2023, 3, 11)
    d = validacion_mod.dividir(instantanea, _con_corte(cfg, sabado))
    assert d.corte == dt.date(2023, 3, 13)
    sesiones = sorted(instantanea.precios["fecha"].unique())
    assert d.corte in sesiones


@pytest.mark.parametrize("fecha", [dt.date(2010, 1, 1), dt.date(2030, 1, 1)])
def test_una_fecha_de_corte_fuera_de_los_datos_es_un_error_claro(cfg, instantanea, fecha):
    with pytest.raises(ErrorConfiguracion, match="fecha_corte"):
        validacion_mod.dividir(instantanea, _con_corte(cfg, fecha))


def test_la_fecha_de_corte_es_obligatoria(cfg):
    datos = cfg.reglas.model_dump(mode="json")
    del datos["validacion"]["fecha_corte"]
    with pytest.raises(Exception, match="fecha_corte"):
        config_mod.Reglas.model_validate(datos)


def test_todo_tambien_toca_la_validacion(cfg, instantanea):
    d = validacion_mod.dividir(instantanea, cfg)
    assert d.toca_validacion("validacion")
    assert d.toca_validacion("todo")
    assert not d.toca_validacion("diseno")


# --------------------------------------------------------------------------
# El informe semanal ensena solo el diseno, y lo demas se anota
# --------------------------------------------------------------------------


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Carpetas temporales y una configuracion sintetica con el corte dentro de
    los dos anos que se descargan."""
    monkeypatch.setattr(cli, "DIR_CACHE", tmp_path / "datos" / "cache")
    monkeypatch.setattr(cli, "DIR_FOTOS", tmp_path / "datos" / "fotos")
    monkeypatch.setattr(cli, "DIR_RESULTADOS", tmp_path / "datos" / "resultados")
    monkeypatch.setattr(cli, "DIR_SITIO", tmp_path / "sitio")
    consultas = tmp_path / "datos" / "consultas.json"
    monkeypatch.setattr(cli, "RUTA_CONSULTAS", consultas)

    config = tmp_path / "config"
    shutil.copytree(DIR_CONFIG_PRUEBA, config)
    reglas = config / "reglas.yaml"
    corte = dt.date.today() - dt.timedelta(days=200)
    texto = reglas.read_text(encoding="utf-8")
    texto = texto.replace("nombre: yfinance", "nombre: sintetico", 1)
    texto = texto.replace("fecha_corte: 2023-03-13", f"fecha_corte: {corte.isoformat()}", 1)
    reglas.write_text(texto, encoding="utf-8")

    base = ["--config", str(config)]
    assert cli.main([*base, "datos", "--anos", "2"]) == 0
    return base, consultas, tmp_path / "datos" / "resultados", corte


def _n_consultas(ruta: Path) -> int:
    return len(json.loads(ruta.read_text(encoding="utf-8"))) if ruta.is_file() else 0


def test_el_informe_por_defecto_no_toca_la_validacion(entorno):
    base, consultas, resultados, corte = entorno
    assert cli.main([*base, "informe", "--formato", "md"]) == 0
    assert _n_consultas(consultas) == 0
    curva = pd.read_parquet(resultados / "curva_sintetico.parquet")
    # Ni un dia del periodo reservado en la curva (el primero es el propio corte).
    assert max(curva["fecha"]) <= corte + dt.timedelta(days=4)


def test_informe_todo_anota_la_consulta(entorno, capsys):
    base, consultas, _, _ = entorno
    assert cli.main([*base, "informe", "--periodo", "todo", "--formato", "md"]) == 0
    assert _n_consultas(consultas) == 1
    assert "periodo de validacion" in capsys.readouterr().out
    motivo = json.loads(consultas.read_text(encoding="utf-8"))[0]["motivo"]
    assert motivo == "informe --periodo todo"


def test_backtest_validacion_anota_y_diseno_no(entorno):
    base, consultas, _, _ = entorno
    assert cli.main([*base, "backtest"]) == 0
    assert _n_consultas(consultas) == 0
    assert cli.main([*base, "backtest", "--periodo", "validacion"]) == 0
    assert _n_consultas(consultas) == 1


# --------------------------------------------------------------------------
# El panel anota una vez por sesion
# --------------------------------------------------------------------------


def test_el_panel_anota_una_sola_vez_por_sesion(tmp_path):
    """Streamlit reejecuta todo con cada clic: abrir la validacion y mover un
    filtro no pueden contar como varias consultas."""
    registro = validacion_mod.RegistroConsultas(tmp_path / "consultas.json")
    sesion: dict = {}
    assert registro.anotar_una_vez(sesion, "validacion_abierta:x:todo", "panel --periodo todo")
    for _ in range(5):
        assert not registro.anotar_una_vez(sesion, "validacion_abierta:x:todo", "panel")
    assert registro.n == 1

    # Otra sesion (otro dia, otro navegador) es otra consulta.
    assert registro.anotar_una_vez({}, "validacion_abierta:x:todo", "panel --periodo todo")
    assert registro.n == 2


def test_el_panel_pide_confirmacion_y_no_muestra_historial_en_senales():
    """El panel no se puede ejecutar aqui, pero si comprobar su texto: la vista
    Backtest para si no se ha abierto la validacion, y Senales ya no ensena el
    historial de ordenes."""
    codigo = (Path(__file__).resolve().parents[1] / "panel" / "app.py").read_text(encoding="utf-8")
    assert "toca_validacion(periodo) and not abrir_validacion" in codigo
    assert "anotar_una_vez(st.session_state" in codigo
    assert "Historial de ordenes" not in codigo
