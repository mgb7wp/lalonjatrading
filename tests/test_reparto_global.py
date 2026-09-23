"""Reparto de huecos global entre mercados (tarea B2).

El fallo que cubren: la revision semanal repartia los huecos mercado a mercado,
y cada mercado veia la cartera como si los demas no hubieran reservado nada.
Con cinco mercados activos podian salir hasta quince compras en una semana con
un maximo de ocho posiciones, se rebasaban los topes de sector y el efectivo, y
entraba antes quien iba primero en la lista es, us, de, in, br, no la mejor
candidata.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from estrategia import backtest as backtest_mod
from estrategia import config as config_mod
from estrategia.backtest import _repartir, _Ronda
from estrategia.calendario import Calendarios
from estrategia.cartera import Cartera
from estrategia.tipos import SenalTecnica

MERCADOS = ["es", "us", "de", "in", "br"]


def _con(cfg, *pares):
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


def _precio(mercado):
    # Brasil compra en lotes de 100: a 1 por accion, un lote cabe de sobra.
    return 1.0 if mercado == "br" else 100.0


def _senal(ticker, mercado, momentum, fecha):
    precio = _precio(mercado)
    # Un ATR amplio deja un stop lejano y posiciones pequenas: asi el tope de
    # posiciones se alcanza antes que el de efectivo.
    return SenalTecnica(
        ticker=ticker, mercado=mercado, fecha=fecha, cierre=precio,
        media_corta=precio * 0.98, media_larga=precio * 0.95, momentum=momentum,
        atr=precio * 0.06, historial_suficiente=True,
    )


class _VistaVacia:
    """`_repartir` solo mira la vista para valorar posiciones abiertas."""

    def serie(self, ticker):
        return None

    def posicion_hasta(self, ticker):
        return -1


@pytest.fixture(scope="module")
def semana(cfg):
    """Una semana real en la que los cinco mercados deciden y ejecutan."""
    cal = Calendarios(cfg, dt.date(2024, 5, 1), dt.date(2024, 7, 31))
    for corte in cal.cortes_semanales:
        decisiones = {m: cal.sesion_de_decision(m, corte) for m in MERCADOS}
        ejecuciones = {m: cal.sesion_de_ejecucion(m, corte) for m in MERCADOS}
        if all(decisiones.values()) and all(ejecuciones.values()):
            return cal, decisiones, ejecuciones
    raise AssertionError("no hay una semana con los cinco mercados")


def _ticker(m, i):
    # Los de Brasil empiezan por Z: asi, si ganan, no es por el desempate
    # alfabetico.
    return f"Z{m.upper()}{i}" if m == "br" else f"{m.upper()}{i}"


def _ronda_llena(cfg, semana, por_mercado=5, sector=lambda m, i: f"sector{i}"):
    """Ronda con muchas candidatas en cada mercado, todas con el regimen
    encendido. Las mejores notas estan en Brasil, el ultimo de la lista: tiene
    mas comprables, y su primera queda en un percentil mas alto que la primera
    de los demas mercados."""
    _, decisiones, ejecuciones = semana
    ronda = _Ronda()
    for m in MERCADOS:
        ronda.regimen[m] = True
        ronda.fx[cfg.reglas.mercado(m).divisa] = 1.0
        ronda.decision[m] = decisiones[m]
        ronda.ejecucion[m] = ejecuciones[m]
        n = por_mercado * 2 if m == "br" else por_mercado
        for i in range(n):
            ticker = _ticker(m, i)
            ronda.comprables[ticker] = _senal(ticker, m, 0.10 + 0.05 * i, decisiones[m])
            ronda.sectores[ticker] = sector(m, i)
    return ronda


def _posicion(ticker, mercado, sector, valor=10.0):
    from estrategia.tipos import Posicion

    return Posicion(
        ticker=ticker, mercado=mercado, sector=sector, divisa="EUR", acciones=1,
        fecha_entrada=dt.date(2024, 1, 2), precio_entrada_local=valor,
        precio_entrada_base=valor, fx_entrada=1.0, atr_entrada=1.0,
        stop_inicial_local=valor * 0.7, maximo_cierre_local=valor,
        stop_dinamico_local=valor * 0.7, coste_entrada_base=0.0,
        riesgo_teorico_pct=0.01, riesgo_efectivo_pct=0.01,
        ultimo_cierre_local=valor,
    )


def _repartir_y_leer(cfg, semana, ronda, cartera):
    cal, decisiones, _ = semana
    dia = max(decisiones.values())
    pendientes: dict = {}
    eventos: list = []
    _repartir(dia, ronda, _VistaVacia(), cal, cartera, cfg, pendientes, eventos)
    ordenes = [o for lista in pendientes.values() for o in lista]
    return ordenes, eventos


@pytest.fixture
def cfg_tecnico(cfg):
    # Solo la parte tecnica: asi la nota la marca el momentum y el test no
    # depende de fundamentales. Con un suelo de cohorte bajo, cada mercado se
    # percentila contra si mismo.
    return _con(cfg, "fundamental.activo", False, "fundamental.min_empresas_percentil", 2)


def test_una_semana_con_cinco_mercados_no_supera_ningun_tope(cfg_tecnico, semana):
    cfg = cfg_tecnico
    cartera = Cartera(efectivo=cfg.reglas.cartera.capital_inicial_eur)
    ronda = _ronda_llena(cfg, semana, sector=lambda m, i: f"sector{i % 3}")
    ordenes, _ = _repartir_y_leer(cfg, semana, ronda, cartera)

    reglas = cfg.reglas.cartera
    assert len(ordenes) == reglas.max_posiciones
    assert len({o.mercado for o in ordenes}) >= 3
    for m in MERCADOS:
        assert sum(o.mercado == m for o in ordenes) <= reglas.max_por_mercado
    for s in {o.sector for o in ordenes}:
        assert sum(o.sector == s for o in ordenes) <= reglas.max_por_sector
    # Cambio 1: el nominal de cada orden es acciones * precio.
    assert sum(o.acciones * _precio(o.mercado) for o in ordenes) <= cartera.efectivo


def test_el_efectivo_se_reserva_una_sola_vez(cfg_tecnico, semana):
    """Con poco efectivo, las compras de todos los mercados juntas caben en el."""
    cfg = cfg_tecnico
    efectivo = 3000.0
    # Mucho patrimonio invertido y poco efectivo: las posiciones se dimensionan
    # sobre el patrimonio, asi que el efectivo es lo que se acaba.
    cartera = Cartera(efectivo=efectivo)
    cartera.abrir(_posicion("GRANDE", "us", "otro", valor=17000.0), 0.0)
    ronda = _ronda_llena(cfg, semana)
    ordenes, eventos = _repartir_y_leer(cfg, semana, ronda, cartera)

    # Cambio 1: el nominal de cada orden es acciones * precio.
    nominal = sum(o.acciones * _precio(o.mercado) for o in ordenes)
    assert ordenes
    assert nominal <= efectivo
    assert any(e.motivo == "efectivo_insuficiente" for e in eventos)


def test_cuentan_las_posiciones_ya_abiertas_en_cualquier_mercado(cfg_tecnico, semana):
    """Los huecos libres son los de toda la cartera, no los de cada mercado."""
    cfg = cfg_tecnico
    reglas = cfg.reglas.cartera
    ronda = _ronda_llena(cfg, semana)
    cartera = Cartera(efectivo=reglas.capital_inicial_eur)
    # Posiciones abiertas repartidas por mercados distintos.
    for i in range(reglas.max_posiciones - 2):
        m = MERCADOS[i % len(MERCADOS)]
        cartera.abrir(_posicion(f"ABIERTA{i}", m, f"otro{i}"), 10.0)
    ordenes, _ = _repartir_y_leer(cfg, semana, ronda, cartera)
    assert len(ordenes) == 2
    for m in MERCADOS:
        total = cartera.n_en_mercado(m) + sum(o.mercado == m for o in ordenes)
        assert total <= reglas.max_por_mercado


def test_el_orden_lo_marca_la_puntuacion_y_no_la_lista_de_mercados(cfg_tecnico, semana):
    """Brasil va el ultimo en la lista, pero tiene las mejores candidatas."""
    cfg = cfg_tecnico
    cartera = Cartera(efectivo=cfg.reglas.cartera.capital_inicial_eur)
    ronda = _ronda_llena(cfg, semana)
    ordenes, _ = _repartir_y_leer(cfg, semana, ronda, cartera)

    primera = min(ordenes, key=lambda o: o.rango_asignacion)
    assert primera.rango_asignacion == 1
    assert primera.mercado == "br"
    # Y Brasil llena su tope, porque sus candidatas van por delante.
    assert sum(o.mercado == "br" for o in ordenes) == cfg.reglas.cartera.max_por_mercado
    # Los puestos del ranking son unicos y globales.
    rangos = [o.rango_asignacion for o in ordenes]
    assert len(set(rangos)) == len(rangos)


def test_las_ordenes_van_a_la_sesion_de_ejecucion_de_su_mercado(cfg_tecnico, semana):
    cfg = cfg_tecnico
    cal, decisiones, ejecuciones = semana
    cartera = Cartera(efectivo=cfg.reglas.cartera.capital_inicial_eur)
    ronda = _ronda_llena(cfg, semana)
    pendientes: dict = {}
    _repartir(max(decisiones.values()), ronda, _VistaVacia(), cal, cartera, cfg,
              pendientes, [])
    for clave, lista in pendientes.items():
        mercado, fecha = clave.split("|")
        assert fecha == ejecuciones[mercado].isoformat()
        assert all(o.mercado == mercado for o in lista)


def test_una_ya_en_cartera_cuenta_en_el_percentil_pero_no_se_rechaza(cfg_tecnico, semana):
    """La nota de una candidata no depende de lo que se tenga en cartera, y
    las que ya se tienen no llenan el registro de rechazos cada semana."""
    cfg = cfg_tecnico
    ronda = _ronda_llena(cfg, semana)
    vacia = Cartera(efectivo=cfg.reglas.cartera.capital_inicial_eur)
    ordenes_vacia, _ = _repartir_y_leer(cfg, semana, ronda, vacia)
    nota = {o.ticker: o.puntuacion_final for o in ordenes_vacia}

    con_una = Cartera(efectivo=cfg.reglas.cartera.capital_inicial_eur)
    con_una.abrir(_posicion("ZBR9", "br", "sector9"), 10.0)
    ordenes, eventos = _repartir_y_leer(cfg, semana, ronda, con_una)
    assert "ZBR9" not in {o.ticker for o in ordenes}
    assert not any(e.motivo == "ya_en_cartera" for e in eventos)
    for o in ordenes:
        if o.ticker in nota:
            assert o.puntuacion_final == pytest.approx(nota[o.ticker])


def test_el_percentil_recurre_al_bloque_con_la_cohorte_de_todos_los_mercados(
    cfg, semana
):
    """Un mercado con pocas comprables se percentila contra su bloque. Solo es
    posible si el ranking ve a la vez las candidatas de todos los mercados."""
    cfg = _con(cfg, "fundamental.activo", False)
    minimo = cfg.reglas.fundamental.min_empresas_percentil
    _, decisiones, ejecuciones = semana
    ronda = _Ronda()
    for m in ("es", "de"):
        ronda.regimen[m] = True
        ronda.fx["EUR"] = 1.0
        ronda.decision[m] = decisiones[m]
        ronda.ejecucion[m] = ejecuciones[m]
    # Alemania, con una sola comprable, la de peor momentum del bloque.
    ronda.comprables["DE0"] = _senal("DE0", "de", 0.01, decisiones["de"])
    ronda.sectores["DE0"] = "x"
    for i in range(minimo):
        t = f"ES{i}"
        ronda.comprables[t] = _senal(t, "es", 0.10 + 0.01 * i, decisiones["es"])
        ronda.sectores[t] = f"s{i}"

    from estrategia import seleccion as seleccion_mod

    cands = seleccion_mod.ordenar_candidatas(
        max(decisiones.values()), ronda.comprables, {}, ronda.sectores, cfg
    )
    de0 = next(c for c in cands if c.ticker == "DE0")
    # Sola en su mercado daria 50; contra el bloque es la peor.
    assert de0.percentil_momentum < 50.0


# --------------------------------------------------------------------------
# De punta a punta, sobre el backtest completo
# --------------------------------------------------------------------------


def test_el_backtest_nunca_supera_los_topes(cfg, instantanea, monkeypatch):
    """En todo el backtest, despues de cada compra, la cartera respeta
    `max_posiciones`, `max_por_sector`, `max_por_mercado` y el efectivo."""
    ajustada = _con(
        cfg,
        "fundamental.activo", False,
        "cartera.max_posiciones", 4,
        "cartera.max_por_mercado", 2,
        "cartera.max_por_sector", 2,
    )
    reglas = ajustada.reglas.cartera
    violaciones: list[str] = []
    abrir_original = Cartera.abrir

    def abrir_vigilado(self, posicion, desembolso):
        abrir_original(self, posicion, desembolso)
        if self.n_posiciones > reglas.max_posiciones:
            violaciones.append(f"{posicion.fecha_entrada}: {self.n_posiciones} posiciones")
        if self.n_en_mercado(posicion.mercado) > reglas.max_por_mercado:
            violaciones.append(f"{posicion.fecha_entrada}: tope de {posicion.mercado}")
        if self.n_en_sector(posicion.sector) > reglas.max_por_sector:
            violaciones.append(f"{posicion.fecha_entrada}: tope de {posicion.sector}")
        if self.efectivo < 0:
            violaciones.append(f"{posicion.fecha_entrada}: efectivo {self.efectivo:.2f}")

    monkeypatch.setattr(Cartera, "abrir", abrir_vigilado)
    r = backtest_mod.ejecutar(instantanea, ajustada, dt.date(2020, 1, 1), dt.date(2024, 12, 31))
    assert not violaciones, violaciones[:10]

    # Y el reparto es de verdad global: cada semana, una sola tanda de ordenes
    # con puestos de ranking unicos, aunque vengan de varios mercados.
    ev = r.eventos_df
    ordenes = ev[ev["tipo"] == "orden"]
    assert not ordenes.empty
    for _, grupo in ordenes.groupby("fecha"):
        assert grupo["rango"].is_unique
        assert len(grupo) <= reglas.max_posiciones
    assert (ordenes.groupby("fecha")["mercado"].nunique() > 1).any()
    assert pd.Series(r.curva["n_posiciones"]).max() <= reglas.max_posiciones
