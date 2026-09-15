"""Tests de los modulos de estrategia.

Cubren sobre todo los sitios donde una implementacion razonable puede estar mal
sin que se note: las trampas de signo del filtro fundamental, el trinquete del
stop, el tope de peso que tapa al parametro de riesgo, y el impuesto espanol,
que solo grava las compras, solo de la lista anual y solo desde 2021.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from estrategia import costes as costes_mod
from estrategia import fundamental as fundamental_mod
from estrategia import indicadores as ind_mod
from estrategia import riesgo as riesgo_mod
from estrategia import salidas as salidas_mod
from estrategia.cartera import Cartera
from estrategia.ordenes import asignar
from estrategia.sectores import MapaSectores
from estrategia.tipos import Candidata, MotivoRechazo, Posicion, SenalTecnica


# --------------------------------------------------------------------------
# Indicadores
# --------------------------------------------------------------------------


def test_atr_de_wilder_contra_un_caso_calculado_a_mano():
    """El ATR de Wilder no es una media movil simple del rango.

    Se siembra con la media de los primeros `periodo` rangos y despues se
    suaviza. Los dos stops dependen de este numero, asi que se fija el convenio.
    """
    maximos = np.array([10.0, 11.0, 12.0, 11.5, 13.0, 12.5])
    minimos = np.array([9.0, 10.0, 10.5, 10.0, 11.0, 11.5])
    cierres = np.array([9.5, 10.5, 11.5, 10.5, 12.5, 12.0])

    atr = ind_mod.atr_wilder_vector(maximos, minimos, cierres, periodo=3)
    # Rangos verdaderos: max(H-L, |H-Cprev|, |L-Cprev|)
    rangos = [
        max(11 - 10, abs(11 - 9.5), abs(10 - 9.5)),       # 1.5
        max(12 - 10.5, abs(12 - 10.5), abs(10.5 - 10.5)), # 1.5
        max(11.5 - 10, abs(11.5 - 11.5), abs(10 - 11.5)), # 1.5
    ]
    assert atr[3] == pytest.approx(float(np.mean(rangos)))

    siguiente = max(13 - 11, abs(13 - 10.5), abs(11 - 10.5))
    assert atr[4] == pytest.approx((atr[3] * 2 + siguiente) / 3)
    assert np.isnan(atr[0]) and np.isnan(atr[2])


def test_media_movil_necesita_la_ventana_completa():
    v = np.arange(1.0, 11.0)
    ma = ind_mod.media_movil_vector(v, 3)
    assert np.isnan(ma[0]) and np.isnan(ma[1])
    assert ma[2] == pytest.approx(2.0)
    assert ma[9] == pytest.approx(9.0)


def test_el_momentum_excluye_el_mes_mas_reciente():
    """El 12-1 mide de hace 12 meses a hace 1, no hasta hoy."""
    fechas = [dt.date(2022, 1, 1) + dt.timedelta(days=i) for i in range(400)]
    cierres = np.linspace(100.0, 200.0, 400)
    mom = ind_mod.momentum_vector(np.array(fechas), cierres, meses=12, excluir_meses=1)

    i = 380
    f = fechas[i]
    # El extremo superior es hace un mes, no hoy.
    j_fin = max(k for k, x in enumerate(fechas) if x <= ind_mod._desplazar_meses(f, -1))
    j_ini = max(k for k, x in enumerate(fechas) if x <= ind_mod._desplazar_meses(f, -12))
    assert mom[i] == pytest.approx(cierres[j_fin] / cierres[j_ini] - 1.0)
    assert mom[i] != pytest.approx(cierres[i] / cierres[j_ini] - 1.0)


# --------------------------------------------------------------------------
# Fundamental: las trampas de signo
# --------------------------------------------------------------------------


def _ratios(**kwargs):
    base = dict(
        ticker="X", roe=0.20, margen_operativo=0.15, crecimiento_ventas_3a=0.05,
        flujo_caja_libre=100.0, deuda_neta_ebitda=1.0, ev_ebit=12.0,
        fin_periodo=dt.date(2023, 12, 31), fecha_publicacion=dt.date(2024, 4, 30),
        origen_pit="reconstruido",
    )
    base.update(kwargs)
    return fundamental_mod.Ratios(**base)


def test_un_ebit_negativo_no_convierte_la_empresa_en_barata(cfg):
    """EV/EBIT con EBIT negativo sale negativo y un percentil inverso ingenuo
    lo leeria como "la mas barata del mercado"."""
    fila = pd.DataFrame([{
        "ticker": "X", "fin_periodo": dt.date(2023, 12, 31), "periodo": "anual",
        "fecha_publicacion": dt.date(2024, 4, 30), "origen_pit": "reconstruido",
        "roe": 0.2, "margen_operativo": 0.15, "ventas": 1000.0,
        "flujo_caja_libre": 50.0, "deuda_neta": 100.0, "ebitda": 200.0,
        "ebit": -150.0, "ev": 1000.0, "patrimonio_neto": 500.0,
    }] * 4)
    fila["fin_periodo"] = [dt.date(y, 12, 31) for y in (2020, 2021, 2022, 2023)]
    r = fundamental_mod.ratios_de("X", fila, cfg, dt.date(2024, 6, 1))
    assert r is not None
    assert r.ev_ebit is None, "con EBIT negativo no hay EV/EBIT utilizable"


def test_un_ebitda_negativo_hace_fallar_el_filtro_de_deuda(cfg):
    """Deuda/EBITDA con EBITDA negativo sale negativo y pasaria un '<= 3.0'."""
    fila = pd.DataFrame([{
        "ticker": "X", "fin_periodo": dt.date(y, 12, 31), "periodo": "anual",
        "fecha_publicacion": dt.date(2024, 4, 30), "origen_pit": "reconstruido",
        "roe": 0.2, "margen_operativo": 0.15, "ventas": 1000.0,
        "flujo_caja_libre": 50.0, "deuda_neta": 600.0, "ebitda": -200.0,
        "ebit": 150.0, "ev": 1000.0, "patrimonio_neto": 500.0,
    } for y in (2020, 2021, 2022, 2023)])
    r = fundamental_mod.ratios_de("X", fila, cfg, dt.date(2024, 6, 1))
    assert r is not None and r.deuda_neta_ebitda is None
    aprueba, motivo = fundamental_mod.aprueba_minimos(r, "industrial", cfg)
    assert not aprueba and motivo == MotivoRechazo.SIN_DATO_FUNDAMENTAL


def test_un_patrimonio_negativo_invalida_el_roe(cfg):
    """Perdidas divididas por patrimonio negativo dan un ROE positivo."""
    fila = pd.DataFrame([{
        "ticker": "X", "fin_periodo": dt.date(y, 12, 31), "periodo": "anual",
        "fecha_publicacion": dt.date(2024, 4, 30), "origen_pit": "reconstruido",
        "roe": 0.35, "margen_operativo": 0.15, "ventas": 1000.0,
        "flujo_caja_libre": 50.0, "deuda_neta": 100.0, "ebitda": 200.0,
        "ebit": 150.0, "ev": 1000.0, "patrimonio_neto": -400.0,
    } for y in (2020, 2021, 2022, 2023)])
    r = fundamental_mod.ratios_de("X", fila, cfg, dt.date(2024, 6, 1))
    assert r is not None and r.roe is None
    aprueba, _ = fundamental_mod.aprueba_minimos(r, "industrial", cfg)
    assert not aprueba


def test_la_caja_neta_si_debe_pasar(cfg):
    """Deuda neta negativa es caja neta: una empresa sin deuda, y eso es bueno.

    Esta escrito como test para que nadie lo "arregle" pensando que es un fallo.
    """
    aprueba, _ = fundamental_mod.aprueba_minimos(
        _ratios(deuda_neta_ebitda=-0.8), "industrial", cfg
    )
    assert aprueba


def test_las_electricas_admiten_mas_deuda(cfg):
    """La excepcion de sector del documento: 5,0 en vez de 3,0."""
    ratios = _ratios(deuda_neta_ebitda=4.2)
    assert not fundamental_mod.aprueba_minimos(ratios, "industrial", cfg)[0]
    assert fundamental_mod.aprueba_minimos(ratios, "electricas", cfg)[0]


def test_un_fundamental_caducado_deja_de_pasar(cfg):
    """Un dato de hace mas de `antiguedad_maxima_dias` no dice nada de hoy."""
    limite = cfg.reglas.fundamental.antiguedad_maxima_dias
    publicacion = dt.date(2022, 1, 1)
    fila = pd.DataFrame([{
        "ticker": "X", "fin_periodo": dt.date(2021, 12, 31), "periodo": "anual",
        "fecha_publicacion": publicacion, "origen_pit": "reconstruido",
        "roe": 0.2, "margen_operativo": 0.15, "ventas": 1000.0,
        "flujo_caja_libre": 50.0, "deuda_neta": 100.0, "ebitda": 200.0,
        "ebit": 150.0, "ev": 1000.0, "patrimonio_neto": 500.0,
    }])
    tarde = publicacion + dt.timedelta(days=limite + 1)
    r = fundamental_mod.ratios_de("X", fila, cfg, tarde)
    assert r is not None
    assert r.motivo_invalidez == MotivoRechazo.FUNDAMENTAL_CADUCADO


def test_los_percentiles_de_hazen_no_dan_ni_0_ni_100():
    """Con Hazen, una cohorte de uno da 50 y una de dos da 25 y 75.

    La alternativa, (rango-1)/(n-1), le pondria un 100 a la mejor de dos
    empresas mediocres, que luego competiria de tu a tu con la mejor de un
    mercado bien cribado.
    """
    uno = fundamental_mod.percentiles_hazen(pd.Series([5.0]))
    assert uno.iloc[0] == pytest.approx(50.0)

    dos = fundamental_mod.percentiles_hazen(pd.Series([1.0, 9.0]))
    assert sorted(dos.tolist()) == pytest.approx([25.0, 75.0])

    muchos = fundamental_mod.percentiles_hazen(pd.Series([1.0, 2.0, 3.0, 4.0]))
    assert muchos.min() > 0.0 and muchos.max() < 100.0


def test_los_empates_comparten_percentil():
    p = fundamental_mod.percentiles_hazen(pd.Series([5.0, 5.0, 9.0]))
    assert p.iloc[0] == pytest.approx(p.iloc[1])


# --------------------------------------------------------------------------
# Sectores
# --------------------------------------------------------------------------


def test_un_sector_desconocido_rechaza_en_vez_de_colarse(cfg):
    """Un sector sin traducir podria dejar entrar a un banco."""
    mapa = MapaSectores(cfg)
    c = mapa.clasificar("NOEXISTE", "Weird Sector Name")
    assert not c.admitido and c.motivo == MotivoRechazo.SECTOR_DESCONOCIDO
    assert "Weird Sector Name" in mapa.sin_mapear


def test_los_financieros_quedan_excluidos(cfg):
    mapa = MapaSectores(cfg)
    for proveedor in ("Financial Services", "Insurance", "Real Estate"):
        c = mapa.clasificar("X", proveedor)
        assert not c.admitido and c.motivo == MotivoRechazo.SECTOR_EXCLUIDO
    assert mapa.clasificar("X", "Utilities").admitido


# --------------------------------------------------------------------------
# Riesgo y tamano
# --------------------------------------------------------------------------


def test_el_tope_de_peso_tapa_al_parametro_de_riesgo(cfg):
    """Con ATR pequeno manda `peso_maximo`, no `riesgo.por_operacion`.

    Es la razon de que el informe distinga riesgo teorico de riesgo efectivo:
    sin eso, la sensibilidad de `riesgo.por_operacion` saldria plana y se leeria
    como robustez cuando lo que pasa es que el parametro no actuaba.
    """
    capital = 10_000.0
    precio = 100.0
    atr = 1.0  # 1% del precio: muy por debajo del 3,3% donde deja de topar
    stop = precio - cfg.reglas.salidas.stop_inicial_atr * atr

    t = riesgo_mod.calcular(capital, precio, stop, lote=1, cfg=cfg)
    assert t.limitada_por_peso_maximo
    assert t.nominal_base <= capital * cfg.reglas.cartera.peso_maximo + 1e-6
    assert t.riesgo_efectivo_pct < t.riesgo_teorico_pct

    # Con un ATR grande manda el riesgo y el tope no llega a morder.
    atr_grande = 8.0
    stop_grande = precio - cfg.reglas.salidas.stop_inicial_atr * atr_grande
    t2 = riesgo_mod.calcular(capital, precio, stop_grande, lote=1, cfg=cfg)
    assert not t2.limitada_por_peso_maximo
    assert t2.riesgo_efectivo_pct == pytest.approx(t2.riesgo_teorico_pct, rel=0.05)


def test_el_lote_redondea_a_la_baja(cfg):
    """El libro principal de B3 va en lotes de 100."""
    t = riesgo_mod.calcular(10_000.0, 100.0, 96.0, lote=100, cfg=cfg)
    assert t.acciones % 100 == 0
    suelto = riesgo_mod.calcular(10_000.0, 100.0, 96.0, lote=1, cfg=cfg)
    assert t.acciones <= suelto.acciones


def test_un_precio_demasiado_alto_da_cero_acciones(cfg):
    t = riesgo_mod.calcular(1_000.0, 5_000.0, 4_900.0, lote=1, cfg=cfg)
    assert t.acciones == 0


# --------------------------------------------------------------------------
# Salidas
# --------------------------------------------------------------------------


def _posicion(**kwargs):
    base = dict(
        ticker="X", mercado="es", sector="industrial", divisa="EUR", acciones=10,
        fecha_entrada=dt.date(2023, 1, 2), precio_entrada_local=100.0,
        precio_entrada_base=100.0, fx_entrada=1.0, atr_entrada=2.0,
        stop_inicial_local=96.0, maximo_cierre_local=100.0,
        stop_dinamico_local=94.0, coste_entrada_base=3.0,
        riesgo_teorico_pct=0.01, riesgo_efectivo_pct=0.008,
        ultimo_cierre_local=100.0,
    )
    base.update(kwargs)
    return Posicion(**base)


def test_un_hueco_bajista_sale_a_la_apertura(cfg):
    """Si abre por debajo del stop no habia forma de vender al stop."""
    pos = _posicion()
    sesion = pd.Series({"apertura": 90.0, "maximo": 91.0, "minimo": 88.0, "cierre": 89.0})
    salida = salidas_mod.evaluar_stop(pos, sesion)
    assert salida is not None
    assert salida.precio_local == pytest.approx(90.0)
    assert str(salida.motivo) == "stop_hueco"


def test_un_minimo_que_toca_el_stop_sale_al_stop(cfg):
    pos = _posicion()
    sesion = pd.Series({"apertura": 99.0, "maximo": 100.0, "minimo": 95.0, "cierre": 98.0})
    salida = salidas_mod.evaluar_stop(pos, sesion)
    assert salida is not None
    assert salida.precio_local == pytest.approx(96.0)
    assert str(salida.motivo) == "stop_intradia"


def test_el_stop_dinamico_nunca_baja(cfg):
    """Trinquete: aunque el ATR se dispare, el stop se queda donde estaba."""
    pos = _posicion()
    subida = salidas_mod.actualizar_trinquete(pos, 130.0, 2.0, cfg)
    assert subida.stop_dinamico_local == pytest.approx(130.0 - 3.0 * 2.0)

    # Mismo cierre, ATR mucho mayor: el calculo en bruto bajaria el stop.
    volatil = salidas_mod.actualizar_trinquete(subida, 130.0, 12.0, cfg)
    assert volatil.stop_dinamico_local == pytest.approx(subida.stop_dinamico_local)


def test_el_trinquete_usa_cierres_y_no_maximos(cfg):
    """Usar maximos intradia apretaria el stop y mejoraria el backtest."""
    pos = _posicion()
    actualizada = salidas_mod.actualizar_trinquete(pos, 110.0, 2.0, cfg)
    assert actualizada.maximo_cierre_local == pytest.approx(110.0)
    assert actualizada.stop_dinamico_local == pytest.approx(110.0 - 6.0)


def test_al_entrar_manda_el_stop_inicial(cfg):
    """Con 2 ATR abajo y 3 ATR desde el maximo, al principio gana el inicial."""
    precio, atr = 100.0, 2.0
    inicial = salidas_mod.stop_inicial(precio, atr, cfg)
    dinamico = salidas_mod.stop_dinamico_bruto(precio, atr, cfg)
    assert inicial > dinamico
    pos = _posicion(stop_inicial_local=inicial, stop_dinamico_local=dinamico)
    assert pos.stop_efectivo_local == pytest.approx(inicial)


# --------------------------------------------------------------------------
# Costes e impuestos
# --------------------------------------------------------------------------


def test_el_itf_espanol_solo_grava_compras_de_la_lista_y_desde_2021(cfg):
    es = cfg.impuestos.paises["es"]
    assert es.grava("ITX.MC", "compra", dt.date(2024, 6, 1))
    assert not es.grava("ITX.MC", "venta", dt.date(2024, 6, 1)), "solo compras"
    assert not es.grava("ITX.MC", "compra", dt.date(2019, 6, 1)), "no existia"
    # ArcelorMittal cotiza en Madrid pero tiene domicilio luxemburgues.
    assert not es.grava("MTS.MC", "compra", dt.date(2024, 6, 1))


def test_la_stt_india_grava_los_dos_lados(cfg):
    inn = cfg.impuestos.paises["in"]
    f = dt.date(2023, 6, 1)
    assert inn.grava("RELIANCE.NS", "compra", f)
    assert inn.grava("RELIANCE.NS", "venta", f)


def test_el_deslizamiento_es_mayor_en_emergentes(cfg):
    reglas = cfg.reglas.costes
    assert reglas.deslizamiento("br", "emergente") > reglas.deslizamiento("us", "desarrollado")


def test_el_deslizamiento_siempre_juega_en_contra(cfg):
    compra = costes_mod.precio_con_deslizamiento(100.0, "compra", "es", cfg)
    venta = costes_mod.precio_con_deslizamiento(100.0, "venta", "es", cfg)
    assert compra > 100.0 and venta < 100.0


def test_los_costes_se_desglosan(cfg):
    c = costes_mod.calcular("ITX.MC", "es", "compra", 1000.0, dt.date(2024, 6, 1), cfg)
    assert c.comision == pytest.approx(cfg.reglas.costes.comision_fija_eur)
    assert c.impuesto == pytest.approx(1000.0 * 0.002)
    assert c.total == pytest.approx(c.comision + c.deslizamiento + c.impuesto)


# --------------------------------------------------------------------------
# Asignacion de huecos
# --------------------------------------------------------------------------


def _candidata(ticker, mercado, sector, puntuacion, precio=100.0, atr=5.0):
    senal = SenalTecnica(
        ticker=ticker, mercado=mercado, fecha=dt.date(2023, 6, 16), cierre=precio,
        media_corta=precio * 0.98, media_larga=precio * 0.95, momentum=0.2,
        atr=atr, historial_suficiente=True,
    )
    return Candidata(
        ticker=ticker, mercado=mercado, sector=sector,
        fecha_decision=dt.date(2023, 6, 16), puntuacion_fundamental=puntuacion,
        percentil_momentum=puntuacion, puntuacion_final=puntuacion, senal=senal,
        n_cohorte=20, cohorte_usada="mercado",
    )


def test_una_candidata_que_no_cabe_se_salta_y_se_sigue_bajando(cfg):
    """"Mientras queden huecos" significa seguir por la lista, no parar."""
    cartera = Cartera(efectivo=100_000.0)
    candidatas = [
        _candidata("A", "es", "industrial", 90.0),
        _candidata("B", "es", "industrial", 85.0),
        _candidata("C", "es", "industrial", 80.0),
        _candidata("D", "es", "industrial", 75.0),  # 4a del sector Y del mercado
        # En otro mercado, para que lo unico que pueda pararla sea el sector,
        # que en su caso esta libre: debe entrar aunque D se haya caido.
        _candidata("E", "de", "salud", 70.0),
    ]
    a = asignar(
        dt.date(2023, 6, 16), candidatas, cartera, {"es": True, "de": True},
        {"EUR": 1.0}, 100_000.0, cfg,
    )
    comprados = [o.ticker for o in a.ordenes]
    assert "E" in comprados, "se corto en el primer rechazo en vez de seguir"
    assert "D" not in comprados
    # El sector se comprueba antes que el mercado, asi que D se cae por sector.
    assert any(r.ticker == "D" and r.motivo == MotivoRechazo.TOPE_SECTOR for r in a.rechazos)


def test_se_respeta_el_tope_por_mercado(cfg):
    cartera = Cartera(efectivo=100_000.0)
    candidatas = [
        _candidata(f"T{i}", "es", f"sector{i}", 90.0 - i) for i in range(5)
    ]
    a = asignar(
        dt.date(2023, 6, 16), candidatas, cartera, {"es": True}, {"EUR": 1.0},
        100_000.0, cfg,
    )
    assert len(a.ordenes) == cfg.reglas.cartera.max_por_mercado
    assert any(r.motivo == MotivoRechazo.TOPE_MERCADO for r in a.rechazos)


def test_el_regimen_apagado_bloquea_las_compras(cfg):
    cartera = Cartera(efectivo=100_000.0)
    candidatas = [_candidata("A", "es", "industrial", 90.0)]
    a = asignar(
        dt.date(2023, 6, 16), candidatas, cartera, {"es": False}, {"EUR": 1.0},
        100_000.0, cfg,
    )
    assert not a.ordenes
    assert a.rechazos[0].motivo == MotivoRechazo.REGIMEN_APAGADO


def test_el_desempate_es_estable(cfg):
    """Dos candidatas con la misma nota se ordenan por ticker.

    Sin esto, dos ejecuciones del mismo backtest pueden dar carteras distintas
    segun como ordene pandas, y el resultado deja de ser reproducible.
    """
    a = _candidata("ZZZ", "es", "industrial", 80.0)
    b = _candidata("AAA", "es", "industrial", 80.0)
    assert sorted([a, b], key=lambda c: c.clave_orden())[0].ticker == "AAA"
