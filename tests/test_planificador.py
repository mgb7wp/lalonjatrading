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
- que las tareas lleven los ajustes que evitan duplicados y saltos;
- que puntuar este programado, y **despues** del ultimo cierre del dia.

Lo ultimo es de la segunda auditoria: el planificador ya funcionaba —las horas
de produccion coincidian con estas— pero `ejecutar_mercado` encadenaba ingesta e
indicadores y se paraba ahi. `scores.py` y `senales.py` existian y no los
llamaba nadie, asi que la web servia precios de hoy con scores de hace cinco
dias, y la India entera, recien cargada, daba `n: 0` en el ranking.
"""

from __future__ import annotations

import datetime as dt

import pytest

from workers.planificador import (
    HORA_DIVISAS,
    MARGEN_SCORES_MIN,
    MARGEN_TRAS_CIERRE_MIN,
    cierre_habitual,
    construir,
    ha_negociado,
    ultimo_cierre,
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


# --- Puntuar, una vez y al final ------------------------------------------


def en_utc(t, dia=MIERCOLES):
    from zoneinfo import ZoneInfo

    return dt.datetime.combine(dia, dt.time(t.hora, t.minuto), ZoneInfo(t.zona)).astimezone(dt.UTC)


def test_puntuar_esta_programado():
    """El fallo que destapo la segunda auditoria, en una linea.

    Habia cinco ingestas y ninguna tarea que puntuara: los scores solo cambiaban
    cuando alguien lanzaba el script a mano.
    """
    tareas = {t.nombre for t in construir(CALENDARIOS, MIERCOLES)}
    assert "scores" in tareas


def test_puntuar_va_despues_de_que_hayan_cerrado_los_cinco_mercados():
    """Si se puntuara antes del ultimo cierre, ese mercado entraria en el
    ranking con los precios de ayer y el score fechado hoy."""
    tareas = construir(CALENDARIOS, MIERCOLES)
    scores = next(t for t in tareas if t.nombre == "scores")
    ingestas = [t for t in tareas if t.mercado]

    assert scores.mercado is None, "no es de ningun mercado: puntua el universo"
    for t in ingestas:
        assert en_utc(scores) > en_utc(t), f"scores debe ir tras {t.nombre}"


def test_el_margen_de_puntuar_es_mayor_que_el_de_la_ingesta():
    """La ingesta solo necesita que el cierre este publicado; puntuar necesita
    que la descarga haya TERMINADO. Con el mismo margen, la tarea de scores
    correria a la vez que la ultima ingesta."""
    assert MARGEN_SCORES_MIN > MARGEN_TRAS_CIERRE_MIN

    tareas = construir(CALENDARIOS, MIERCOLES)
    scores = next(t for t in tareas if t.nombre == "scores")
    mercado, hora, minuto, zona = ultimo_cierre(CALENDARIOS, MIERCOLES)
    assert mercado == "br", "en septiembre el ultimo en cerrar es Sao Paulo"
    assert scores.zona == zona
    assert (scores.hora * 60 + scores.minuto) - (hora * 60 + minuto) == MARGEN_SCORES_MIN


def test_puntuar_va_en_hora_local_del_ultimo_mercado_y_no_en_utc():
    """Programarla en UTC la descolocaria una hora en cada cambio de horario, y
    en la direccion peor: puntuar antes de que el ultimo mercado descargue."""
    scores = next(t for t in construir(CALENDARIOS, MIERCOLES) if t.nombre == "scores")
    assert scores.zona == "America/Sao_Paulo"


def test_el_ultimo_en_cerrar_se_mide_en_utc_y_no_por_la_hora_local():
    """Brasil cierra a las 18:00 y Nueva York a las 16:00: comparando los
    numeros locales sale Brasil por la razon equivocada. En UTC son las 21:00 y
    las 20:00, y sale Brasil por la razon correcta.

    El caso que discrimina es Madrid, que cierra a las 17:30 locales —mas tarde
    que Nueva York— y a las 15:30 UTC, mucho antes.
    """
    mercado, _, _, _ = ultimo_cierre({"es": "XMAD", "us": "XNYS"}, MIERCOLES)
    assert mercado == "us", "Madrid cierra despues en local y mucho antes en UTC"


def test_la_tarea_de_scores_llama_a_puntuar_y_no_a_las_divisas():
    """El `if/else` sobre `tarea.mercado` mandaba a divisas cualquier tarea
    global nueva, en silencio y con el nombre correcto en el log."""
    from workers import runner

    p = construir_planificador(Planificador(), CALENDARIOS)
    registrada = p.tareas["scores"]["funcion"]
    # `_protegida` devuelve un cierre; la funcion envuelta vive en una de sus
    # celdas (la otra guarda los argumentos, que aqui van vacios).
    celdas = [c.cell_contents for c in registrada.__closure__]
    assert runner.ejecutar_scores in celdas
    assert runner.ejecutar_divisas not in celdas


def test_puntuar_no_filtra_por_mercado_y_emite_senales_despues():
    """Dos contratos en una: puntuar el universo entero (filtrar por mercado
    dejaria el ranking incompleto) y llamar a senales DESPUES de scores, porque
    `senales.ejecutar` busca la version del modelo que ya tiene scores de esa
    fecha y sin ellos devuelve cero sin explicar por que."""
    import inspect

    from workers import runner

    # Sin el docstring: explica el orden con las dos llamadas nombradas y al
    # reves, asi que leerlo entero mediria el texto y no el codigo.
    fuente = inspect.getsource(runner.ejecutar_scores).replace(
        runner.ejecutar_scores.__doc__ or "", ""
    )
    assert "mercados=" not in fuente, "se puntua el universo, no un mercado"
    assert fuente.index("scores.ejecutar") < fuente.index("senales.ejecutar")


@pytest.mark.parametrize(
    ("negocia_alguien", "abre_la_base"),
    [
        # Un dia en que no abre NADIE: no hay nada nuevo que puntuar.
        (False, False),
        # Cualquier otro dia si, aunque algun mercado este de festivo: un
        # festivo en Nueva York no puede borrar EE. UU. del ranking. Ese
        # mercado se puntua con su ultimo cierre conocido y repite score.
        (True, True),
    ],
)
def test_solo_un_dia_sin_sesion_en_ningun_mercado_se_salta_la_puntuacion(
    monkeypatch, negocia_alguien, abre_la_base
):
    """Se comprueba sobre la base de datos y no sobre el log.

    `_fabrica` se sustituye por algo que revienta: si el guardarrail no esta,
    saltara, y si esta de mas —saltandose dias que si habria que puntuar— el
    segundo caso no saltara. Sobre el log no valdria: otra bateria de tests deja
    el logging configurado y `caplog` no ve nada.
    """
    from backend.db import session as db
    from workers import planificador, runner

    def revienta():
        raise RuntimeError("abierta la base")

    monkeypatch.setattr(planificador, "ha_negociado", lambda *_: negocia_alguien)
    monkeypatch.setattr(db, "_fabrica", revienta)

    if abre_la_base:
        with pytest.raises(RuntimeError, match="abierta la base"):
            runner.ejecutar_scores()
    else:
        runner.ejecutar_scores()


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


def test_se_registran_las_cinco_ingestas_las_divisas_y_los_scores():
    p = construir_planificador(Planificador(), CALENDARIOS)
    assert set(p.tareas) == {f"ingesta:{m}" for m in CALENDARIOS} | {"divisas", "scores"}


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
