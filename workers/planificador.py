"""Cuando se ejecuta cada cosa, y por que a esa hora.

## El agujero que esto tapa

`docker-compose.yml` decia que "APScheduler dentro del worker cubre el pipeline
diario" y `pyproject.toml` declaraba la dependencia, pero el worker se limitaba a
`signal.pause()`: **no habia ni una tarea programada**. La consecuencia se vio en
produccion —dos mercados con datos y tres vacios— y no porque el proveedor
fallara, sino porque los datos solo aparecian cuando alguien se acordaba de
lanzar el script a mano.

## Cada mercado, tras SU cierre

No hay un "cierre global". Programar los cinco mercados a la misma hora
significa descargar la India ocho horas tarde o Brasil antes de que cierre, y lo
segundo guarda una sesion a medias como si fuera el cierre del dia.

Las horas **no se escriben aqui**: salen de `exchange_calendars`, que es la
fuente autoritativa que ya usa el motor. Escribirlas a mano significa que el dia
que Nueva York cambie al horario de verano una semana antes que Madrid, algo se
descarga a la hora equivocada y nadie lo relaciona con esto.

Se anade un margen tras el cierre porque el dato no esta publicado en el
instante en que suena la campana.

## Las divisas van aparte

El BCE publica sus tipos de referencia a media tarde (CET). El primer mercado
que cierra es la India, a las 10:00 UTC: si esa ejecucion arrastrara las
divisas, se anotarian como hechas con el tipo de ayer y las ejecuciones de la
tarde la saltarian por idempotencia. El tipo de hoy no entraria hasta manana.

## Un festivo no es un fallo

Antes de descargar se pregunta al calendario si ese mercado ha abierto hoy. Sin
esa comprobacion, cada festivo nacional deja una ejecucion registrada que no
trae datos nuevos, y el dia que de verdad falle algo estara enterrado entre
docenas de esas.
"""

from __future__ import annotations

import datetime as dt
import logging

import exchange_calendars as xc
import pandas as pd

log = logging.getLogger("planificador")

#: Minutos de espera tras el cierre antes de descargar. El precio de cierre no
#: esta publicado cuando suena la campana; media hora es lo que tarda en
#: asentarse sin dejar el dato del dia para el dia siguiente.
MARGEN_TRAS_CIERRE_MIN = 30

#: Hora (Europe/Madrid) de la descarga de divisas. El BCE publica sus tipos de
#: referencia alrededor de las 16:00 CET; 16:45 deja margen sin esperar a manana.
HORA_DIVISAS = (16, 45)


class Tarea:
    """Una tarea programada, con su hora y su huso."""

    __slots__ = ("nombre", "hora", "minuto", "zona", "mercado")

    def __init__(
        self, nombre: str, hora: int, minuto: int, zona: str, mercado: str | None = None
    ) -> None:
        self.nombre = nombre
        self.hora = hora
        self.minuto = minuto
        self.zona = zona
        self.mercado = mercado

    def __repr__(self) -> str:  # pragma: no cover - solo para logs
        return f"<Tarea {self.nombre} {self.hora:02d}:{self.minuto:02d} {self.zona}>"

    @property
    def cuando(self) -> str:
        return f"{self.hora:02d}:{self.minuto:02d} {self.zona}"


def cierre_habitual(codigo: str, referencia: dt.date | None = None) -> tuple[int, int, str]:
    """Hora de cierre HABITUAL de un mercado, en su propio huso.

    Habitual y no "la del ultimo dia": las medias sesiones (Nochebuena, visperas
    de fiesta) cierran antes, y tomar una de esas como referencia adelantaria la
    descarga de todo el anio. Se toma la moda de las sesiones de un trimestre.
    """
    referencia = referencia or dt.date.today()
    inicio = referencia - dt.timedelta(days=90)
    cal = xc.get_calendar(codigo, start=str(inicio), end=str(referencia))
    zona = str(cal.tz)
    locales = cal.closes.dt.tz_convert(zona)
    habitual = locales.dt.strftime("%H:%M").mode()
    if habitual.empty:  # pragma: no cover - un mercado sin sesiones en 90 dias
        raise ValueError(f"el calendario '{codigo}' no tiene sesiones recientes")
    hora, minuto = (int(x) for x in habitual.iloc[0].split(":"))
    return hora, minuto, zona


def _sumar_minutos(hora: int, minuto: int, minutos: int) -> tuple[int, int]:
    total = (hora * 60 + minuto + minutos) % (24 * 60)
    return divmod(total, 60)


def construir(calendarios: dict[str, str], referencia: dt.date | None = None) -> list[Tarea]:
    """Las tareas del dia: una por mercado, mas la de divisas.

    `calendarios` es el mapa mercado -> codigo de `exchange_calendars` que ya
    vive en `implementacion.yaml`.
    """
    tareas: list[Tarea] = []
    for mercado_id, codigo in sorted(calendarios.items()):
        hora, minuto, zona = cierre_habitual(codigo, referencia)
        hora, minuto = _sumar_minutos(hora, minuto, MARGEN_TRAS_CIERRE_MIN)
        tareas.append(
            Tarea(
                nombre=f"ingesta:{mercado_id}",
                hora=hora,
                minuto=minuto,
                zona=zona,
                mercado=mercado_id,
            )
        )
    tareas.append(
        Tarea(
            nombre="divisas",
            hora=HORA_DIVISAS[0],
            minuto=HORA_DIVISAS[1],
            zona="Europe/Madrid",
        )
    )
    return tareas


def ha_negociado(codigo: str, dia: dt.date) -> bool:
    """Si ese mercado tuvo sesion ese dia. Un festivo no es un fallo.

    Se pregunta por PERTENENCIA al conjunto de sesiones y no con `is_session`:
    un calendario construido hasta el propio dia termina en su ultima sesion, y
    si ese dia es festivo `is_session` lanza `DateOutOfBounds` en lugar de
    responder que no. Lo descubrio un test con el 1 de mayo en Madrid. Con el
    fallo, cada fin de semana y cada festivo dejaba un error en el log, que es
    exactamente la alarma siempre encendida que nadie acaba mirando.
    """
    cal = xc.get_calendar(
        codigo,
        start=str(dia - dt.timedelta(days=7)),
        end=str(dia + dt.timedelta(days=7)),
    )
    return pd.Timestamp(dia) in cal.sessions
