"""Tests contra el sesgo de anticipacion.

El documento los pide explicitamente: "Ninguna decision puede usar datos
posteriores al momento en que se toma, y debe haber tests que lo comprueben".
Son el nucleo de la suite. Si uno de estos falla, los resultados de un backtest
no valen nada, por buenos que parezcan.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from estrategia import backtest as backtest_mod
from estrategia import fundamental as fundamental_mod
from estrategia import tecnico as tecnico_mod
from estrategia.errores import ErrorAnticipacion

from ayudas import instantanea_de, serie_precios


def _fila_fundamental(ticker, fin_periodo, publicacion, **extra):
    base = {
        "ticker": ticker,
        "fin_periodo": fin_periodo,
        "periodo": "anual",
        "fecha_publicacion": publicacion,
        "origen_fecha_publicacion": "estimada_retraso",
        "origen_pit": "reconstruido",
        "fecha_descarga": publicacion,
        "roe": 0.20,
        "margen_operativo": 0.15,
        "ventas": 1000.0,
        "flujo_caja_libre": 100.0,
        "deuda_neta": 200.0,
        "ebitda": 200.0,
        "ebit": 150.0,
        "ev": 1500.0,
        "patrimonio_neto": 500.0,
    }
    base.update(extra)
    return base


def test_un_fundamental_no_publicado_es_invisible(cfg):
    """Un dato con fecha de publicacion futura no se puede ver."""
    fechas = [dt.date(2023, 1, 2) + dt.timedelta(days=i) for i in range(10)]
    precios = serie_precios("ITX.MC", fechas, [10.0] * 10)
    fund = pd.DataFrame(
        [
            _fila_fundamental("ITX.MC", dt.date(2022, 12, 31), dt.date(2023, 1, 5)),
            # Este se publica DESPUES del corte: no debe aparecer.
            _fila_fundamental("ITX.MC", dt.date(2023, 3, 31), dt.date(2023, 1, 9)),
        ]
    )
    inst = instantanea_de(cfg, precios, fund)

    vista = inst.vista(dt.date(2023, 1, 6))
    visibles = vista.fundamentales("ITX.MC")
    assert len(visibles) == 1
    assert visibles.iloc[0]["fin_periodo"] == dt.date(2022, 12, 31)

    # Una vez pasada la fecha de publicacion, si aparece.
    assert len(inst.vista(dt.date(2023, 1, 9)).fundamentales("ITX.MC")) == 2


def test_el_retraso_de_publicacion_es_el_del_mercado(cfg):
    """India publica con su propio retraso, no con el general.

    `retraso_por_mercado` fija 105 dias para India; el valor por defecto anual
    es 120. Si se usara el general, la decision veria el dato quince dias tarde.
    """
    datos = cfg.reglas.datos
    assert datos.retraso("in", "anual") == 105
    assert datos.retraso("br", "anual") == 100
    assert datos.retraso("es", "anual") == datos.retraso_anual_dias == 120
    assert datos.retraso("us", "trimestral") == datos.retraso_trimestral_dias == 90


def test_pedir_un_precio_futuro_es_un_error(cfg):
    """La vista no es una convencion: no deja leer mas alla del corte."""
    fechas = [dt.date(2023, 1, 2) + dt.timedelta(days=i) for i in range(10)]
    inst = instantanea_de(cfg, serie_precios("ITX.MC", fechas, [10.0] * 10))
    vista = inst.vista(dt.date(2023, 1, 5))

    assert vista.precio_en("ITX.MC", dt.date(2023, 1, 5)) is not None
    with pytest.raises(ErrorAnticipacion):
        vista.precio_en("ITX.MC", dt.date(2023, 1, 8))


def test_la_vista_no_toca_fechas_posteriores_al_corte(cfg, instantanea):
    """Calcular una senal completa no mira ni un dia mas alla del corte."""
    corte = dt.date(2023, 6, 15)
    vista = instantanea.vista(corte)
    senal = tecnico_mod.senal("ITX.MC", "es", corte, vista, cfg)
    assert senal is not None
    assert vista.fecha_maxima_tocada is not None
    assert vista.fecha_maxima_tocada <= corte


def test_truncar_el_futuro_no_cambia_la_decision(cfg, instantanea, proveedor):
    """La senal en D es la misma con y sin los datos posteriores a D.

    Es la comprobacion mas directa de que no hay anticipacion: si algun calculo
    mirase hacia delante, recortar la serie cambiaria el resultado.
    """
    corte = dt.date(2023, 6, 15)
    completa = tecnico_mod.senal("ITX.MC", "es", corte, instantanea.vista(corte), cfg)

    recortados = instantanea.precios[instantanea.precios["fecha"] <= corte]
    inst_corta = instantanea_de(cfg, recortados)
    truncada = tecnico_mod.senal("ITX.MC", "es", corte, inst_corta.vista(corte), cfg)

    assert completa is not None and truncada is not None
    assert completa.cierre == pytest.approx(truncada.cierre)
    assert completa.media_larga == pytest.approx(truncada.media_larga)
    assert completa.media_corta == pytest.approx(truncada.media_corta)
    assert completa.momentum == pytest.approx(truncada.momentum)
    assert completa.atr == pytest.approx(truncada.atr)
    assert completa.comprable == truncada.comprable


def test_los_indicadores_no_dependen_del_tipo_de_cambio(cfg, instantanea, proveedor):
    """Medias, momentum y ATR se calculan en divisa local y no se mueven.

    El documento lo pide expresamente. Si alguien convirtiese la serie una linea
    antes de tiempo, la tendencia medida seria la del valor mezclada con la de
    su divisa, y este test lo cazaria.
    """
    corte = dt.date(2023, 6, 15)
    fx_original = instantanea.fx.copy()

    fx_doble = fx_original.copy()
    fx_doble["tasa"] = fx_doble["tasa"] * 2.0

    base = instantanea_de(cfg, instantanea.precios, instantanea.fundamentales, fx_original)
    otro = instantanea_de(cfg, instantanea.precios, instantanea.fundamentales, fx_doble)

    for ticker, mercado in (("RELIANCE.NS", "in"), ("PETR4.SA", "br"), ("MSFT", "us")):
        a = tecnico_mod.senal(ticker, mercado, corte, base.vista(corte), cfg)
        b = tecnico_mod.senal(ticker, mercado, corte, otro.vista(corte), cfg)
        assert a is not None and b is not None, ticker
        assert a.media_larga == pytest.approx(b.media_larga), ticker
        assert a.media_corta == pytest.approx(b.media_corta), ticker
        assert a.momentum == pytest.approx(b.momentum), ticker
        assert a.atr == pytest.approx(b.atr), ticker
        assert a.comprable == b.comprable, ticker


def test_el_tipo_de_cambio_para_decidir_es_el_de_la_vispera(cfg, instantanea):
    """Se decide con el cambio de D-1 y se valora con el de D.

    Los tipos de referencia del BCE se publican por la tarde: decidir a la hora
    del cierre indio con el cambio de hoy seria usar un dato que aun no existe.
    """
    assert cfg.reglas.datos.fx_decision_dia_anterior is True
    fecha = dt.date(2023, 6, 15)
    vista = instantanea.vista(fecha)

    hoy = vista.fx("USD", fecha)
    ayer = vista.fx("USD", fecha - dt.timedelta(days=1))
    decision = vista.fx_decision("USD", fecha, usar_dia_anterior=True)

    assert decision == pytest.approx(ayer)
    assert decision != pytest.approx(hoy)


def test_la_orden_se_ejecuta_en_la_apertura_siguiente(cfg, instantanea):
    """Nunca se compra al cierre con el que se genero la senal."""
    r = backtest_mod.ejecutar(
        instantanea, cfg, dt.date(2019, 1, 1), dt.date(2023, 12, 31)
    )
    ev = r.eventos_df
    ordenes = ev[ev["tipo"] == "orden"]
    compras = ev[ev["tipo"] == "compra"]
    assert not ordenes.empty and not compras.empty

    # Cada compra ocurre estrictamente despues de la orden que la origino.
    for _, compra in compras.head(40).iterrows():
        previas = ordenes[
            (ordenes["ticker"] == compra["ticker"])
            & (ordenes["fecha"] < compra["fecha"])
        ]
        assert not previas.empty, f"compra de {compra['ticker']} sin orden previa"

    # Y el retraso registrado entre decidir y ejecutar es de al menos una sesion.
    assert (ordenes["sesiones_de_retraso"] >= 1).all()


def test_el_stop_del_dia_no_usa_el_cierre_del_dia(cfg):
    """El nivel con que se juzga la sesion D viene de datos hasta D-1.

    Si el trinquete se actualizase antes de mirar el minimo, se estaria usando
    el cierre de hoy para decidir si hoy se toco el stop. Es un error de una
    linea que mejora todos los backtests en silencio.
    """
    from estrategia import salidas as salidas_mod
    from estrategia.tipos import Posicion

    pos = Posicion(
        ticker="X", mercado="es", sector="industrial", divisa="EUR", acciones=10,
        fecha_entrada=dt.date(2023, 1, 2), precio_entrada_local=100.0,
        precio_entrada_base=100.0, fx_entrada=1.0, atr_entrada=2.0,
        stop_inicial_local=96.0, maximo_cierre_local=100.0,
        stop_dinamico_local=94.0, coste_entrada_base=3.0,
        riesgo_teorico_pct=0.01, riesgo_efectivo_pct=0.008,
        ultimo_cierre_local=100.0,
    )
    # Sesion que cae hasta 95 (por debajo del stop de 96) y cierra en 110.
    sesion = pd.Series(
        {"apertura": 99.0, "maximo": 111.0, "minimo": 95.0, "cierre": 110.0}
    )
    salida = salidas_mod.evaluar_stop(pos, sesion)
    assert salida is not None, "el stop debe saltar aunque el dia cierre al alza"
    assert salida.precio_local == pytest.approx(96.0)

    # Si el trinquete se actualizara ANTES de juzgar la sesion, el stop subiria
    # a 110 - 3x2 = 104 usando el cierre de hoy, y la misma sesion se resolveria
    # de otra forma: salida a 99 en vez de a 96, y por otro motivo. Que el orden
    # cambie el resultado es justo lo que hace que el orden importe.
    tras_trinquete = salidas_mod.actualizar_trinquete(pos, 110.0, 2.0, cfg)
    assert tras_trinquete.stop_efectivo_local == pytest.approx(104.0)

    otra = salidas_mod.evaluar_stop(tras_trinquete, sesion)
    assert otra is not None
    assert otra.precio_local != pytest.approx(salida.precio_local)
    assert otra.motivo != salida.motivo
