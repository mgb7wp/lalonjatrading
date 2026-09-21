"""El pipeline diario, programado (arregla el agujero que destapo la auditoria).

El worker declaraba la dependencia de APScheduler y `docker-compose.yml`
prometia un pipeline diario, pero `runner.py` solo hacia `signal.pause()`: no
habia ni una tarea. En produccion eso se vio como dos mercados con datos y tres
vacios, y no por culpa del proveedor —los tres descargan bien— sino porque nadie
lanzaba la ingesta.

Lo que se comprueba aqui es lo que se rompe en silencio:

- que cada mercado se descargue tras SU cierre y no a una hora global;
- que las horas salgan del calendario de verdad y no esten escritas a mano;
- que las divisas vayan aparte, porque el BCE publica despues de que cierre la
  India;
- que un festivo no dispare una descarga;
- que las tareas lleven los ajustes que evitan duplicados y saltos.
"""

from __future__ import annotations

import datetime as dt

import pytest

from workers.planificador import (
    HORA_DIVISAS,
    MARGEN_TRAS_CIERRE_MIN,
    cierre_habitual,
    construir,
    ha_negociado,
)
from workers.runner import construir_planificador

#: El mapa real del proyecto. Si alguien anade un mercado y olvida su
#: calendario, estos tests fallan, que es justo lo que se quiere.
CALENDARIOS = {"es": "XMAD", "us": "XNYS", "de": "XETR", "in": "XBOM", "br": "BVMF"}

#: Un miercoles laborable en los cinco mercados, para que el calendario no
#: dependa de cuando se ejecuten los tests.
MIERCOLES = dt.date(2026, 9, 16)


class Planificador:
    """Un planificador de mentira: registra las tareas sin arrancar hilos."""

    def __init__(self) -> None:
        self.tareas: dict[str, dict] = {}

    def add_job(self, funcion, trigger, **kw):
        self.tareas[kw["id"]] = {"funcion": funcion, "trigger": trigger, **kw}

    def get_jobs(self):
        return list(self.tareas.values())


# --- Las horas salen del calendario ---------------------------------------


@pytest.mark.parametrize(
    ("codigo", "referencia", "habitual", "media_sesion"),
    [
        # El 31 de diciembre Madrid cierra a las 14:00.
        ("XMAD", dt.date(2025, 12, 31), (17, 30), (14, 0)),
        # Nueva York cierra a las 13:00 el dia despues de Accion de Gracias.
        ("XNYS", dt.date(2025, 11, 28), (16, 0), (13, 0)),
    ],
)
def test_el_cierre_habitual_no_es_el_de_una_media_sesion(
    codigo, referencia, habitual, media_sesion
):
    """La referencia ES una media sesion, a proposito.

    Si el cierre se tomara de la ultima sesion del calendario en lugar de la
    moda del trimestre, aqui saldria esa media sesion y la descarga de todo el
    anio se adelantaria tres horas y media.

    Hicieron falta dos intentos. La primera version usaba una fecha cualquiera;
    la segunda, el dia siguiente a la media sesion —y ese ya es una sesion
    normal, asi que las dos implementaciones coincidian—. Solo discrimina
    cuando la referencia cae EN la media sesion. Comprobado mutando el codigo
    las dos veces.
    """
    hora, minuto, _ = cierre_habitual(codigo, referencia)
    assert (hora, minuto) == habitual
    assert (hora, minuto) != media_sesion


def test_el_huso_es_el_del_mercado_y_no_utc():
    _, _, zona = cierre_habitual("XMAD", dt.date(2026, 1, 15))
    assert zona == "Europe/Madrid"


@pytest.mark.parametrize(
    ("mercado", "codigo", "zona"),
    [
        ("es", "XMAD", "Europe/Madrid"),
        ("us", "XNYS", "America/New_York"),
        ("in", "XBOM", "Asia/Kolkata"),
        ("br", "BVMF", "America/Sao_Paulo"),
    ],
)
def test_cada_mercado_trae_su_propio_huso(mercado, codigo, zona):
    _, _, leido = cierre_habitual(codigo, MIERCOLES)
    assert leido == zona


def test_cada_mercado_se_descarga_tras_su_cierre_y_con_margen():
    tareas = {t.nombre: t for t in construir(CALENDARIOS, MIERCOLES)}
    for mercado, codigo in CALENDARIOS.items():
        hora, minuto, zona = cierre_habitual(codigo, MIERCOLES)
        t = tareas[f"ingesta:{mercado}"]
        minutos_cierre = hora * 60 + minuto
        minutos_tarea = t.hora * 60 + t.minuto
        assert t.zona == zona, "la tarea va en el huso del mercado"
        assert minutos_tarea - minutos_cierre == MARGEN_TRAS_CIERRE_MIN


def test_los_mercados_se_reparten_a_lo_largo_del_dia():
    """La prueba de que el huso se respeta de verdad.

    Con las horas escritas a mano, o con un unico "cierre global", los cinco
    instantes coincidirian. Convertidos a UTC salen repartidos once horas.

    Salen CUATRO instantes y no cinco, y eso es correcto: Madrid y Fráncfort
    comparten huso y cierran a la vez. La primera version de este test exigia
    cinco y fallaba por eso —el codigo estaba bien y la aserción, mal—.
    """
    from zoneinfo import ZoneInfo

    def en_utc(t):
        local = dt.datetime.combine(MIERCOLES, dt.time(t.hora, t.minuto), ZoneInfo(t.zona))
        return local.astimezone(dt.UTC)

    por_mercado = {t.mercado: en_utc(t) for t in construir(CALENDARIOS, MIERCOLES) if t.mercado}

    assert len({m.strftime("%H:%M") for m in por_mercado.values()}) == 4
    assert por_mercado["es"] == por_mercado["de"], "mismo huso, mismo cierre"

    horas = (max(por_mercado.values()) - min(por_mercado.values())).total_seconds() / 3600
    assert horas > 10, f"la India y Brasil tienen que quedar lejos, y quedan a {horas:.0f} h"
    assert min(por_mercado, key=lambda m: por_mercado[m]) == "in"
    assert max(por_mercado, key=lambda m: por_mercado[m]) == "br"


# --- Las divisas van aparte ------------------------------------------------


def test_las_divisas_tienen_tarea_propia_y_posterior_al_bce():
    """El BCE publica a media tarde (CET) y la India cierra a las 10:00 UTC.

    Si las divisas viajaran con el primer mercado del dia, se anotarian como
    hechas con el tipo de AYER y las ejecuciones de la tarde las saltarian por
    idempotencia: el tipo de hoy no entraria hasta manana.
    """
    from zoneinfo import ZoneInfo

    tareas = construir(CALENDARIOS, MIERCOLES)
    divisas = next(t for t in tareas if t.nombre == "divisas")
    assert divisas.mercado is None
    assert (divisas.hora, divisas.minuto) == HORA_DIVISAS

    momento = dt.datetime.combine(
        MIERCOLES, dt.time(divisas.hora, divisas.minuto), ZoneInfo(divisas.zona)
    ).astimezone(dt.UTC)
    india = next(t for t in tareas if t.nombre == "ingesta:in")
    momento_india = dt.datetime.combine(
        MIERCOLES, dt.time(india.hora, india.minuto), ZoneInfo(india.zona)
    ).astimezone(dt.UTC)
    assert momento > momento_india, "las divisas, despues del primer mercado en cerrar"


def test_la_ingesta_de_un_mercado_no_arrastra_las_divisas():
    """La tarea de mercado llama a la ingesta con `con_divisas=False`.

    Se comprueba sobre la firma y no sobre una ejecucion porque lo que importa
    es el contrato: si manana alguien invierte el valor por defecto, este test
    lo caza sin necesidad de red ni de base de datos.
    """
    import inspect

    from workers import runner

    fuente = inspect.getsource(runner.ejecutar_mercado)
    assert "con_divisas=False" in fuente


# --- Un festivo no es un fallo --------------------------------------------


def test_un_domingo_no_dispara_descarga():
    assert ha_negociado("XMAD", MIERCOLES) is True
    assert ha_negociado("XMAD", dt.date(2026, 9, 20)) is False, "domingo"


def test_un_festivo_nacional_no_dispara_descarga():
    """El 1 de mayo Madrid no abre y Nueva York si. Un calendario global no
    distinguiria los dos casos."""
    assert ha_negociado("XMAD", dt.date(2026, 5, 1)) is False
    assert ha_negociado("XNYS", dt.date(2026, 5, 1)) is True


# --- El registro en APScheduler -------------------------------------------


def test_se_registran_las_cinco_ingestas_y_las_divisas():
    p = construir_planificador(Planificador(), CALENDARIOS)
    assert set(p.tareas) == {f"ingesta:{m}" for m in CALENDARIOS} | {"divisas"}


def test_las_tareas_llevan_los_ajustes_que_evitan_duplicados_y_saltos():
    """Sin estos tres, el planificador falla de formas que no se ven:

    - sin `coalesce`, un contenedor caido dos dias descarga dos veces al volver;
    - sin `max_instances=1`, una descarga lenta se solapa con la siguiente;
    - sin `misfire_grace_time`, un reinicio a la hora justa se salta el dia.
    """
    p = construir_planificador(Planificador(), CALENDARIOS)
    for nombre, tarea in p.tareas.items():
        assert tarea["coalesce"] is True, nombre
        assert tarea["max_instances"] == 1, nombre
        assert tarea["misfire_grace_time"] >= 600, nombre


def test_una_tarea_que_revienta_no_tumba_al_planificador():
    """Con cinco mercados y fuentes gratuitas, que la India no responda no puede
    dejar sin actualizar a EE. UU."""
    from workers.runner import _protegida

    def explota():
        raise RuntimeError("la fuente no responde")

    _protegida(explota)()  # no propaga


def test_las_tareas_solo_se_programan_de_lunes_a_viernes():
    p = construir_planificador(Planificador(), CALENDARIOS)
    for nombre, tarea in p.tareas.items():
        assert "mon-fri" in str(tarea["trigger"]), nombre
