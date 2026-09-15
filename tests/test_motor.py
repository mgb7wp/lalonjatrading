"""Tests del motor completo, del calendario y de la arquitectura.

Incluye la comprobacion de que el codigo no lleva parametros incrustados. El
documento pide que "el codigo no debe contener numeros sueltos", y buscar
literales en el fuente no sirve: hay ceros y unos legitimos por todas partes.
Lo que si demuestra la propiedad es cambiar un valor en la configuracion y
comprobar que el comportamiento cambia. Si `media_larga` estuviera clavada a
200, bajarla a 50 no alteraria ninguna senal y el test caeria.
"""

from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path

import pytest

from estrategia import backtest as backtest_mod
from estrategia import config as config_mod
from estrategia import metricas as metricas_mod
from estrategia import tecnico as tecnico_mod
from estrategia import validacion as validacion_mod
from estrategia.calendario import Calendarios
from estrategia.informe import construir

INICIO = dt.date(2019, 1, 1)
FIN = dt.date(2024, 12, 31)


def _con(cfg, *pares):
    """Copia de la configuracion con uno o varios parametros cambiados.

    Acepta varios de golpe porque la configuracion se valida entera: bajar
    `max_posiciones` sin bajar a la vez `max_por_mercado` deja un estado que la
    propia validacion rechaza, con razon.

    Uso: `_con(cfg, "tecnico.media_larga", 120)` o
    `_con(cfg, "cartera.max_posiciones", 2, "cartera.max_por_mercado", 2)`.
    """
    datos = cfg.reglas.model_dump(mode="json")
    for ruta, valor in zip(pares[::2], pares[1::2]):
        partes = ruta.split(".")
        actual = datos
        for p in partes[:-1]:
            actual = actual[p]
        actual[partes[-1]] = valor
    return config_mod.Config(
        reglas=config_mod.Reglas.model_validate(datos),
        implementacion=cfg.implementacion,
        universo=cfg.universo,
        impuestos=cfg.impuestos,
        dir_config=cfg.dir_config,
    )


# --------------------------------------------------------------------------
# Los parametros salen de la configuracion, no del codigo
# --------------------------------------------------------------------------


def test_la_media_larga_sale_de_la_configuracion(cfg, instantanea):
    """Cambiar `tecnico.media_larga` cambia la media calculada."""
    corte = dt.date(2023, 6, 15)
    base = tecnico_mod.senal("ITX.MC", "es", corte, instantanea.vista(corte), cfg)

    otra_cfg = _con(cfg, "tecnico.media_larga", 120)
    otra_inst = type(instantanea)(
        precios=instantanea.precios, fundamentales=instantanea.fundamentales,
        fx=instantanea.fx, sectores=instantanea.sectores,
    ).preparar(otra_cfg)
    otra = tecnico_mod.senal("ITX.MC", "es", corte, otra_inst.vista(corte), otra_cfg)

    assert base is not None and otra is not None
    assert base.media_larga != pytest.approx(otra.media_larga)


def test_el_periodo_del_atr_sale_de_la_configuracion(cfg, instantanea):
    corte = dt.date(2023, 6, 15)
    base = tecnico_mod.senal("ITX.MC", "es", corte, instantanea.vista(corte), cfg)

    otra_cfg = _con(cfg, "tecnico.atr_periodo", 30)
    otra_inst = type(instantanea)(
        precios=instantanea.precios, fundamentales=instantanea.fundamentales,
        fx=instantanea.fx, sectores=instantanea.sectores,
    ).preparar(otra_cfg)
    otra = tecnico_mod.senal("ITX.MC", "es", corte, otra_inst.vista(corte), otra_cfg)
    assert base.atr != pytest.approx(otra.atr)


def test_los_multiplicadores_del_stop_salen_de_la_configuracion(cfg):
    from estrategia import salidas as salidas_mod

    apretado = _con(cfg, "salidas.stop_inicial_atr", 1.0)
    assert salidas_mod.stop_inicial(100.0, 2.0, cfg) == pytest.approx(96.0)
    assert salidas_mod.stop_inicial(100.0, 2.0, apretado) == pytest.approx(98.0)


def test_el_maximo_de_posiciones_sale_de_la_configuracion(cfg, instantanea):
    """Con menos huecos, el backtest hace menos operaciones."""
    fin = dt.date(2022, 12, 31)
    base = backtest_mod.ejecutar(instantanea, cfg, INICIO, fin)
    # Los topes por sector y por mercado no pueden superar el de posiciones, asi
    # que los tres bajan en la misma validacion.
    estrecha = _con(
        cfg,
        "cartera.max_posiciones", 2,
        "cartera.max_por_sector", 2,
        "cartera.max_por_mercado", 2,
    )
    pocas = backtest_mod.ejecutar(instantanea, estrecha, INICIO, fin)
    assert len(pocas.operaciones) < len(base.operaciones)


def test_una_configuracion_con_una_clave_de_mas_no_carga(cfg):
    """`extra=forbid`: una errata en el YAML falla al arrancar, no a mitad."""
    datos = cfg.reglas.model_dump(mode="json")
    datos["riesgo"]["por_operacon"] = 0.02  # errata a proposito
    with pytest.raises(Exception):
        config_mod.Reglas.model_validate(datos)


def test_unos_pesos_que_no_suman_uno_no_cargan(cfg):
    datos = cfg.reglas.model_dump(mode="json")
    datos["seleccion"]["pesos"]["fundamental"] = 0.9
    with pytest.raises(Exception):
        config_mod.Reglas.model_validate(datos)


def test_todo_mercado_necesita_su_indice_de_regimen(cfg):
    datos = cfg.reglas.model_dump(mode="json")
    del datos["tecnico"]["indices_regimen"]["br"]
    with pytest.raises(Exception):
        config_mod.Reglas.model_validate(datos)


# --------------------------------------------------------------------------
# Calendario
# --------------------------------------------------------------------------


def test_ningun_mercado_ejecuta_antes_del_corte_semanal(cfg):
    """La invariante que sostiene todo el ciclo semanal.

    Ninguna decision usa un cierre posterior al corte y ninguna ejecucion abre
    antes de el. Se comprueba sesion a sesion sobre los calendarios reales.
    """
    cal = Calendarios(cfg, dt.date(2021, 1, 1), dt.date(2024, 12, 31))
    comprobados = 0
    for corte in cal.cortes_semanales:
        for mercado in cal.mercados():
            d = cal.sesion_de_decision(mercado, corte)
            e = cal.sesion_de_ejecucion(mercado, corte)
            if d is None or e is None:
                continue
            assert cal.cierre_utc(mercado, d) <= corte
            assert cal.apertura_utc(mercado, e) > corte
            assert cal.sesiones_de_retraso(mercado, d, e) >= 1
            comprobados += 1
    assert comprobados > 800


def test_cada_mercado_tiene_su_propio_calendario(cfg):
    """Los festivos no coinciden, y por eso no hay un calendario global."""
    cal = Calendarios(cfg, dt.date(2024, 1, 1), dt.date(2024, 12, 31))
    sesiones = {m: set(cal.sesiones(m)) for m in cal.mercados()}
    assert sesiones["es"] != sesiones["us"]
    assert sesiones["in"] != sesiones["br"]
    # La union es mayor que cualquiera de las partes.
    assert len(cal.union_sesiones) > max(len(s) for s in sesiones.values())


# --------------------------------------------------------------------------
# Motor completo
# --------------------------------------------------------------------------


def test_el_backtest_es_reproducible(cfg, instantanea):
    """Dos ejecuciones identicas dan exactamente lo mismo."""
    fin = dt.date(2022, 12, 31)
    a = backtest_mod.ejecutar(instantanea, cfg, INICIO, fin)
    b = backtest_mod.ejecutar(instantanea, cfg, INICIO, fin)
    assert len(a.operaciones) == len(b.operaciones)
    assert a.curva["valor"].iloc[-1] == pytest.approx(b.curva["valor"].iloc[-1])
    assert [o.ticker for o in a.operaciones] == [o.ticker for o in b.operaciones]


def test_todo_precio_de_ejecucion_cae_dentro_del_rango_de_su_sesion(cfg, instantanea):
    """Invariante que caza una familia entera de fallos.

    Si una compra o una venta se hiciera a un precio fuera del rango de la
    sesion, el backtest estaria inventando liquidez. Se admite el margen del
    deslizamiento, que por definicion empeora el precio.
    """
    r = backtest_mod.ejecutar(instantanea, cfg, INICIO, dt.date(2023, 12, 31))
    holgura = max(cfg.reglas.costes.deslizamiento_pct_por_mercado.values()) + 1e-6

    revisadas = 0
    for op in r.operaciones:
        if op.motivo_salida.value in ("cierre_forzoso_sin_datos", "abierta_al_final"):
            continue
        serie = instantanea.series.get(op.ticker)
        if serie is None:
            continue
        for fecha, precio in (
            (op.fecha_entrada, op.precio_entrada_local),
            (op.fecha_salida, op.precio_salida_local),
        ):
            i = serie.posicion_exacta(fecha)
            if i < 0:
                continue
            bajo = float(serie.minimo[i]) * (1 - holgura)
            alto = float(serie.maximo[i]) * (1 + holgura)
            assert bajo <= precio <= alto, (
                f"{op.ticker} en {fecha}: precio {precio} fuera de [{bajo}, {alto}]"
            )
            revisadas += 1
    assert revisadas > 50


def test_no_se_compra_donde_el_regimen_esta_apagado(cfg, instantanea):
    """El generador apaga el indice indio de mayo de 2022 a febrero de 2023.

    Se usa India y no Espana a proposito: el tramo bajista espanol del generador
    cae en 2021, cuando la estrategia todavia no puede operar porque el
    crecimiento de ventas a tres anos necesita cuatro ejercicios publicados y
    aun no se habia publicado el cuarto.
    """
    desde, hasta = dt.date(2022, 6, 1), dt.date(2023, 1, 31)

    # El mecanismo, comprobado directamente: India apagada, los demas no.
    for f in (dt.date(2022, 7, 15), dt.date(2022, 11, 15)):
        regimen = tecnico_mod.regimen_por_mercado(f, instantanea.vista(f), cfg)
        assert regimen["in"] is False, f"India deberia estar apagada en {f}"
        assert any(v for m, v in regimen.items() if m != "in"), (
            "el regimen de un mercado no debe apagar a los demas"
        )

    # Y su efecto en el motor: ni una compra en India en ese tramo.
    r = backtest_mod.ejecutar(instantanea, cfg, INICIO, dt.date(2023, 12, 31))
    ev = r.eventos_df
    compras = ev[ev["tipo"] == "compra"]
    dentro = compras[
        (compras["mercado"] == "in")
        & (compras["fecha"] >= desde)
        & (compras["fecha"] <= hasta)
    ]
    assert dentro.empty, "se compro en India con el regimen apagado"

    # Mientras tanto, los demas mercados si operaron.
    otras = compras[
        (compras["mercado"] != "in")
        & (compras["fecha"] >= desde)
        & (compras["fecha"] <= hasta)
    ]
    assert not otras.empty, "el regimen de un mercado no debe frenar a los demas"


def test_el_informe_avisa_del_periodo_inicial_sin_operaciones(cfg, instantanea):
    """El tramo sin datos fundamentales no debe confundirse con estar en liquidez."""
    r = backtest_mod.ejecutar(instantanea, cfg, INICIO, dt.date(2023, 12, 31))
    inf = construir(r, cfg, instantanea)
    assert "periodo_muerto_inicial" in {a.clave for a in inf.avisos}


def test_la_cartera_respeta_sus_limites(cfg, instantanea):
    r = backtest_mod.ejecutar(instantanea, cfg, INICIO, dt.date(2023, 12, 31))
    ev = r.eventos_df
    compras = ev[ev["tipo"] == "compra"]
    ventas = ev[ev["tipo"] == "venta"]

    # Se reconstruye la cartera dia a dia a partir de los eventos.
    abiertas: dict[str, str] = {}
    eventos = ev[ev["tipo"].isin(["compra", "venta"])].sort_values("fecha")
    maximo = 0
    for _, e in eventos.iterrows():
        if e["tipo"] == "compra":
            abiertas[e["ticker"]] = e["mercado"]
        else:
            abiertas.pop(e["ticker"], None)
        maximo = max(maximo, len(abiertas))
        por_mercado: dict[str, int] = {}
        for m in abiertas.values():
            por_mercado[m] = por_mercado.get(m, 0) + 1
        assert max(por_mercado.values(), default=0) <= cfg.reglas.cartera.max_por_mercado
    assert maximo <= cfg.reglas.cartera.max_posiciones
    assert len(compras) > 0 and len(ventas) > 0


def test_el_efectivo_nunca_se_pone_en_negativo(cfg, instantanea):
    r = backtest_mod.ejecutar(instantanea, cfg, INICIO, dt.date(2023, 12, 31))
    assert (r.curva["efectivo"] >= -1e-6).all()


def test_sin_filtro_fundamental_hay_mas_operaciones(cfg, instantanea):
    """`fundamental.activo: false` deja pasar solo la pata tecnica.

    Es lo que permite validar calendarios, stops, costes y divisas sobre un
    historico largo, donde el proveedor gratuito no da fundamentales.
    """
    fin = dt.date(2022, 12, 31)
    con = backtest_mod.ejecutar(instantanea, cfg, INICIO, fin)
    sin = backtest_mod.ejecutar(
        instantanea, _con(cfg, "fundamental.activo", False), INICIO, fin
    )
    assert len(sin.operaciones) > len(con.operaciones)


def test_el_informe_saca_siempre_los_avisos_permanentes(cfg, instantanea):
    """El documento exige un aviso permanente sobre la repatriacion."""
    r = backtest_mod.ejecutar(instantanea, cfg, INICIO, dt.date(2022, 12, 31))
    inf = construir(r, cfg, instantanea)
    claves = {a.clave for a in inf.avisos}
    assert "repatriacion" in claves
    assert "supervivencia" in claves
    assert any(a.permanente for a in inf.avisos)
    permanente = next(a for a in inf.avisos if a.clave == "repatriacion")
    assert permanente.permanente


def test_el_informe_avisa_si_faltan_operaciones(cfg, instantanea):
    """Los minimos de `validacion` del documento."""
    r = backtest_mod.ejecutar(instantanea, cfg, INICIO, dt.date(2021, 6, 30))
    inf = construir(r, cfg, instantanea)
    claves = {a.clave for a in inf.avisos}
    assert "pocas_operaciones" in claves


def test_el_informe_marca_los_datos_sinteticos(cfg, instantanea):
    """Una curva sintetica confundida con una real es un error caro."""
    r = backtest_mod.ejecutar(instantanea, cfg, INICIO, dt.date(2022, 12, 31))
    inf = construir(r, cfg, instantanea)
    assert inf.sintetico
    from estrategia.informe import a_markdown

    assert "DATOS SINTETICOS" in a_markdown(inf)


# --------------------------------------------------------------------------
# Validacion
# --------------------------------------------------------------------------


def test_la_division_deja_la_fraccion_pedida_en_diseno(cfg, instantanea):
    d = validacion_mod.dividir(instantanea, cfg)
    fechas = sorted(instantanea.precios["fecha"].unique())
    antes = sum(1 for f in fechas if f <= d.corte)
    assert antes / len(fechas) == pytest.approx(
        cfg.reglas.validacion.fraccion_diseno, abs=0.02
    )
    assert d.inicio < d.corte < d.fin


def test_el_registro_de_consultas_cuenta(tmp_path):
    """Sin contador, "no consultes mucho el periodo de validacion" es un deseo."""
    reg = validacion_mod.RegistroConsultas(tmp_path / "consultas.json")
    assert reg.n == 0
    assert reg.anotar("prueba") == 1
    assert reg.anotar("otra") == 2
    assert reg.n == 2
    assert reg.leer()[0]["motivo"] == "prueba"


def test_la_sensibilidad_genera_variantes_de_los_dos_lados(cfg):
    vs = validacion_mod.variantes(cfg)
    assert len(vs) > 20
    rutas = {r for r, _, _ in vs}
    assert "tecnico.media_larga" in rutas
    assert "riesgo.por_operacion" in rutas
    # Los enteros se desplazan a enteros: 200 pasa a 150 y 250.
    largas = sorted(
        c.reglas.tecnico.media_larga for r, _, c in vs if r == "tecnico.media_larga"
    )
    assert largas == [150, 250]


# --------------------------------------------------------------------------
# Arquitectura
# --------------------------------------------------------------------------

CAPAS = [
    {"constantes", "errores", "tipos"},
    {"config"},
    {"indicadores"},
    {"calendario", "sectores"},
    {"universo", "fundamental", "tecnico"},
    {"seleccion", "riesgo", "salidas", "costes"},
    {"cartera"},
    {"ordenes"},
    {"backtest"},
    {"metricas"},
    {"validacion"},
    {"informe"},
    {"cli"},
]


def test_las_importaciones_respetan_las_capas():
    """Un modulo no puede importar de una capa posterior.

    Sin esta disciplina aparece el ciclo tipico de un proyecto asi: `cartera`
    necesita `riesgo`, que necesita `seleccion`, que necesita `cartera`.
    """
    raiz = Path(__file__).resolve().parents[1] / "src" / "estrategia"
    nivel = {m: i for i, capa in enumerate(CAPAS) for m in capa}

    problemas = []
    for fichero in raiz.glob("*.py"):
        modulo = fichero.stem
        if modulo not in nivel:
            continue
        arbol = ast.parse(fichero.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.ImportFrom) or nodo.level == 0:
                continue
            nombre = (nodo.module or "").split(".")[0]
            if nombre not in nivel:
                continue
            if nivel[nombre] > nivel[modulo]:
                problemas.append(f"{modulo} importa {nombre}, de una capa posterior")
    assert not problemas, "\n".join(problemas)


def test_tipos_no_importa_nada_del_paquete():
    """`tipos` es la hoja del grafo; si importa algo, el ciclo vuelve."""
    raiz = Path(__file__).resolve().parents[1] / "src" / "estrategia"
    arbol = ast.parse((raiz / "tipos.py").read_text(encoding="utf-8"))
    relativas = [
        n for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom) and n.level > 0
    ]
    assert not relativas, "tipos.py no debe importar nada del propio paquete"
