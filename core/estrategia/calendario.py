"""Calendarios de negociacion, uno por mercado.

El documento insiste en que "la sesion siguiente" se calcula por mercado y no
de forma global, porque los festivos no coinciden entre paises. Este modulo es
el unico que habla con `exchange_calendars` y el unico que sabe que una sesion
se etiqueta con una fecha pero se abre y se cierra en un instante UTC concreto.
Esa distincion importa: mezclar fechas e instantes es justo lo que produce
decisiones tomadas con datos que todavia no existian.

El corte semanal es global y va en instantes, no en fechas. Para los cinco
mercados actuales un corte por mercado daria el mismo resultado —se comprobo
sesion a sesion sobre el calendario real— pero el corte global lo garantiza por
construccion y no por suerte del calendario: todas las candidatas de la semana
se puntuan con informacion disponible en un mismo instante, y ningun mercado
puede ejecutar antes de ese instante.
"""

from __future__ import annotations

from datetime import date
from functools import cached_property

import exchange_calendars as xc
import numpy as np
import pandas as pd

from .config import Config
from .errores import ErrorCalendario


class Calendarios:
    """Los calendarios de todos los mercados del universo.

    Las aperturas y los cierres se vuelcan una sola vez a vectores alineados con
    las sesiones de cada mercado. Consultar pasa a ser una busqueda binaria en
    lugar de un recorrido: la primera version preguntaba a `exchange_calendars`
    sesion a sesion y se comia mas de la mitad del tiempo del backtest.
    """

    def __init__(self, cfg: Config, inicio: date, fin: date) -> None:
        self._cfg = cfg
        self._inicio = inicio
        self._fin = fin
        self._cal: dict[str, xc.ExchangeCalendar] = {}
        self._sesiones: dict[str, list[date]] = {}
        self._cierres: dict[str, np.ndarray] = {}
        self._aperturas: dict[str, np.ndarray] = {}

        for mercado_id in cfg.reglas.mercados_por_id:
            codigo = cfg.implementacion.calendarios[mercado_id]
            try:
                cal = xc.get_calendar(
                    codigo, start=pd.Timestamp(inicio), end=pd.Timestamp(fin)
                )
            except Exception as exc:  # pragma: no cover - configuracion invalida
                raise ErrorCalendario(
                    f"no se pudo cargar el calendario '{codigo}' del mercado "
                    f"'{mercado_id}': {exc}"
                ) from exc
            self._cal[mercado_id] = cal
            self._sesiones[mercado_id] = [s.date() for s in cal.sessions]
            # `closes` y `opens` vienen como Series con zona horaria. Dentro se
            # guardan como UTC sin zona: comparar un instante con zona contra
            # uno sin ella es un TypeError en pandas, y mezclar los dos convenios
            # por el modulo es la forma segura de acabar teniendolo.
            self._cierres[mercado_id] = _a_utc_naive(cal.closes)
            self._aperturas[mercado_id] = _a_utc_naive(cal.opens)

    # -- sesiones ---------------------------------------------------------

    def mercados(self) -> list[str]:
        return list(self._cal)

    def sesiones(self, mercado_id: str) -> list[date]:
        """Fechas de sesion de un mercado, en orden."""
        return self._sesiones[self._exige(mercado_id)]

    @cached_property
    def _sesiones_set(self) -> dict[str, set[date]]:
        return {m: set(s) for m, s in self._sesiones.items()}

    def abierto(self, mercado_id: str, fecha: date) -> bool:
        return fecha in self._sesiones_set[self._exige(mercado_id)]

    @cached_property
    def union_sesiones(self) -> list[date]:
        """Todas las fechas en que negocia al menos un mercado, ordenadas.

        Es el eje temporal del backtest: un dia en que solo abre Brasil sigue
        siendo un dia en que hay que vigilar los stops de las posiciones
        brasilenas y en que la cartera cambia de valor por la divisa.
        """
        todas: set[date] = set()
        for m in self._cal:
            todas |= self._sesiones_set[m]
        return sorted(todas)

    def cierre_utc(self, mercado_id: str, fecha: date) -> pd.Timestamp:
        """Instante de cierre de esa sesion, en UTC y con zona horaria."""
        i = self._indice_sesion(mercado_id, fecha)
        return pd.Timestamp(self._cierres[mercado_id][i], tz="UTC")

    def apertura_utc(self, mercado_id: str, fecha: date) -> pd.Timestamp:
        """Instante de apertura de esa sesion, en UTC y con zona horaria."""
        i = self._indice_sesion(mercado_id, fecha)
        return pd.Timestamp(self._aperturas[mercado_id][i], tz="UTC")

    def _indice_sesion(self, mercado_id: str, fecha: date) -> int:
        sesiones = self.sesiones(mercado_id)
        i = _primer_indice_mayor_igual(sesiones, fecha)
        if i >= len(sesiones) or sesiones[i] != fecha:
            raise ErrorCalendario(f"{fecha} no es sesion de '{mercado_id}'")
        return i

    def sesion_siguiente(self, mercado_id: str, fecha: date) -> date | None:
        """Primera sesion de ese mercado estrictamente posterior a `fecha`."""
        sesiones = self.sesiones(mercado_id)
        idx = _primer_indice_mayor(sesiones, fecha)
        return sesiones[idx] if idx < len(sesiones) else None

    def sesion_anterior(self, mercado_id: str, fecha: date) -> date | None:
        """Ultima sesion de ese mercado estrictamente anterior a `fecha`."""
        sesiones = self.sesiones(mercado_id)
        idx = _primer_indice_mayor_igual(sesiones, fecha)
        return sesiones[idx - 1] if idx > 0 else None

    # -- ciclo semanal ----------------------------------------------------

    @cached_property
    def cortes_semanales(self) -> list[pd.Timestamp]:
        """Un instante de corte por semana ISO, ordenados.

        El corte de una semana es el ultimo cierre de mercado de esa semana,
        mirando todos los mercados a la vez. Hasta ese instante se acumula
        informacion; a partir de el se ejecuta.
        """
        todos = np.concatenate([c for c in self._cierres.values() if len(c)])
        if todos.size == 0:
            return []
        serie = pd.Series(pd.to_datetime(todos))
        iso = serie.dt.isocalendar()
        por_semana = serie.groupby([iso["year"], iso["week"]]).max()
        return sorted(pd.Timestamp(v, tz="UTC") for v in por_semana.to_numpy())

    def sesion_de_decision(self, mercado_id: str, corte: pd.Timestamp) -> date | None:
        """Ultima sesion del mercado cuyo cierre no supera el corte.

        Si el mercado estuvo cerrado al final de la semana, su sesion de
        decision es anterior y la senal llega con retraso. Eso es honesto y se
        registra (`sesiones_de_retraso`), a diferencia de decidir con el cierre
        de otro mercado que aun no se habia producido.
        """
        self._exige(mercado_id)
        cierres = self._cierres[mercado_id]
        i = int(np.searchsorted(cierres, _corte_naive(corte), side="right")) - 1
        return self._sesiones[mercado_id][i] if i >= 0 else None

    def sesion_de_ejecucion(self, mercado_id: str, corte: pd.Timestamp) -> date | None:
        """Primera sesion del mercado que abre estrictamente despues del corte.

        Es "la apertura de la sesion siguiente" del documento, resuelta en el
        calendario de cada mercado y anclada al corte global.
        """
        self._exige(mercado_id)
        aperturas = self._aperturas[mercado_id]
        i = int(np.searchsorted(aperturas, _corte_naive(corte), side="right"))
        sesiones = self._sesiones[mercado_id]
        return sesiones[i] if i < len(sesiones) else None

    def sesiones_de_retraso(
        self, mercado_id: str, decision: date, ejecucion: date
    ) -> int:
        """Cuantas sesiones median entre decidir y ejecutar.

        En una semana normal es 1. Mas de 1 significa que el mercado estuvo
        cerrado y la senal llego vieja; el informe reporta la distribucion.
        """
        sesiones = self.sesiones(mercado_id)
        try:
            return sesiones.index(ejecucion) - sesiones.index(decision)
        except ValueError as exc:  # pragma: no cover - fechas fuera de rango
            raise ErrorCalendario(
                f"{decision} o {ejecucion} no son sesiones de '{mercado_id}'"
            ) from exc

    # -- utilidades -------------------------------------------------------

    def _exige(self, mercado_id: str) -> str:
        if mercado_id not in self._cal:
            raise ErrorCalendario(f"mercado sin calendario: {mercado_id!r}")
        return mercado_id


def _a_utc_naive(serie: pd.Series) -> np.ndarray:
    """Pasa una serie de instantes con zona a UTC sin zona, como datetime64."""
    valores = pd.to_datetime(serie)
    if getattr(valores.dt, "tz", None) is not None:
        valores = valores.dt.tz_convert("UTC").dt.tz_localize(None)
    return valores.to_numpy(dtype="datetime64[ns]")


def _corte_naive(corte: pd.Timestamp) -> np.datetime64:
    """El corte en el mismo convenio que los vectores internos."""
    ts = pd.Timestamp(corte)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return np.datetime64(ts)


def _primer_indice_mayor(ordenadas: list[date], valor: date) -> int:
    import bisect

    return bisect.bisect_right(ordenadas, valor)


def _primer_indice_mayor_igual(ordenadas: list[date], valor: date) -> int:
    import bisect

    return bisect.bisect_left(ordenadas, valor)
