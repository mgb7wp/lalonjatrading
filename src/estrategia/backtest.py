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
   semana para ese mercado: salidas por regla y **recogida** de candidatas.
   Aqui todavia no se compra nada.

Y al final del dia, fuera del bucle de mercados:

7. **Asignacion conjunta** de los cortes cuya ultima sesion de decision es hoy.
   Las candidatas de los cinco mercados, cada una calculada con la vista de su
   propia sesion de decision, se puntuan y ordenan juntas y se reparten los
   huecos una sola vez. Asi el orden lo marca la puntuacion y no el orden de
   los mercados en la configuracion: antes cada mercado asignaba por su cuenta
   al revisar, y como el viernes los cinco deciden el mismo dia y el bucle los
   recorre en el orden del YAML, Espana elegia huecos primero todas las
   semanas. Es factible porque todas las decisiones de un corte son
   anteriores a cualquiera de sus ejecuciones (la decision cierra en o antes
   del corte, la ejecucion abre despues), y el motor lo comprueba.

   **Cambia los resultados** respecto a backtests anteriores a este cambio: el
   reparto de huecos entre mercados es otro, y las cohortes de percentiles
   pueden recurrir al bloque con los demas mercados, que antes no veian.

Las salidas se procesan antes que las entradas para que un hueco liberado hoy
se pueda usar en la asignacion de la semana siguiente. Un hueco que se libera el
lunes no se rellena hasta el siguiente corte semanal: es mas simple y mas
conservador que reabrir la lista a media semana.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    # sobre series a medias.
    inicio_efectivo = _inicio_con_calentamiento(inicio, cfg)

    pendientes_compra: dict[str, list[Orden]] = {}
    pendientes_venta: dict[str, list[tuple[str, MotivoSalida]]] = {}
    decisiones: dict[date, list[tuple[str, pd.Timestamp]]] = {}

    # Se precalcula, por corte semanal, que sesion decide y cual ejecuta en cada
    # mercado. Asi el bucle diario solo consulta un diccionario.
    ejecuciones: dict[tuple[str, date], pd.Timestamp] = {}
    cortes_que_asignan = _cortes_que_asignan(cal, inicio_efectivo, fin)
    for cortes in cortes_que_asignan.values():
        for corte, por_mercado in cortes:
            for mercado_id, (d, e) in por_mercado.items():
                decisiones.setdefault(d, []).append((mercado_id, corte))
                ejecuciones[(mercado_id, d)] = pd.Timestamp(e)
    # Lo que cada mercado aporta a la asignacion conjunta de su corte.
    recogidas: dict[pd.Timestamp, _Recogida] = {}

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

            # 6. Revision semanal.
            for mid, corte in decisiones.get(dia, []):
                if mid != mercado_id:
                    continue
                _revisar(
                    dia, mercado_id, corte, vista, cartera, cfg, mapa,
                    pendientes_venta, ejecuciones, eventos,
                    recogidas.setdefault(corte, _Recogida()),
                )

        # 7. Asignacion conjunta de los cortes que ya tienen todas sus
        # decisiones.
        for corte, _ in cortes_que_asignan.get(dia, []):
            _asignar_corte(
                dia, recogidas.pop(corte, _Recogida()), vista, cal, cartera, cfg,
                pendientes_compra, ejecuciones, eventos,
            )

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
            _cerrar(
                cartera, ticker, fin, precio, vista, cfg,
                MotivoSalida.ABIERTA_AL_FINAL, eventos,
                cfg.reglas.mercado(pos.mercado).divisa,
            )

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
class _Recogida:
    """Lo que los mercados de un corte aportan a su asignacion conjunta.

    Cada entrada se calcula con la vista de la sesion de decision de su
    mercado, asi que juntarlas no anticipa nada: todas son anteriores al corte.
    """

    comprables: dict = field(default_factory=dict)
    sectores: dict[str, str] = field(default_factory=dict)
    cohorte: dict = field(default_factory=dict)
    fx: dict[str, float] = field(default_factory=dict)
    regimen: dict[str, bool] = field(default_factory=dict)
    decision: dict[str, date] = field(default_factory=dict)


def _cortes_que_asignan(
    cal: Calendarios, inicio_efectivo: date, fin: date
) -> dict[date, list[tuple[pd.Timestamp, dict[str, tuple[date, date]]]]]:
    """Para cada dia, los cortes cuya ultima sesion de decision es ese dia.

    Devuelve, por corte, la sesion de decision y la de ejecucion de cada
    mercado que participa. Comprueba de paso la condicion que hace posible
    asignar al final: la ultima decision de un corte tiene que ser anterior a
    su primera ejecucion. Si no lo fuera, un mercado ejecutaria antes de que
    se hubiera asignado, y la orden se perderia sin avisar.
    """
    salida: dict[date, list] = {}
    for corte in cal.cortes_semanales:
        por_mercado: dict[str, tuple[date, date]] = {}
        for mercado_id in cal.mercados():
            d = cal.sesion_de_decision(mercado_id, corte)
            e = cal.sesion_de_ejecucion(mercado_id, corte)
            if d is None or e is None or d < inicio_efectivo or e > fin:
                continue
            por_mercado[mercado_id] = (d, e)
        if not por_mercado:
            continue
        ultima = max(d for d, _ in por_mercado.values())
        primera_ejecucion = min(e for _, e in por_mercado.values())
        if ultima >= primera_ejecucion:
            raise ErrorDatos(
                f"el corte {corte} tiene una decision el {ultima} y una "
                f"ejecucion el {primera_ejecucion}: no se puede asignar de forma "
                f"conjunta sin ejecutar antes de decidir"
            )
        salida.setdefault(ultima, []).append((corte, por_mercado))
    return salida


def _revisar(
    dia: date,
    mercado_id: str,
    corte,
    vista,
    cartera: Cartera,
    cfg: Config,
    mapa: MapaSectores,
    pendientes_venta: dict,
    ejecuciones: dict,
    eventos: list[Evento],
    recogida: _Recogida,
) -> None:
    """Revision semanal de un mercado: salidas por regla y recogida de candidatas.

    No compra: deja en `recogida` lo necesario para que `_asignar_corte`
    reparta los huecos entre todos los mercados del corte a la vez.
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

    recogida.decision[mercado_id] = dia
    regimen = tecnico_mod.regimen_por_mercado(dia, vista, cfg)
    recogida.regimen[mercado_id] = bool(regimen.get(mercado_id, False))
    if not recogida.regimen[mercado_id]:
        eventos.append(Evento(dia, "regimen_apagado", mercado_id))
        return

    # Senales tecnicas de los elegibles de este mercado.
    comprables: dict = {}
    for ticker, eleg in del_mercado.items():
        if not eleg.elegible or cartera.tiene(ticker):
            continue
        senal = tecnico_mod.senal(ticker, mercado_id, dia, vista, cfg)
        if senal is None or not senal.comprable:
            continue
        comprables[ticker] = senal
        recogida.sectores[ticker] = eleg.sector

    if not comprables:
        return

    divisa = cfg.reglas.mercado(mercado_id).divisa
    try:
        recogida.fx[divisa] = vista.fx_decision(
            divisa, dia, cfg.reglas.datos.fx_decision_dia_anterior,
            cfg.reglas.cartera.divisa_base,
        )
    except Exception:
        return
    recogida.comprables.update(comprables)

    # Cohorte fundamental: todos los elegibles del mercado, no solo los
    # comprables. Se puntua despues, junto con los demas mercados, para que
    # un mercado con poca gente pueda recurrir a su bloque.
    if cfg.reglas.fundamental.activo:
        for ticker, eleg in del_mercado.items():
            if not eleg.elegible:
                continue
            # El precio de la fecha de decision entra en el calculo del EV: la
            # valoracion tiene que moverse con el precio, no quedarse congelada
            # entre publicaciones de resultados.
            senal_valor = tecnico_mod.senal(ticker, mercado_id, dia, vista, cfg)
            ratios = fundamental_mod.ratios_de(
                ticker, vista.fundamentales(ticker), cfg, dia,
                senal_valor.cierre if senal_valor else None,
            )
            if ratios is not None:
                recogida.cohorte[ticker] = (ratios, mercado_id, eleg.sector)


def _asignar_corte(
    dia: date,
    recogida: _Recogida,
    vista,
    cal: Calendarios,
    cartera: Cartera,
    cfg: Config,
    pendientes_compra: dict,
    ejecuciones: dict,
    eventos: list[Evento],
) -> None:
    """Puntua, ordena y reparte los huecos de un corte entre todos sus mercados."""
    if not recogida.comprables:
        return

    puntuaciones: dict = {}
    if cfg.reglas.fundamental.activo:
        puntuaciones = fundamental_mod.puntuar(recogida.cohorte, cfg)

    candidatas = seleccion_mod.ordenar_candidatas(
        dia, recogida.comprables, puntuaciones, recogida.sectores, cfg
    )
    # Cada candidata conserva la fecha en que decidio su mercado.
    candidatas = [
        replace(c, fecha_decision=recogida.decision.get(c.mercado, dia))
        for c in candidatas
    ]
    if not candidatas:
        return

    # El capital se valora hoy, la ultima sesion de decision del corte: es
    # posterior a las demas, pero sigue siendo anterior al corte.
    capital = cartera.valor(_precios_base(cartera, vista, cfg, dia))

    # Lo decidido y aun sin ejecutar ocupa hueco. Con la asignacion conjunta
    # normalmente no queda nada de cortes anteriores, pero si un mercado estuvo
    # cerrado puede quedar una orden en vuelo.
    pendientes = [o for lista in pendientes_compra.values() for o in lista]
    asignacion = ordenes_mod.asignar(
        dia, candidatas, cartera, recogida.regimen, recogida.fx, capital, cfg,
        pendientes=pendientes,
    )
    for orden in asignacion.ordenes:
        decision = recogida.decision[orden.mercado]
        fecha_ejecucion = ejecuciones[(orden.mercado, decision)].date()
        clave = f"{orden.mercado}|{fecha_ejecucion.isoformat()}"
        pendientes_compra.setdefault(clave, []).append(orden)
        eventos.append(
            Evento(decision, "orden", orden.mercado, orden.ticker, detalles={
                "acciones": orden.acciones, "rango": orden.rango_asignacion,
                "puntuacion": round(orden.puntuacion_final, 2),
                "riesgo_teorico_pct": orden.riesgo_teorico_pct,
                "riesgo_efectivo_pct": round(orden.riesgo_efectivo_pct, 5),
                "limitada_por_peso_maximo": orden.limitada_por_peso_maximo,
                "sesiones_de_retraso": cal.sesiones_de_retraso(
                    orden.mercado, decision, fecha_ejecucion
                ),
            })
        )
    for r in asignacion.rechazos:
        eventos.append(
            Evento(recogida.decision.get(r.mercado, dia), "rechazo", r.mercado,
                   r.ticker, str(r.motivo),
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
        coste_entrada_base=costes.comision + costes.impuesto + costes.deslizamiento,
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
        ticker, dia, precio_cobrado, cambio, ingreso,
        costes.comision + costes.impuesto + costes.deslizamiento, motivo,
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
