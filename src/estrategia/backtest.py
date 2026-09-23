"""Motor de backtest.

Recorre dia a dia la union de sesiones de los cinco mercados. Es el unico modulo
con estado mutable entre dias; todo lo demas son funciones puras sobre una
sesion o sobre una vista de datos a una fecha.

Orden dentro de cada dia, para cada mercado que tenga sesion:

1. **Stops** de las posiciones abiertas, juzgados con el nivel vigente de AYER.
   Si abre por debajo, salida a la apertura; si el minimo lo toca, salida al
   stop.
2. **Ventas** pendientes de la revision semanal anterior, a la apertura.
3. **Compras** pendientes, a la apertura, en el orden ya congelado al decidir.
4. **Stop intradia** de lo que se acaba de comprar: una posicion abierta hoy
   puede saltar hoy mismo, y el backtest no puede ignorarlo.
5. **Trinquete**: se actualiza el maximo de cierres y el stop dinamico con el
   cierre de hoy. Va al final a proposito: si se actualizase antes del paso 1,
   se estaria usando el cierre de hoy para decidir si hoy se toco el stop, que
   es anticipacion pura y mejora todos los backtests en silencio.
6. **Revision semanal**, si esta sesion es la que aporta la decision de la
   semana para ese mercado: salidas por regla y candidatas del mercado.

Al terminar el dia en que decide el ultimo mercado de la semana, se **reparten
los huecos una sola vez** entre las candidatas de todos los mercados, ordenadas
en una lista global. Repartirlos mercado a mercado dejaria que cada uno viera la
cartera como si los demas no hubieran reservado nada: se podrian superar los
topes de posiciones, sector y efectivo, y entraria antes el mercado que va
primero en la lista, no la mejor candidata.

Las salidas se procesan antes que las entradas para que un hueco liberado hoy
se pueda usar en la asignacion de la semana siguiente. Un hueco que se libera el
lunes no se rellena hasta el siguiente corte semanal: es mas simple y mas
conservador que reabrir la lista a media semana.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import costes as costes_mod
from . import fundamental as fundamental_mod
from . import ordenes as ordenes_mod
from . import salidas as salidas_mod
from . import seleccion as seleccion_mod
from . import tecnico as tecnico_mod
from . import universo as universo_mod
from .calendario import Calendarios
from .cartera import Cartera
from .config import Config
from .datos.almacen import Instantanea
from .errores import ErrorDatos
from .sectores import MapaSectores
from .tipos import Evento, MotivoSalida, Orden, Posicion


@dataclass
class Resultado:
    """Todo lo que produce un backtest."""

    curva: pd.DataFrame
    operaciones: list
    eventos: list[Evento]
    inicio: date
    fin: date
    capital_inicial: float
    sectores_sin_mapear: dict[str, list[str]] = field(default_factory=dict)
    posiciones_finales: int = 0
    impuesto_extrapolado: bool = False

    @property
    def operaciones_df(self) -> pd.DataFrame:
        if not self.operaciones:
            return pd.DataFrame()
        from dataclasses import asdict
        return pd.DataFrame([asdict(o) | {
            "motivo_salida": str(o.motivo_salida),
            "ganadora": o.ganadora,
            "dias": o.dias,
            "coste_pct_posicion": o.coste_pct_posicion,
        } for o in self.operaciones])

    @property
    def eventos_df(self) -> pd.DataFrame:
        if not self.eventos:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "fecha": e.fecha, "tipo": e.tipo, "mercado": e.mercado,
                    "ticker": e.ticker, "motivo": e.motivo, **e.detalles,
                }
                for e in self.eventos
            ]
        )


def ejecutar(
    instantanea: Instantanea,
    cfg: Config,
    inicio: date | None = None,
    fin: date | None = None,
) -> Resultado:
    """Corre el backtest completo sobre una instantanea de datos."""
    instantanea.preparar(cfg)
    rango_ini, rango_fin = instantanea.rango_precios
    inicio = inicio or rango_ini
    fin = fin or rango_fin
    if inicio >= fin:
        raise ErrorDatos(f"rango de backtest vacio: {inicio} .. {fin}")

    cal = Calendarios(cfg, rango_ini, rango_fin)
    mapa = MapaSectores(cfg)
    cartera = Cartera(efectivo=cfg.reglas.cartera.capital_inicial_eur)
    eventos: list[Evento] = []
    curva: list[dict] = []
    impuesto_extrapolado = False

    # Calentamiento: no se decide hasta tener historico para la media larga, el
    # regimen, el ATR y el momentum. Empezar antes produciria senales calculadas
    # sobre series a medias. Se cuenta desde el principio de los DATOS, no desde
    # el del backtest: si hay historico anterior a `inicio`, los indicadores ya
    # estan maduros y se decide desde el primer dia. Si no, el periodo de
    # validacion, que empieza donde acaba el de diseno, pasaria mas de un ano en
    # liquidez esperando algo que ya tiene.
    inicio_efectivo = max(inicio, _inicio_con_calentamiento(rango_ini, cfg))

    pendientes_compra: dict[str, list[Orden]] = {}
    pendientes_venta: dict[str, list[tuple[str, MotivoSalida]]] = {}
    decisiones: dict[date, list[tuple[str, pd.Timestamp]]] = {}

    # Se precalcula, por corte semanal, que sesion decide y cual ejecuta en cada
    # mercado, y que dia se reparten los huecos: el de la ultima decision de la
    # semana. Asi el bucle diario solo consulta diccionarios.
    ejecuciones: dict[tuple[str, date], pd.Timestamp] = {}
    repartos: dict[date, list[pd.Timestamp]] = {}
    for corte in cal.cortes_semanales:
        ultima: date | None = None
        for mercado_id in cal.mercados():
            d = cal.sesion_de_decision(mercado_id, corte)
            e = cal.sesion_de_ejecucion(mercado_id, corte)
            if d is None or e is None or d < inicio_efectivo or e > fin:
                continue
            decisiones.setdefault(d, []).append((mercado_id, corte))
            ejecuciones[(mercado_id, d)] = pd.Timestamp(e)
            ultima = d if ultima is None else max(ultima, d)
        if ultima is not None:
            repartos.setdefault(ultima, []).append(corte)
    rondas: dict[pd.Timestamp, _Ronda] = {}

    for dia in cal.union_sesiones:
        if dia < inicio or dia > fin:
            continue
        vista = instantanea.vista(dia)

        for mercado_id in cal.mercados():
            if not cal.abierto(mercado_id, dia):
                continue
            divisa = cfg.reglas.mercado(mercado_id).divisa

            # 1. Stops, con el nivel que venia de ayer.
            for ticker in list(cartera.posiciones):
                pos = cartera.posiciones[ticker]
                if pos.mercado != mercado_id:
                    continue
                sesion = vista.precio_en(ticker, dia)
                if sesion is None:
                    cartera.actualizar(pos.sin_datos())
                    if pos.sesiones_sin_datos + 1 >= cfg.reglas.datos.sesiones_sin_datos_cierre_forzoso:
                        _cerrar(
                            cartera, ticker, dia, pos.ultimo_cierre_local or pos.precio_entrada_local,
                            vista, cfg, MotivoSalida.CIERRE_FORZOSO_SIN_DATOS, eventos, divisa,
                        )
                    continue
                salida = salidas_mod.evaluar_stop(pos, sesion)
                if salida is not None:
                    ext = _cerrar(
                        cartera, ticker, dia, salida.precio_local, vista, cfg,
                        salida.motivo, eventos, divisa,
                    )
                    impuesto_extrapolado = impuesto_extrapolado or ext

            # 2. Ventas pendientes de la revision anterior.
            clave_venta = f"{mercado_id}|{dia.isoformat()}"
            for ticker, motivo in pendientes_venta.pop(clave_venta, []):
                if not cartera.tiene(ticker):
                    continue
                sesion = vista.precio_en(ticker, dia)
                if sesion is None:
                    continue
                ext = _cerrar(
                    cartera, ticker, dia, float(sesion["apertura"]), vista, cfg,
                    motivo, eventos, divisa,
                )
                impuesto_extrapolado = impuesto_extrapolado or ext

            # 3. Compras pendientes, en el orden congelado al decidir.
            clave_compra = f"{mercado_id}|{dia.isoformat()}"
            for orden in pendientes_compra.pop(clave_compra, []):
                ext = _abrir(cartera, orden, dia, vista, cfg, eventos, divisa)
                impuesto_extrapolado = impuesto_extrapolado or ext

            # 4. Stop intradia de lo comprado hoy y del resto.
            for ticker in list(cartera.posiciones):
                pos = cartera.posiciones[ticker]
                if pos.mercado != mercado_id or pos.fecha_entrada != dia:
                    continue
                sesion = vista.precio_en(ticker, dia)
                if sesion is None:
                    continue
                if float(sesion["minimo"]) <= pos.stop_efectivo_local:
                    ext = _cerrar(
                        cartera, ticker, dia, pos.stop_efectivo_local, vista, cfg,
                        MotivoSalida.STOP_INTRADIA, eventos, divisa,
                    )
                    impuesto_extrapolado = impuesto_extrapolado or ext

            # 5. Trinquete con el cierre de hoy.
            for ticker in list(cartera.posiciones):
                pos = cartera.posiciones[ticker]
                if pos.mercado != mercado_id:
                    continue
                sesion = vista.precio_en(ticker, dia)
                if sesion is None:
                    continue
                serie = vista.serie(ticker)
                i = vista.posicion_exacta(ticker, dia)
                atr = pos.atr_entrada
                if serie is not None and i >= 0:
                    import math
                    v = float(serie.atr[i])
                    if not math.isnan(v):
                        atr = v
                cartera.actualizar(
                    salidas_mod.actualizar_trinquete(pos, float(sesion["cierre"]), atr, cfg)
                )

            # 6. Revision semanal del mercado: salidas y candidatas.
            for mid, corte in decisiones.get(dia, []):
                if mid != mercado_id:
                    continue
                _revisar(
                    dia, mercado_id, vista, cartera, cfg, mapa,
                    pendientes_venta, ejecuciones, eventos,
                    rondas.setdefault(corte, _Ronda()),
                )

        # 7. Reparto global de huecos, cuando ya han decidido todos los mercados
        #    de la semana.
        for corte in repartos.get(dia, []):
            ronda = rondas.pop(corte, None)
            if ronda is not None:
                _repartir(dia, ronda, vista, cal, cartera, cfg, pendientes_compra, eventos)

        curva.append(_valorar(dia, cartera, vista, cfg))

    # Cierre de lo que siga abierto al final, para que la curva sea completa.
    posiciones_finales = cartera.n_posiciones
    if posiciones_finales:
        vista = instantanea.vista(fin)
        for ticker in list(cartera.posiciones):
            pos = cartera.posiciones[ticker]
            serie = vista.serie(ticker)
            i = vista.posicion_hasta(ticker)
            precio = float(serie.cierre[i]) if serie is not None and i >= 0 else pos.precio_entrada_local
            ext = _cerrar(
                cartera, ticker, fin, precio, vista, cfg,
                MotivoSalida.ABIERTA_AL_FINAL, eventos,
                cfg.reglas.mercado(pos.mercado).divisa,
            )
            impuesto_extrapolado = impuesto_extrapolado or ext
        # La curva termina DESPUES de liquidar: su ultimo punto es el efectivo
        # que queda de verdad, con los costes de salida ya pagados. Asi el
        # resumen y las operaciones cuentan la misma historia.
        final = _valorar(fin, cartera, vista, cfg)
        if curva and curva[-1]["fecha"] == fin:
            curva[-1] = final
        else:
            curva.append(final)

    return Resultado(
        curva=pd.DataFrame(curva),
        operaciones=cartera.operaciones,
        eventos=eventos,
        inicio=inicio,
        fin=fin,
        capital_inicial=cfg.reglas.cartera.capital_inicial_eur,
        sectores_sin_mapear=mapa.sin_mapear,
        posiciones_finales=posiciones_finales,
        impuesto_extrapolado=impuesto_extrapolado,
    )


# --------------------------------------------------------------------------
# Piezas del bucle
# --------------------------------------------------------------------------


def _inicio_con_calentamiento(inicio: date, cfg: Config) -> date:
    """Primera fecha en que se puede decidir con las series completas."""
    from datetime import timedelta

    tec = cfg.reglas.tecnico
    sesiones = max(tec.media_larga, tec.regimen_mercado_media) + tec.atr_periodo
    meses = tec.momentum_meses + tec.momentum_excluir_meses
    # Se toma el mas exigente de los dos, con holgura para festivos.
    dias = max(int(sesiones * 1.45), int(meses * 31))
    return inicio + timedelta(days=dias)


@dataclass
class _Ronda:
    """Lo que cada mercado aporta a la revision de una semana.

    Se va llenando en la sesion de decision de cada mercado y se reparte de una
    vez cuando ha decidido el ultimo. Las senales, los ratios y el cambio se
    calculan en la sesion de cada mercado, con sus datos de ese dia.
    """

    comprables: dict = field(default_factory=dict)
    sectores: dict[str, str] = field(default_factory=dict)
    cohorte: dict = field(default_factory=dict)
    regimen: dict[str, bool] = field(default_factory=dict)
    fx: dict[str, float] = field(default_factory=dict)
    decision: dict[str, date] = field(default_factory=dict)
    ejecucion: dict[str, date] = field(default_factory=dict)


def _revisar(
    dia: date,
    mercado_id: str,
    vista,
    cartera: Cartera,
    cfg: Config,
    mapa: MapaSectores,
    pendientes_venta: dict,
    ejecuciones: dict,
    eventos: list[Evento],
    ronda: _Ronda,
) -> None:
    """Revision semanal de un mercado: salidas por regla y candidatas.

    Las compras no se deciden aqui: las candidatas se guardan en la ronda de la
    semana y se reparten junto con las de los demas mercados en `_repartir`.
    """
    ejecucion = ejecuciones.get((mercado_id, dia))
    if ejecucion is None:
        return
    fecha_ejecucion = ejecucion.date()
    clave = f"{mercado_id}|{fecha_ejecucion.isoformat()}"

    del_mercado = universo_mod.evaluar(dia, vista, cfg, mapa, solo_mercado=mercado_id)

    # Salidas por regla semanal sobre las posiciones de este mercado.
    for ticker in list(cartera.posiciones):
        pos = cartera.posiciones[ticker]
        if pos.mercado != mercado_id:
            continue
        senal = tecnico_mod.senal(ticker, mercado_id, dia, vista, cfg)
        if senal is None:
            continue
        aprueba = fundamental_mod.sigue_aprobando(
            ticker, pos.sector, dia, vista, cfg, senal.cierre
        )
        salida = salidas_mod.evaluar_salida_semanal(
            pos, senal.cierre, senal.media_larga, aprueba, cfg
        )
        if salida is not None:
            pendientes_venta.setdefault(clave, []).append((ticker, salida.motivo))
            eventos.append(
                Evento(dia, "salida_programada", mercado_id, ticker, str(salida.motivo))
            )

    regimen = tecnico_mod.regimen_por_mercado(dia, vista, cfg)
    ronda.regimen[mercado_id] = bool(regimen.get(mercado_id, False))
    if not ronda.regimen[mercado_id]:
        eventos.append(Evento(dia, "regimen_apagado", mercado_id))
        return

    # Senales tecnicas de los elegibles de este mercado. Las que ya estan en
    # cartera tambien cuentan: forman parte de la cohorte del percentil de
    # momentum, y la nota de una candidata no debe depender de lo que se tenga.
    # Al repartir se descartan con `ya_en_cartera`.
    senales: dict = {}
    for ticker, eleg in del_mercado.items():
        if not eleg.elegible:
            continue
        senal = tecnico_mod.senal(ticker, mercado_id, dia, vista, cfg)
        senales[ticker] = senal
        if senal is None or not senal.comprable:
            continue
        ronda.comprables[ticker] = senal
        ronda.sectores[ticker] = eleg.sector

    # Ratios fundamentales de la cohorte elegible del mercado. Se puntuan al
    # repartir, con las de todos los mercados, para que el recurso al bloque
    # tenga con quien comparar.
    if cfg.reglas.fundamental.activo:
        for ticker, eleg in del_mercado.items():
            if not eleg.elegible:
                continue
            # El precio de la fecha de decision entra en el calculo del EV: la
            # valoracion tiene que moverse con el precio, no quedarse congelada
            # entre publicaciones de resultados.
            senal_valor = senales.get(ticker)
            ratios = fundamental_mod.ratios_de(
                ticker, vista.fundamentales(ticker), cfg, dia,
                senal_valor.cierre if senal_valor else None,
            )
            if ratios is not None:
                ronda.cohorte[ticker] = (ratios, mercado_id, eleg.sector)

    divisa = cfg.reglas.mercado(mercado_id).divisa
    try:
        ronda.fx[divisa] = vista.fx_decision(
            divisa, dia, cfg.reglas.datos.fx_decision_dia_anterior,
            cfg.reglas.cartera.divisa_base,
        )
    except Exception:
        # Sin cambio no se puede dimensionar: sus candidatas se rechazan al
        # repartir con `sin_precio_ejecucion`, y queda constancia.
        pass

    ronda.decision[mercado_id] = dia
    ronda.ejecucion[mercado_id] = fecha_ejecucion


def _repartir(
    dia: date,
    ronda: _Ronda,
    vista,
    cal: Calendarios,
    cartera: Cartera,
    cfg: Config,
    pendientes_compra: dict,
    eventos: list[Evento],
) -> None:
    """Reparto de huecos de la semana, una sola vez para todos los mercados.

    Las candidatas de todos los mercados se ordenan en una lista global y se
    asignan de mejor a peor contra un unico estado reservado de la cartera: los
    topes de posiciones, sector y mercado y el efectivo se consumen una sola vez.
    """
    if not ronda.comprables:
        return

    puntuaciones: dict = {}
    if cfg.reglas.fundamental.activo:
        puntuaciones = fundamental_mod.puntuar(ronda.cohorte, cfg)

    candidatas = seleccion_mod.ordenar_candidatas(
        dia, ronda.comprables, puntuaciones, ronda.sectores, cfg
    )
    # Las que ya estan en cartera solo servian de cohorte para los percentiles.
    # Se quitan antes de asignar para que no llenen el registro de rechazos
    # todas las semanas ni ocupen puestos del ranking.
    candidatas = [c for c in candidatas if not cartera.tiene(c.ticker)]
    if not candidatas:
        return

    precios_base = _precios_base(cartera, vista, cfg, dia)
    capital = cartera.valor(precios_base)

    asignacion = ordenes_mod.asignar(
        dia, candidatas, cartera, ronda.regimen, ronda.fx, capital, cfg
    )
    for orden in asignacion.ordenes:
        mercado_id = orden.mercado
        decision = ronda.decision[mercado_id]
        ejecucion = ronda.ejecucion[mercado_id]
        pendientes_compra.setdefault(
            f"{mercado_id}|{ejecucion.isoformat()}", []
        ).append(orden)
        eventos.append(
            Evento(dia, "orden", mercado_id, orden.ticker, detalles={
                "acciones": orden.acciones, "rango": orden.rango_asignacion,
                "puntuacion": round(orden.puntuacion_final, 2),
                "riesgo_teorico_pct": orden.riesgo_teorico_pct,
                "riesgo_efectivo_pct": round(orden.riesgo_efectivo_pct, 5),
                "limitada_por_peso_maximo": orden.limitada_por_peso_maximo,
                "sesiones_de_retraso": cal.sesiones_de_retraso(mercado_id, decision, ejecucion),
            })
        )
    for r in asignacion.rechazos:
        eventos.append(
            Evento(dia, "rechazo", r.mercado, r.ticker, str(r.motivo),
                   {"rango": r.rango, "puntuacion": round(r.puntuacion_final, 2)})
        )


def _abrir(
    cartera: Cartera, orden: Orden, dia: date, vista, cfg: Config,
    eventos: list[Evento], divisa: str,
) -> bool:
    """Ejecuta una compra a la apertura. Devuelve si el impuesto se extrapolo."""
    sesion = vista.precio_en(orden.ticker, dia)
    if sesion is None:
        eventos.append(
            Evento(dia, "rechazo", orden.mercado, orden.ticker, "sin_precio_ejecucion")
        )
        return False
    if cartera.tiene(orden.ticker):
        return False

    apertura = float(sesion["apertura"])
    precio_pagado = costes_mod.precio_con_deslizamiento(
        apertura, "compra", orden.mercado, cfg
    )
    cambio = vista.fx(divisa, dia, cfg.reglas.cartera.divisa_base)
    nominal_base = orden.acciones * apertura * cambio
    costes = costes_mod.calcular(
        orden.ticker, orden.mercado, "compra", nominal_base, dia, cfg
    )
    desembolso = orden.acciones * precio_pagado * cambio + costes.comision + costes.impuesto

    if desembolso > cartera.efectivo:
        eventos.append(
            Evento(dia, "rechazo", orden.mercado, orden.ticker, "efectivo_insuficiente")
        )
        return False

    precio_base = precio_pagado * cambio
    posicion = Posicion(
        ticker=orden.ticker,
        mercado=orden.mercado,
        sector=orden.sector,
        divisa=divisa,
        acciones=orden.acciones,
        fecha_entrada=dia,
        precio_entrada_local=precio_pagado,
        precio_entrada_base=precio_base,
        fx_entrada=cambio,
        atr_entrada=orden.atr_entrada,
        # El stop se ancla al precio realmente pagado, no al de referencia.
        stop_inicial_local=salidas_mod.stop_inicial(precio_pagado, orden.atr_entrada, cfg),
        maximo_cierre_local=precio_pagado,
        stop_dinamico_local=salidas_mod.stop_dinamico_bruto(
            precio_pagado, orden.atr_entrada, cfg
        ),
        coste_entrada_base=costes.total,
        deslizamiento_entrada_base=costes.deslizamiento,
        riesgo_teorico_pct=orden.riesgo_teorico_pct,
        riesgo_efectivo_pct=orden.riesgo_efectivo_pct,
        ultimo_cierre_local=float(sesion["cierre"]),
    )
    cartera.abrir(posicion, desembolso)
    eventos.append(
        Evento(dia, "compra", orden.mercado, orden.ticker, detalles={
            "acciones": orden.acciones, "precio_local": round(precio_pagado, 4),
            "coste_base": round(costes.total, 2),
        })
    )
    return costes.impuesto_extrapolado


def _cerrar(
    cartera: Cartera, ticker: str, dia: date, precio_local: float, vista,
    cfg: Config, motivo: MotivoSalida, eventos: list[Evento], divisa: str,
) -> bool:
    """Cierra una posicion. Devuelve si el impuesto se extrapolo."""
    if not cartera.tiene(ticker):
        return False
    pos = cartera.posiciones[ticker]
    precio_cobrado = costes_mod.precio_con_deslizamiento(
        precio_local, "venta", pos.mercado, cfg
    )
    cambio = vista.fx(divisa, dia, cfg.reglas.cartera.divisa_base)
    nominal_base = pos.acciones * precio_local * cambio
    costes = costes_mod.calcular(ticker, pos.mercado, "venta", nominal_base, dia, cfg)
    ingreso = pos.acciones * precio_cobrado * cambio - costes.comision - costes.impuesto

    operacion = cartera.cerrar(
        ticker, dia, precio_cobrado, cambio, ingreso, costes.total, motivo,
        deslizamiento_salida_base=costes.deslizamiento,
    )
    eventos.append(
        Evento(dia, "venta", pos.mercado, ticker, str(motivo), {
            "resultado_base": round(operacion.resultado_base, 2),
            "dias": operacion.dias,
        })
    )
    return costes.impuesto_extrapolado


def _precios_base(cartera: Cartera, vista, cfg: Config, dia: date) -> dict[str, float]:
    """Precio en divisa base de cada posicion abierta.

    Si el mercado esta cerrado hoy se usa el ultimo cierre local disponible pero
    el cambio de HOY: la divisa se mueve aunque la bolsa no abra.
    """
    salida: dict[str, float] = {}
    for ticker, pos in cartera.posiciones.items():
        serie = vista.serie(ticker)
        i = vista.posicion_hasta(ticker)
        if serie is None or i < 0:
            salida[ticker] = pos.precio_entrada_base
            continue
        try:
            cambio = vista.fx(pos.divisa, dia, cfg.reglas.cartera.divisa_base)
        except Exception:
            cambio = pos.fx_entrada
        salida[ticker] = float(serie.cierre[i]) * cambio
    return salida


def _valorar(dia: date, cartera: Cartera, vista, cfg: Config) -> dict:
    precios_base = _precios_base(cartera, vista, cfg, dia)
    valor = cartera.valor(precios_base)
    invertido = valor - cartera.efectivo
    return {
        "fecha": dia,
        "valor": valor,
        "efectivo": cartera.efectivo,
        "n_posiciones": cartera.n_posiciones,
        "exposicion": invertido / valor if valor else 0.0,
    }
