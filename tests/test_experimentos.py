"""Registro de experimentos de backtest (§23, riesgo RT-1).

Lo que se comprueba aqui no es que la tabla guarde filas: es que el RECUENTO de
filas signifique lo que tiene que significar. Un registro de experimentos cuyo
numero de filas no es el numero de experimentos distintos no sirve para lo unico
que existe, que es saber cuantas veces se ha buscado antes de encontrar.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa

from backend.db import experimentos
from backend.db.models import ModelVersion
from backend.db.models.enums import BacktestPeriod, ModelKind

DISENO_INICIO = dt.date(2015, 1, 1)
DISENO_FIN = dt.date(2021, 12, 31)
VALIDACION_INICIO = dt.date(2022, 1, 1)
VALIDACION_FIN = dt.date(2024, 12, 31)


@pytest.fixture
def modelo(sesion):
    mv = ModelVersion(name="equilibrado", version="9.9.9", kind=ModelKind.RULES.value)
    sesion.add(mv)
    sesion.flush()
    return mv


def _registrar(sesion, modelo, **cambios):
    base = {
        "model_version_id": modelo.id,
        "model_version": f"{modelo.name}:{modelo.version}",
        "period_kind": BacktestPeriod.DISENO.value,
        "period_start": DISENO_INICIO,
        "period_end": DISENO_FIN,
        "data_source": "sintetico",
        "universe_hash": "a" * 64,
        "universe_size": 138,
        "parameters": {"pesos": {"fundamental": 50, "tecnico": 35}},
        "metrics": {"sharpe": 1.2, "rentabilidad_anualizada": 0.11},
    }
    return experimentos.registrar(sesion, **(base | cambios))


# --- Lo que hace util al recuento ------------------------------------------


def test_repetir_el_mismo_experimento_no_cuenta_como_uno_nuevo(sesion, modelo):
    """Volver a ejecutar lo mismo no es haber probado otra cosa.

    Si cada ejecucion creara fila, el recuento contaria ejecuciones y no
    experimentos, y bastaria con reejecutar para inflar —o con reejecutar sin
    querer para falsear— la cifra que mide el riesgo de sobreajuste.
    """
    id1, nuevo1 = _registrar(sesion, modelo)
    id2, nuevo2 = _registrar(sesion, modelo)

    assert nuevo1 is True
    assert nuevo2 is False
    assert id1 == id2
    assert experimentos.experimentos_por_periodo(sesion) == {"diseno": 1}

    run_count = sesion.execute(
        sa.text("SELECT run_count FROM backtest_run WHERE id = :i"), {"i": id1}
    ).scalar()
    assert run_count == 2, "la reejecucion se anota, pero aparte"


def test_cambiar_un_solo_peso_si_cuenta_como_experimento_nuevo(sesion, modelo):
    """El coste de buscar queda anotado, se quiera o no.

    Es la mitad que de verdad protege: probar diez juegos de pesos deja diez
    filas, y esas diez filas son el contexto sin el cual el mejor Sharpe de los
    diez no se puede interpretar.
    """
    _registrar(sesion, modelo)
    _registrar(sesion, modelo, parameters={"pesos": {"fundamental": 51, "tecnico": 34}})

    assert experimentos.experimentos_por_periodo(sesion) == {"diseno": 2}


def test_el_orden_de_las_claves_no_cambia_la_huella(sesion, modelo):
    """Sin `sort_keys`, el mismo experimento contaria dos veces.

    Es un fallo silencioso: nada falla, solo que el numero que mide el
    sobreajuste sale mas alto de lo que es y deja de creerse.
    """
    _registrar(sesion, modelo, parameters={"a": 1, "b": 2})
    _registrar(sesion, modelo, parameters={"b": 2, "a": 1})

    assert experimentos.experimentos_por_periodo(sesion) == {"diseno": 1}


def test_lo_que_describe_la_ejecucion_no_cambia_la_huella(sesion, modelo):
    """La hora a la que se lanzo no es parte del experimento.

    Si lo fuera, cada ejecucion tendria huella distinta y el recuento volveria a
    contar ejecuciones.
    """
    _registrar(sesion, modelo, parameters={"pesos": {"x": 1}, "ejecutado_en": "10:00"})
    _registrar(sesion, modelo, parameters={"pesos": {"x": 1}, "ejecutado_en": "18:30"})

    assert experimentos.experimentos_por_periodo(sesion) == {"diseno": 1}


def test_datos_sinteticos_y_reales_no_son_el_mismo_experimento(sesion, modelo):
    """El fallo de la FASE 6 otra vez: una curva sintetica confundida con una real."""
    _registrar(sesion, modelo, data_source="sintetico")
    _registrar(sesion, modelo, data_source="yfinance")

    assert experimentos.experimentos_por_periodo(sesion) == {"diseno": 2}


# --- El guardarrail de RT-1 ------------------------------------------------


def test_se_puede_contar_cuantas_veces_se_miro_la_validacion(sesion, modelo):
    """La consulta que hace comprobable "el periodo de validacion esta cerrado".

    Sin esta cifra, la regla es una intencion. Con ella, es un numero que
    cualquiera puede mirar antes de creerse un resultado.
    """
    _registrar(sesion, modelo)
    _registrar(sesion, modelo, parameters={"pesos": {"z": 9}})
    _registrar(
        sesion,
        modelo,
        period_kind=BacktestPeriod.VALIDACION.value,
        period_start=VALIDACION_INICIO,
        period_end=VALIDACION_FIN,
    )

    recuento = experimentos.experimentos_por_periodo(sesion)
    assert recuento == {"diseno": 2, "validacion": 1}


# --- Lo que la base de datos no deja pasar ---------------------------------


def test_un_backtest_sin_version_de_modelo_no_entra(sesion, modelo):
    """Mismo criterio que un score huerfano: un numero sin procedencia no vale."""
    with pytest.raises(sa.exc.IntegrityError):
        _registrar(sesion, modelo, model_version_id=999_999)
        sesion.flush()


@pytest.mark.parametrize(
    "cambios, motivo",
    [
        ({"period_kind": "inventado"}, "periodo desconocido"),
        ({"period_start": DISENO_FIN, "period_end": DISENO_INICIO}, "periodo invertido"),
        ({"universe_size": 0}, "universo vacio"),
    ],
)
def test_se_rechaza_lo_que_no_significa_nada(sesion, modelo, cambios, motivo):
    with pytest.raises(ValueError):
        _registrar(sesion, modelo, **cambios)


def test_la_restriccion_del_periodo_tambien_esta_en_la_base_de_datos(sesion, modelo):
    """La validacion en Python protege de un error; el CHECK protege del resto.

    Cualquiera puede escribir en esta tabla con un INSERT a mano o desde otro
    proceso. Una regla que solo vive en la funcion de conveniencia es una regla
    que se salta sin enterarse.
    """
    with pytest.raises(sa.exc.IntegrityError):
        sesion.execute(
            sa.text(
                "INSERT INTO backtest_run (model_version_id, period_kind, period_start, "
                "period_end, data_source, universe_hash, universe_size, parameters, "
                "metrics, fingerprint, run_count) "
                "VALUES (:mv, 'diseno', '2021-12-31', '2015-01-01', 'sintetico', "
                "'b', 1, '{}', '{}', 'huella-a-mano', 1)"
            ),
            {"mv": modelo.id},
        )
        sesion.flush()
