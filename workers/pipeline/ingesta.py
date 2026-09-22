"""Etapa de ingesta: del proveedor a Postgres.

Tres cosas que no son detalles de implementacion sino el motivo de que esta
etapa exista como modulo y no como script suelto:

**Cada etapa se registra.** `pipeline_run` guarda que se hizo, de que mercado,
con que resultado y sobre que instantanea. Una etapa ya terminada con exito se
salta al reejecutar, que es la mitad de la idempotencia; la otra mitad son los
UPSERT de `ingest.py`.

**Un proveedor caido degrada, no tumba.** Si falla la descarga de un mercado se
registra el fallo y se sigue con el siguiente. §48 del encargo lo pide, y ademas
es lo unico razonable con cinco mercados y fuentes gratuitas: que la India no
responda no puede dejar sin actualizar a EE. UU.

**Lo que no cuadra se guarda, no se escribe en un log.** Las comprobaciones de
calidad van a `data_quality_check` porque la degradacion de una fuente se ve como
tendencia —"lleva tres semanas faltando el 12 % de los fundamentales de Brasil"—
y un log rotado no permite esa lectura.
"""

from __future__ import annotations

import datetime as dt
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.adapters.nucleo import fundamentales_a_filas, fx_a_filas, precios_a_filas
from backend.db import ingest
from backend.db.models import DataFreshness, DataQualityCheck, PipelineRun
from backend.db.models.enums import CheckStatus, RunStatus, Severity

log = logging.getLogger("pipeline.ingesta")

PIPELINE = "ingesta"

#: Por debajo de esta fraccion de valores cubiertos, la descarga de un mercado
#: se considera degradada. No es un fallo —hay valores que legitimamente no
#: resuelven— pero si algo que hay que ver antes de fiarse de un ranking.
COBERTURA_MINIMA = 0.80

#: Dias sin dato nuevo tras los cuales un conjunto se marca rancio, POR TIPO DE
#: DATO. Un solo umbral no vale: los precios llegan cada sesion y los
#: fundamentales una o cuatro veces al ano. Medir los segundos con la vara de los
#: primeros deja el sistema marcado como rancio de forma permanente, y una alarma
#: que siempre esta encendida es una alarma que nadie mira.
#:
#: El de precios cubre un puente largo sin dar la alarma. El de fundamentales no
#: se inventa aqui: sale de `fundamental.antiguedad_maxima_dias` del motor, que
#: es la antiguedad a partir de la cual una empresa deja de pasar el filtro. El
#: proyecto ya tiene una definicion de "este dato ya no dice nada del presente" y
#: dos definiciones distintas de lo mismo acabarian divergiendo.
DIAS_PARA_RANCIO = {"precios": 5, "divisas": 5}
DIAS_PARA_RANCIO_POR_DEFECTO = 5

#: Anios de historico que se descargan. **Un solo sitio**: lo usan la ingesta,
#: el planificador y el script de linea de ordenes, y con el valor repartido por
#: tres ficheros basta con cambiar dos para que el backtest y el trabajo diario
#: cubran periodos distintos sin que nada avise.
#:
#: 20 y no 8. El minimo que exige D-7 para entrenar son 15 anios en dos
#: mercados, y con 8 no lo cumple ninguno; el proveedor si los sirve —comprobado
#: ticker a ticker— asi que el limite lo ponia este numero y nada mas. Los
#: valores que salieron a bolsa despues traen menos, que es correcto: no
#: existian.
ANOS_HISTORICO = 20


def _umbrales_rancio(cfg) -> dict[str, int]:
    return {**DIAS_PARA_RANCIO, "fundamentales": cfg.reglas.fundamental.antiguedad_maxima_dias}


@dataclass
class Resultado:
    """Que paso en una etapa de un mercado."""

    etapa: str
    mercado: str | None
    estado: str
    filas: int = 0
    error: str = ""
    avisos: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        donde = self.mercado or "global"
        if self.estado == RunStatus.FAILED.value:
            return f"  {donde}/{self.etapa}: FALLO - {self.error}"
        if self.estado == RunStatus.SKIPPED.value:
            return f"  {donde}/{self.etapa}: ya estaba hecho"
        cola = f" | {'; '.join(self.avisos)}" if self.avisos else ""
        return f"  {donde}/{self.etapa}: {self.filas} filas{cola}"


#: Fuentes cuyos datos son inventados. Mezclarlas con datos reales en la misma
#: base es indetectable en cualquier consulta que no mire la columna `source`.
FUENTES_SINTETICAS = {"sintetico"}


class MezclaDeDatos(RuntimeError):
    """Se intenta escribir datos inventados junto a datos reales, o al reves."""


def comprobar_procedencia(
    sesion: Session, fuente: str, tablas=("price", "fundamental_snapshot")
) -> None:
    """Impide mezclar datos sinteticos y reales en la misma base.

    El problema que motiva esto es real y costo encontrarlo. Una ejecucion con
    `--proveedor sintetico` dejo precios inventados para fechas que los datos
    reales aun no cubrian; la recarga real no los piso —solo sobrescribe las
    fechas que trae— y quedaron conviviendo. Exxon aparecia a 1.215 dolares
    junto a sus cierres reales de 165, y el ranking se calculo con eso.

    Nada fallaba. La columna `source` decia la verdad en cada fila, pero
    ninguna consulta la miraba, y el resultado era un score contaminado que
    parecia perfectamente normal.

    La regla es simple: una base es de datos reales o es de pruebas, nunca las
    dos cosas. Para trabajar con el proveedor sintetico, otra base de datos.
    """
    sinteticas = fuente in FUENTES_SINTETICAS
    for tabla in tablas:
        existentes = {
            f for (f,) in sesion.execute(text(f"SELECT DISTINCT source FROM {tabla}")).all()
        }
        if not existentes:
            continue
        otras = (
            {f for f in existentes if f not in FUENTES_SINTETICAS}
            if sinteticas
            else existentes & FUENTES_SINTETICAS
        )
        if otras:
            clase = "inventados" if sinteticas else "reales"
            raise MezclaDeDatos(
                f"no se pueden escribir datos {clase} de '{fuente}' en una base que "
                f"ya tiene datos de {sorted(otras)} en '{tabla}'. Una base es de "
                f"datos reales o de pruebas, nunca las dos: usa otra DATABASE_URL, "
                f"o vacia la tabla si las pruebas ya no hacen falta."
            )


def _ya_hecho(sesion: Session, etapa: str, dia: dt.date, mercado: str | None) -> bool:
    consulta = select(PipelineRun.id).where(
        PipelineRun.pipeline == PIPELINE,
        PipelineRun.stage == etapa,
        PipelineRun.run_date == dia,
        PipelineRun.status == RunStatus.SUCCEEDED.value,
    )
    consulta = consulta.where(
        PipelineRun.market_id.is_(None) if mercado is None else PipelineRun.market_id == mercado
    )
    return sesion.execute(consulta).first() is not None


def _registrar(
    sesion: Session,
    etapa: str,
    dia: dt.date,
    mercado: str | None,
    estado: str,
    filas: int = 0,
    error: str = "",
    descargado: dt.date | None = None,
) -> None:
    """Deja constancia de la etapa, sustituyendo el intento anterior del dia.

    Sustituyendo y no acumulando: la clave unica de `pipeline_run` es
    (pipeline, etapa, dia, mercado) justamente para que reintentar un dia no
    genere una fila por intento y haya que adivinar cual fue el bueno.
    """
    sentencia = insert(PipelineRun).values(
        pipeline=PIPELINE,
        stage=etapa,
        run_date=dia,
        market_id=mercado,
        status=estado,
        finished_at=dt.datetime.now(dt.UTC),
        rows_affected=filas,
        snapshot_downloaded_at=descargado,
        error=error or None,
    )
    sesion.execute(
        sentencia.on_conflict_do_update(
            index_elements=["pipeline", "stage", "run_date", "market_id"],
            set_={
                "status": sentencia.excluded.status,
                "finished_at": sentencia.excluded.finished_at,
                "rows_affected": sentencia.excluded.rows_affected,
                "snapshot_downloaded_at": sentencia.excluded.snapshot_downloaded_at,
                "error": sentencia.excluded.error,
            },
        )
    )


def _comprobar(
    sesion: Session,
    fuente: str,
    conjunto: str,
    mercado: str | None,
    nombre: str,
    estado: str,
    severidad: str,
    detalle: str = "",
    contexto: dict | None = None,
) -> None:
    sesion.add(
        DataQualityCheck(
            source=fuente,
            dataset=conjunto,
            market_id=mercado,
            check_name=nombre,
            status=estado,
            severity=severidad,
            detail=detalle or None,
            context=contexto,
        )
    )


def _actualizar_frescura(
    sesion: Session,
    conjunto: str,
    mercado: str,
    ultima: dt.date | None,
    fuente: str,
    cubiertos: int,
    esperados: int,
    hoy: dt.date,
    dias_rancio: int,
) -> None:
    """Deja en `data_freshness` lo que sirve `/health/data`.

    Se materializa en lugar de calcularse con un MAX() sobre las series: ese MAX
    sobre decenas de millones de filas particionadas no es una consulta para un
    health check que se llama cada quince segundos.
    """
    rancio = ultima is None or (hoy - ultima).days > dias_rancio
    sentencia = insert(DataFreshness).values(
        dataset=conjunto,
        market_id=mercado,
        last_data_date=ultima,
        last_success_at=dt.datetime.now(dt.UTC),
        source=fuente,
        securities_covered=cubiertos,
        securities_expected=esperados,
        is_stale=rancio,
    )
    sesion.execute(
        sentencia.on_conflict_do_update(
            index_elements=["dataset", "market_id"],
            set_={
                "last_data_date": sentencia.excluded.last_data_date,
                "last_success_at": sentencia.excluded.last_success_at,
                "source": sentencia.excluded.source,
                "securities_covered": sentencia.excluded.securities_covered,
                "securities_expected": sentencia.excluded.securities_expected,
                "is_stale": sentencia.excluded.is_stale,
            },
        )
    )


@contextmanager
def _etapa(
    sesion: Session, resultados: list[Resultado], etapa: str, mercado: str | None, dia: dt.date
):
    """Ejecuta una etapa aislando su fallo del resto del pipeline.

    Si algo revienta se deshace lo escrito por la etapa —para no dejar datos a
    medias— pero se conserva el registro del fallo, que se escribe en una
    transaccion nueva. Un pipeline que se cae sin dejar rastro de por que es un
    pipeline que se depura leyendo logs de hace tres dias.
    """
    resultado = Resultado(etapa=etapa, mercado=mercado, estado=RunStatus.SUCCEEDED.value)
    try:
        yield resultado
        sesion.commit()
    except Exception as exc:  # noqa: BLE001 - aqui cualquier fallo degrada, no tumba
        sesion.rollback()
        resultado.estado = RunStatus.FAILED.value
        resultado.error = f"{type(exc).__name__}: {exc}"
        log.warning("etapa %s/%s fallida: %s", mercado or "global", etapa, resultado.error)
        _registrar(sesion, etapa, dia, mercado, RunStatus.FAILED.value, error=resultado.error)
        _comprobar(
            sesion,
            fuente="pipeline",
            conjunto=etapa,
            mercado=mercado,
            nombre="descarga",
            estado=CheckStatus.FAILED.value,
            severidad=Severity.CRITICAL.value,
            detalle=resultado.error,
        )
        sesion.commit()
    resultados.append(resultado)


def _cobertura(resultado: Resultado, devueltos: set[str], esperados: list[str]) -> int:
    cubiertos = len(devueltos & set(esperados))
    if esperados and cubiertos / len(esperados) < COBERTURA_MINIMA:
        resultado.avisos.append(
            f"cobertura {cubiertos}/{len(esperados)} por debajo del {COBERTURA_MINIMA:.0%}"
        )
    return cubiertos


def ejecutar(
    sesion: Session,
    cfg,
    enrutador,
    mercados: list[str] | None = None,
    anos: int = ANOS_HISTORICO,
    dia: dt.date | None = None,
    forzar: bool = False,
    con_divisas: bool = True,
) -> list[Resultado]:
    """Descarga y persiste precios, fundamentales y divisas.

    `con_divisas=False` deja fuera la etapa de tipos de cambio. Existe por una
    razon de RELOJ, no de gusto: el BCE publica sus tipos de referencia a media
    tarde (CET), y el primer mercado que cierra cada dia es la India, a las
    10:00 UTC. Si esa ejecucion arrastrara la etapa de divisas, se anotaria como
    hecha con el ultimo tipo publicado —el de ayer— y las de la tarde la
    saltarian: el tipo de hoy no entraria hasta manana. Por eso el planificador
    la pide aparte, despues de que el BCE publique.
    """
    hoy = dt.date.today()
    dia = dia or hoy
    fin = dia
    inicio = dt.date(fin.year - anos, fin.month, fin.day)
    ids_mercado = mercados or [m.id for m in cfg.reglas.universo.mercados]
    # Antes de descargar nada: media hora de descarga para acabar rechazando la
    # escritura no le sirve a nadie.
    comprobar_procedencia(sesion, enrutador.nombre_de("precios"))
    umbrales = _umbrales_rancio(cfg)
    resultados: list[Resultado] = []

    indices = cfg.reglas.tecnico.indices_regimen

    for mercado_id in ids_mercado:
        tickers = cfg.universo.tickers(mercado_id)
        if not tickers:
            continue
        mapa = ingest.id_por_ticker(sesion, mercado_id)

        # --- precios -------------------------------------------------------
        if _ya_hecho(sesion, "precios", dia, mercado_id) and not forzar:
            resultados.append(Resultado("precios", mercado_id, RunStatus.SKIPPED.value))
        else:
            with _etapa(sesion, resultados, "precios", mercado_id, dia) as r:
                simbolos = tickers + ([indices[mercado_id]] if mercado_id in indices else [])
                df = enrutador.precios(simbolos, inicio, fin)
                filas = precios_a_filas(df, mapa, hoy)
                r.filas = ingest.escribir_precios(sesion, filas).filas

                # Filas imposibles que el saneamiento quito antes de verificar.
                # Se registran: cinco filas corruptas son ruido tolerable, pero
                # si un dia son cinco mil hay que verlo como tendencia, no
                # enterarse por un log rotado.
                descartadas = getattr(enrutador, "precios_descartados", 0)
                if descartadas:
                    r.avisos.append(f"{descartadas} filas con OHLC imposible descartadas")
                _comprobar(
                    sesion,
                    fuente=enrutador.nombre_de("precios"),
                    conjunto="precios",
                    mercado=mercado_id,
                    nombre="ohlc_coherente",
                    estado=(
                        CheckStatus.PASSED.value if not descartadas else CheckStatus.WARNING.value
                    ),
                    severidad=(Severity.INFO.value if not descartadas else Severity.WARNING.value),
                    detalle=(
                        ""
                        if not descartadas
                        else f"{descartadas} filas con minimo por encima del cierre "
                        f"o maximo por debajo; imposibles, se descartan"
                    ),
                    contexto={"descartadas": descartadas},
                )

                devueltos = set(df["ticker"].unique()) if not df.empty else set()
                cubiertos = _cobertura(r, devueltos, tickers)
                ultima = df["fecha"].max() if not df.empty else None
                _comprobar(
                    sesion,
                    fuente=enrutador.nombre_de("precios"),
                    conjunto="precios",
                    mercado=mercado_id,
                    nombre="cobertura",
                    estado=(
                        CheckStatus.PASSED.value if not r.avisos else CheckStatus.WARNING.value
                    ),
                    severidad=Severity.INFO.value if not r.avisos else Severity.WARNING.value,
                    detalle="; ".join(r.avisos),
                    contexto={"cubiertos": cubiertos, "esperados": len(tickers)},
                )
                _actualizar_frescura(
                    sesion,
                    "precios",
                    mercado_id,
                    ultima,
                    enrutador.nombre_de("precios"),
                    cubiertos,
                    len(tickers),
                    hoy,
                    umbrales["precios"],
                )
                _registrar(
                    sesion,
                    "precios",
                    dia,
                    mercado_id,
                    RunStatus.SUCCEEDED.value,
                    r.filas,
                    descargado=hoy,
                )

        # --- fundamentales --------------------------------------------------
        if _ya_hecho(sesion, "fundamentales", dia, mercado_id) and not forzar:
            resultados.append(Resultado("fundamentales", mercado_id, RunStatus.SKIPPED.value))
            continue
        with _etapa(sesion, resultados, "fundamentales", mercado_id, dia) as r:
            df = enrutador.fundamentales(tickers, inicio, fin)
            filas = fundamentales_a_filas(df, mapa, hoy)
            r.filas = ingest.escribir_fundamentales(sesion, filas).filas

            devueltos = set(df["ticker"].unique()) if not df.empty else set()
            cubiertos = _cobertura(r, devueltos, tickers)

            # Que proporcion de las filas es point-in-time de verdad. Es el
            # numero que decide cuanto vale un backtest fundamental, asi que se
            # mide y se guarda en lugar de suponerse.
            if not df.empty and "origen_pit" in df:
                capturadas = int((df["origen_pit"] == "capturado").sum())
                proporcion = capturadas / len(df)
                if proporcion < 1.0:
                    r.avisos.append(f"{proporcion:.0%} point-in-time real")
                _comprobar(
                    sesion,
                    fuente=enrutador.nombre_de("fundamentales", mercado_id),
                    conjunto="fundamentales",
                    mercado=mercado_id,
                    nombre="point_in_time",
                    estado=(
                        CheckStatus.PASSED.value if proporcion == 1.0 else CheckStatus.WARNING.value
                    ),
                    severidad=(
                        Severity.INFO.value if proporcion == 1.0 else Severity.WARNING.value
                    ),
                    detalle=(
                        f"{capturadas}/{len(df)} filas con cifras de su momento; "
                        f"el resto son reexpresadas a hoy"
                    ),
                    contexto={"capturadas": capturadas, "total": int(len(df))},
                )

            # La frescura se mide con lo que YA se ha publicado. Una fila con
            # fecha de publicacion futura no es el ultimo dato disponible: es un
            # dato que todavia no existe, y tomarlo como referencia daria una
            # frescura inmejorable precisamente cuando algo va mal.
            #
            # Que aparezcan es normal en el proveedor sintetico, que fabrica el
            # ejercicio en curso, y es un fallo en uno real: significa que la
            # fecha se ha estimado mal o que el mapeo esta roto. Se guardan
            # igualmente —la vista puntual ya impide que un backtest las vea
            # antes de tiempo— pero se cuentan y se avisa, en lugar de dejar que
            # pasen desapercibidas.
            futuras = 0
            ultima = None
            if not df.empty:
                publicadas = df["fecha_publicacion"]
                futuras = int((publicadas > hoy).sum())
                pasadas = publicadas[publicadas <= hoy]
                ultima = pasadas.max() if not pasadas.empty else None
            if futuras:
                r.avisos.append(f"{futuras} filas con publicacion futura")
            _comprobar(
                sesion,
                fuente=enrutador.nombre_de("fundamentales", mercado_id),
                conjunto="fundamentales",
                mercado=mercado_id,
                nombre="publicacion_futura",
                estado=CheckStatus.PASSED.value if not futuras else CheckStatus.WARNING.value,
                severidad=Severity.INFO.value if not futuras else Severity.WARNING.value,
                detalle=(
                    ""
                    if not futuras
                    else f"{futuras} filas dicen haberse publicado despues de {hoy}"
                ),
                contexto={"futuras": futuras},
            )
            _actualizar_frescura(
                sesion,
                "fundamentales",
                mercado_id,
                ultima,
                enrutador.nombre_de("fundamentales", mercado_id),
                cubiertos,
                len(tickers),
                hoy,
                umbrales["fundamentales"],
            )
            _registrar(
                sesion,
                "fundamentales",
                dia,
                mercado_id,
                RunStatus.SUCCEEDED.value,
                r.filas,
                descargado=hoy,
            )

    # --- divisas: una sola vez, no por mercado ------------------------------
    if not con_divisas:
        pass
    elif _ya_hecho(sesion, "divisas", dia, None) and not forzar:
        resultados.append(Resultado("divisas", None, RunStatus.SKIPPED.value))
    else:
        with _etapa(sesion, resultados, "divisas", None, dia) as r:
            divisas = sorted(
                {m.divisa for m in cfg.reglas.universo.mercados} - {cfg.reglas.cartera.divisa_base}
            )
            df = enrutador.fx(divisas, inicio, fin)
            r.filas = ingest.escribir_fx(
                sesion, fx_a_filas(df, cfg.reglas.cartera.divisa_base)
            ).filas
            _registrar(
                sesion, "divisas", dia, None, RunStatus.SUCCEEDED.value, r.filas, descargado=hoy
            )

    sesion.commit()
    return resultados


def marcar_rancios(sesion: Session, umbrales: dict[str, int], hoy: dt.date | None = None) -> int:
    """Marca como rancio lo que lleva demasiado sin actualizarse.

    Se ejecuta aunque la descarga falle: si no, un conjunto que dejo de
    actualizarse hace un mes seguiria figurando como fresco, que es peor que no
    tener el dato.
    """
    hoy = hoy or dt.date.today()
    tocadas = 0
    for conjunto, dias in umbrales.items():
        resultado = sesion.execute(
            update(DataFreshness)
            .where(
                DataFreshness.dataset == conjunto,
                DataFreshness.last_data_date < hoy - dt.timedelta(days=dias),
            )
            .values(is_stale=True)
        )
        tocadas += resultado.rowcount or 0
    sesion.commit()
    return tocadas
