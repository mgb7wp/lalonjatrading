"""Division diseno/validacion y analisis de sensibilidad.

El documento dice algo que es facil asentir y dificil cumplir: el periodo de
validacion deja de ser una prueba independiente si se consulta muchas veces. La
memoria no basta para eso, asi que aqui la puerta es explicita —hay que pedir el
periodo de validacion a proposito— y **cada consulta se anota en disco con su
fecha**. Cuando el contador va por nueve, el informe lo dice, y la conclusion
que uno saque de ese periodo vale lo que valga un test repetido nueve veces.

El analisis de sensibilidad mueve cada parametro numerico un `sensibilidad_pct`
arriba y abajo, de uno en uno, sobre el periodo de diseno. Los enteros se
redondean (una media de 200 sesiones pasa a 150 y 250, no a 150,0) y los
parametros estructurales —la divisa base, la lista de mercados— se quedan fuera
porque moverlos no es un ajuste, es otra estrategia.

Cada parametro se etiqueta ademas como activo o inactivo segun si moverlo
cambia algo. Es la unica forma de no confundir "la estrategia aguanta este
parametro" con "este parametro no estaba haciendo nada".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, MutableMapping

import pandas as pd

from . import backtest as backtest_mod
from . import metricas as metricas_mod
from .config import Config
from .datos.almacen import Instantanea
from .errores import ErrorConfiguracion

#: Parametros numericos que tiene sentido mover. Los que no estan aqui son
#: estructurales: cambiarlos no afina la estrategia, la sustituye.
PARAMETROS_SENSIBILIDAD: list[tuple[str, type]] = [
    ("cartera.max_posiciones", int),
    ("cartera.max_por_sector", int),
    ("cartera.max_por_mercado", int),
    ("cartera.peso_maximo", float),
    ("fundamental.minimos.roe", float),
    ("fundamental.minimos.margen_operativo", float),
    ("fundamental.minimos.deuda_neta_ebitda_max", float),
    ("tecnico.regimen_mercado_media", int),
    ("tecnico.media_corta", int),
    ("tecnico.media_larga", int),
    ("tecnico.atr_periodo", int),
    ("salidas.stop_inicial_atr", float),
    ("salidas.stop_dinamico_atr", float),
    ("riesgo.por_operacion", float),
    ("universo.volumen_minimo_desarrollado", float),
    ("universo.volumen_minimo_emergente", float),
]


@dataclass(frozen=True, slots=True)
class Division:
    """Las dos mitades del historico."""

    inicio: date
    corte: date
    fin: date

    @property
    def diseno(self) -> tuple[date, date]:
        return self.inicio, self.corte

    @property
    def validacion(self) -> tuple[date, date]:
        return self.corte, self.fin

    def toca_validacion(self, periodo: str) -> bool:
        """Si mirar ese periodo ensena algo del de validacion.

        "todo" tambien: incluye la validacion entera, y ver su curva es mirarla
        igual que pidiendola sola.
        """
        return periodo in ("validacion", "todo")


def dividir(instantanea: Instantanea, cfg: Config) -> Division:
    """Parte el historico en diseno y validacion por la fecha de corte fija.

    El corte es `validacion.fecha_corte`, o la primera sesion a partir de ella.
    Antes se calculaba como la fraccion `fraccion_diseno` de las sesiones
    descargadas, y eso lo movia cada semana: al llegar datos nuevos, el corte
    avanzaba y una parte de lo que era validacion pasaba a ser diseno sin que
    nadie lo decidiera. Ahora los datos nuevos solo alargan la validacion.
    """
    fechas = sorted(instantanea.precios["fecha"].unique())
    if not fechas:
        raise ValueError("no hay fechas en la instantanea")
    fecha_corte = cfg.reglas.validacion.fecha_corte
    posteriores = [f for f in fechas if f >= fecha_corte]
    if fecha_corte <= fechas[0] or not posteriores:
        raise ErrorConfiguracion(
            f"validacion.fecha_corte ({fecha_corte}) queda fuera de los datos "
            f"({fechas[0]} a {fechas[-1]}): no deja periodo de diseno o de "
            f"validacion. Revisa config/reglas.yaml."
        )
    return Division(fechas[0], posteriores[0], fechas[-1])


class RegistroConsultas:
    """Lleva la cuenta de cuantas veces se ha mirado el periodo de validacion."""

    def __init__(self, ruta: Path) -> None:
        self._ruta = Path(ruta)

    def leer(self) -> list[dict[str, Any]]:
        if not self._ruta.is_file():
            return []
        try:
            return json.loads(self._ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    @property
    def n(self) -> int:
        return len(self.leer())

    def anotar(self, motivo: str) -> int:
        """Registra una consulta y devuelve cuantas van."""
        consultas = self.leer()
        consultas.append(
            {"fecha": datetime.now().isoformat(timespec="seconds"), "motivo": motivo}
        )
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        self._ruta.write_text(
            json.dumps(consultas, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return len(consultas)

    def anotar_una_vez(self, sesion: MutableMapping, clave: str, motivo: str) -> bool:
        """Anota la consulta si esta sesion no la habia anotado ya.

        El panel se reejecuta entero con cada clic: sin esto, mirar una vez la
        validacion y mover un filtro contaria como diez consultas. `sesion` es
        el estado de la sesion (en el panel, `st.session_state`). Devuelve si
        ha anotado.
        """
        if sesion.get(clave):
            return False
        self.anotar(motivo)
        sesion[clave] = True
        return True


# --------------------------------------------------------------------------
# Sensibilidad
# --------------------------------------------------------------------------


def _leer_ruta(datos: dict, ruta: str) -> Any:
    actual: Any = datos
    for parte in ruta.split("."):
        actual = actual[parte]
    return actual


def _escribir_ruta(datos: dict, ruta: str, valor: Any) -> dict:
    partes = ruta.split(".")
    copia = json.loads(json.dumps(datos, default=str))
    actual = copia
    for parte in partes[:-1]:
        actual = actual[parte]
    actual[partes[-1]] = valor
    return copia


def variantes(cfg: Config) -> list[tuple[str, str, Config]]:
    """Genera las configuraciones desplazadas, una por parametro y sentido."""
    from .config import Config as ConfigCls
    from .config import Reglas

    pct = cfg.reglas.validacion.sensibilidad_pct
    base = cfg.reglas.model_dump(mode="json")
    salida: list[tuple[str, str, Config]] = []

    for ruta, tipo in PARAMETROS_SENSIBILIDAD:
        try:
            original = _leer_ruta(base, ruta)
        except KeyError:
            continue
        for sentido, factor in (("abajo", 1.0 - pct), ("arriba", 1.0 + pct)):
            nuevo = original * factor
            # Un entero desplazado sigue siendo un entero: una media de 200
            # sesiones pasa a 150 o 250, no a 150,0.
            nuevo = max(int(round(nuevo)), 1) if tipo is int else float(nuevo)
            if nuevo == original:
                continue
            try:
                reglas = Reglas.model_validate(_escribir_ruta(base, ruta, nuevo))
            except Exception:
                # Un desplazamiento que rompe una invariante (media corta por
                # encima de la larga, por ejemplo) no es un fallo: es que ese
                # extremo no es una estrategia valida. Se salta y se dice.
                continue
            salida.append(
                (ruta, sentido, ConfigCls(
                    reglas=reglas,
                    implementacion=cfg.implementacion,
                    universo=cfg.universo,
                    impuestos=cfg.impuestos,
                    dir_config=cfg.dir_config,
                ))
            )
    return salida


def sensibilidad(
    instantanea: Instantanea,
    cfg: Config,
    inicio: date,
    fin: date,
    base: metricas_mod.Resumen | None = None,
) -> pd.DataFrame:
    """Corre el backtest con cada parametro desplazado y compara.

    Se ejecuta sobre el periodo de diseno: usar el de validacion para esto seria
    justamente gastar la unica prueba independiente que hay.
    """
    if base is None:
        r = backtest_mod.ejecutar(instantanea, cfg, inicio, fin)
        base = metricas_mod.resumir(r.curva, r.operaciones_df, cfg)

    filas: list[dict] = []
    for ruta, sentido, variante in variantes(cfg):
        try:
            r = backtest_mod.ejecutar(instantanea, variante, inicio, fin)
            res = metricas_mod.resumir(r.curva, r.operaciones_df, variante)
        except Exception as exc:  # pragma: no cover - variante inviable
            filas.append({"parametro": ruta, "sentido": sentido, "error": str(exc)})
            continue
        filas.append(
            {
                "parametro": ruta,
                "sentido": sentido,
                "valor": _leer_ruta(variante.reglas.model_dump(mode="json"), ruta),
                "rentabilidad_anualizada": res.rentabilidad_anualizada,
                "drawdown_maximo": res.drawdown_maximo,
                "sharpe": res.sharpe,
                "n_operaciones": res.n_operaciones,
                "delta_anualizada": res.rentabilidad_anualizada - base.rentabilidad_anualizada,
                "delta_sharpe": res.sharpe - base.sharpe,
            }
        )

    df = pd.DataFrame(filas)
    if df.empty or "delta_anualizada" not in df.columns:
        return df

    # Un parametro cuyo desplazamiento no mueve nada estaba inactivo. Decirlo
    # evita leer como robustez lo que era irrelevancia.
    movimiento = df.groupby("parametro")["delta_anualizada"].apply(
        lambda s: float(s.abs().max())
    )
    df["actividad"] = df["parametro"].map(
        lambda p: "activo" if movimiento.get(p, 0.0) > 1e-6 else "inactivo"
    )
    return df
