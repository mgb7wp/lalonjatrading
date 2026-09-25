"""Arranque del worker: el pipeline diario, programado.

Sin Celery a proposito (decision D-11): APScheduler dentro de un contenedor
cubre un pipeline diario con mucho menos coste operativo, y el presupuesto de
§50 es real. Celery entrara cuando haya una razon concreta —paralelismo entre
mercados, reintentos persistentes—, no por costumbre.

Cada mercado se procesa tras **su** cierre, con su calendario y su huso. No hay
un "cierre global": es la primera cosa que se rompe en una plataforma
multi-mercado escrita como si solo existiera Nueva York. El reparto de horas
vive en `planificador.py`, sacado de los calendarios de verdad.

Puntuar es la excepcion y va aparte: una sola tarea al final del dia, con todo
descargado, porque el ranking compara los cinco mercados y leerlo a media tarde
no puede ensenar solo los que ya han cerrado. Ver `ejecutar_scores`.

## Lo que este fichero hacia antes

`signal.pause()`. La dependencia de APScheduler estaba declarada y el comentario
de `docker-compose.yml` prometia un pipeline diario, pero no habia ni una tarea:
los datos solo entraban cuando alguien lanzaba el script a mano. Asi es como
produccion acabo con dos mercados cargados y tres vacios.

## Tres ajustes que no son adorno

- **`coalesce`**: si el contenedor ha estado caido dos dias, al arrancar se
  ejecuta UNA vez, no dos. Ponerse al dia disparando cada ejecucion perdida
  descarga lo mismo varias veces.
- **`max_instances=1`**: una descarga lenta no puede solaparse con la siguiente.
  Dos ingestas del mismo mercado a la vez compiten por las mismas filas.
- **`misfire_grace_time`**: un reinicio a la hora justa no puede saltarse el dia.
  Con el valor por defecto de APScheduler, una tarea que llega un segundo tarde
  se descarta en silencio.

Un fallo de un mercado se registra y **no** tumba el planificador ni a los
demas: con cinco mercados y fuentes gratuitas, que la India no responda no puede
dejar sin actualizar a EE. UU.
"""

from __future__ import annotations

import datetime as dt
import logging
import signal
import sys
from types import FrameType

log = logging.getLogger("worker")

#: Margen para una tarea que llega tarde (reinicio, maquina ocupada). Una hora:
#: mas alla de eso ya no es "tarde", es otro momento del dia.
GRACIA_SEG = 3600


def configurar_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"ts":"%(asctime)s","nivel":"%(levelname)s","servicio":"worker",'
        '"operacion":"%(name)s","mensaje":"%(message)s"}',
    )


def ejecutar_mercado(mercado_id: str, codigo_calendario: str) -> None:
    """Descarga un mercado y recalcula sus indicadores.

    Se construye todo dentro: el enrutador cachea lo que descarga —la ficha de
    la SEC, el fichero anual de la CVM— y esa cache tiene sentido dentro de una
    ejecucion, no arrastrada de un dia para otro.
    """
    from estrategia import config as core_config
    from estrategia.datos.enrutador import Enrutador

    from backend.db.session import _fabrica
    from workers.pipeline import indicadores, ingesta
    from workers.planificador import ha_negociado

    hoy = dt.date.today()
    if not ha_negociado(codigo_calendario, hoy):
        log.info("%s no ha negociado hoy (festivo o fin de semana); no se descarga", mercado_id)
        return

    cfg = core_config.cargar()
    # Esta tarea corre DESPUES del cierre del mercado (ver `planificador.py`), asi
    # que la sesion de hoy ya es definitiva. El enrutador aparta por defecto las
    # filas de hoy, porque a media sesion su "cierre" es el ultimo precio del
    # momento; aqui se le dice que hoy ya ha cerrado. Sin esto la plataforma iria
    # siempre un dia por detras.
    enrutador = Enrutador(cfg, hoy=hoy + dt.timedelta(days=1))
    with _fabrica()() as sesion:
        resultados = ingesta.ejecutar(
            sesion,
            cfg,
            enrutador,
            mercados=[mercado_id],
            # Las divisas tienen su propia tarea: ver el modulo del planificador.
            con_divisas=False,
        )
        calculados = indicadores.ejecutar(sesion, cfg, mercados=[mercado_id])
        ingesta.marcar_rancios(sesion, ingesta._umbrales_rancio(cfg))

    for r in resultados:
        log.info("%s", r)
    for mid, n in calculados.items():
        log.info("%s/indicadores: %s filas", mid, n)

    fallos = [r for r in resultados if r.estado == "failed"]
    if fallos:
        # Se registra y se sale sin excepcion: el planificador sigue vivo y los
        # demas mercados se ejecutan a su hora.
        log.error("%s: %s etapas han fallado", mercado_id, len(fallos))


def ejecutar_scores() -> None:
    """Puntua el universo entero y emite las senales del dia.

    ## Por que no va dentro de `ejecutar_mercado`

    Porque el ranking de §25 compara los cinco mercados y lee los scores de UNA
    fecha: puntuar tras cada cierre dejaria la tabla global incompleta once
    horas al dia. Va una vez, al final, con todo descargado. La cohorte de
    percentiles es `mercado x sector`, asi que puntuar junto o por separado da
    exactamente el mismo numero; lo que cambia es que la tabla este entera.

    ## Se puntua todo, tambien lo que hoy no ha negociado

    Un festivo en Nueva York no puede borrar EE. UU. del ranking. Un mercado sin
    sesion se puntua con su ultimo cierre conocido —que es lo que las etapas de
    precios e indicadores ya hacen, `date <= fecha`— y repite el score de ayer.
    Lo que si se comprueba es que haya negociado ALGUIEN: un 1 de enero no
    escribe una fila por valor para no decir nada nuevo.

    ## Senales despues de scores, en la misma sesion

    `senales.ejecutar` busca la version del modelo que de verdad tiene scores de
    esa fecha. Invertir el orden devuelve cero sin explicar por que.
    """
    from estrategia import config as core_config

    from backend.db.session import _fabrica
    from workers.pipeline import scores, senales
    from workers.planificador import ha_negociado

    hoy = dt.date.today()
    cfg = core_config.cargar()
    calendarios = dict(cfg.implementacion.calendarios)
    abiertos = [m for m, codigo in sorted(calendarios.items()) if ha_negociado(codigo, hoy)]
    if not abiertos:
        log.info("ningun mercado ha negociado hoy; no se puntua")
        return
    log.info("puntuando el universo; hoy han negociado: %s", ", ".join(abiertos))

    with _fabrica()() as sesion:
        puntuados = scores.ejecutar(sesion, cfg, fecha=hoy)
        emitidas = senales.ejecutar(sesion, cfg, fecha=hoy)

    for modelo, n in puntuados.items():
        log.info("scores/%s: %s filas", modelo, n)
    if not puntuados:
        log.error("no se ha puntuado ni un valor; el ranking se quedara en la fecha anterior")
    for motivo, n in emitidas.items():
        log.info("senales/%s: %s", motivo, n)


def ejecutar_divisas() -> None:
    """Solo los tipos de cambio, despues de que el BCE publique."""
    from estrategia import config as core_config
    from estrategia.datos.enrutador import Enrutador

    from backend.db.session import _fabrica
    from workers.pipeline import ingesta

    cfg = core_config.cargar()
    # Corre despues de que el BCE publique el cambio de hoy (ver
    # `planificador.py`): ese cambio ya es definitivo y no se aparta.
    enrutador = Enrutador(cfg, hoy=dt.date.today() + dt.timedelta(days=1))
    with _fabrica()() as sesion:
        # Sin mercados: solo corre la etapa global de divisas.
        resultados = ingesta.ejecutar(sesion, cfg, enrutador, mercados=[], con_divisas=True)
    for r in resultados:
        log.info("%s", r)


def _protegida(fn, *args):
    """Envuelve una tarea para que su excepcion no tumbe el planificador.

    APScheduler ya registra la excepcion, pero la deja pasar y el ruido acaba en
    un sitio distinto del resto de los logs. Aqui se anota con el nombre de la
    tarea, que es lo que se busca al depurar.
    """

    def corre():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 - un fallo de una tarea no para el resto
            log.exception("la tarea %s ha fallado", getattr(fn, "__name__", fn))

    return corre


def construir_planificador(scheduler, calendarios: dict[str, str]):
    """Registra las tareas en el planificador que se le pase.

    Recibe el `scheduler` en lugar de crearlo para poder probar el registro con
    uno de mentira, sin arrancar hilos ni esperar a las seis de la tarde.
    """
    from apscheduler.triggers.cron import CronTrigger

    from workers.planificador import construir

    #: Las tareas que no son de un mercado concreto, por nombre. Un `if/else`
    #: sobre `tarea.mercado` mandaba a divisas cualquier tarea global nueva, en
    #: silencio y con el nombre correcto en el log.
    globales = {"divisas": ejecutar_divisas, "scores": ejecutar_scores}

    for tarea in construir(calendarios):
        if tarea.mercado:
            funcion = _protegida(ejecutar_mercado, tarea.mercado, calendarios[tarea.mercado])
        else:
            funcion = _protegida(globales[tarea.nombre])
        scheduler.add_job(
            funcion,
            CronTrigger(
                day_of_week="mon-fri",
                hour=tarea.hora,
                minute=tarea.minuto,
                timezone=tarea.zona,
            ),
            id=tarea.nombre,
            name=tarea.nombre,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=GRACIA_SEG,
            replace_existing=True,
        )
        log.info("programada %s a las %s", tarea.nombre, tarea.cuando)
    return scheduler


def main() -> int:
    configurar_logging()

    from apscheduler.schedulers.blocking import BlockingScheduler
    from estrategia import config as core_config

    def parar(sig: int, _frame: FrameType | None) -> None:
        log.info("senal %s recibida, parando", sig)
        sys.exit(0)

    signal.signal(signal.SIGTERM, parar)
    signal.signal(signal.SIGINT, parar)

    cfg = core_config.cargar()
    calendarios = dict(cfg.implementacion.calendarios)

    scheduler = construir_planificador(BlockingScheduler(), calendarios)
    log.info("worker arrancado con %s tareas", len(scheduler.get_jobs()))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("planificador detenido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
