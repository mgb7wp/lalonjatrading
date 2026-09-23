"""Diagnostico de fuentes: que resuelve cada una y que no.

Existe por un motivo concreto. Esta app se ha desarrollado entera sin acceso a
ningun proveedor real, asi que la primera ejecucion con datos de verdad va a
encontrarse con tickers que no existen, sectores que el mapeo no conoce, campos
de los estados financieros con otro nombre y empresas que reportan en una divisa
distinta de la de su cotizacion. Lo util no es que eso reviente con una traza en
el ticker numero 37: es obtener la lista entera de una vez, para arreglarla de
una pasada.

La comprobacion que mas importa es la del EV. El fallo que motivo buena parte de
este trabajo —una fuente que devolvia el EV siempre vacio y dejaba media
puntuacion fundamental muerta en silencio— no se veia por ningun lado. Aqui se
ve: si la columna de EV no se puede calcular para nadie, sale en primera linea.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from . import fundamental as fundamental_mod
from .config import Config
from .constantes import SECTOR_DESCONOCIDO
from .datos import contrato
from .datos.enrutador import Enrutador
from .sectores import MapaSectores


@dataclass
class FilaDiagnostico:
    """Lo que se ha podido averiguar de un valor."""

    ticker: str
    mercado: str
    sesiones: int = 0
    primera: date | None = None
    ultima: date | None = None
    sector_proveedor: str | None = None
    sector_traducido: str = SECTOR_DESCONOCIDO
    sector_mapeado: bool = False
    # El sector se salvo por el respaldo de universo.yaml y no por el mapeo. No
    # es un fallo, pero si deuda de configuracion: el proveedor esta devolviendo
    # algo que nadie ha traducido.
    sector_por_respaldo: bool = False
    ejercicios: int = 0
    fechas_publicacion_reales: int = 0
    divisa_reporte: str | None = None
    divisa_cotizacion: str | None = None
    campos_vacios: list[str] = field(default_factory=list)
    ev_calculable: bool = False
    motivo_sin_ev: str | None = None
    problemas: list[str] = field(default_factory=list)

    @property
    def utilizable(self) -> bool:
        return self.sesiones > 0 and self.sector_mapeado and not self.problemas


CAMPOS_VIGILADOS = [
    "roe",
    "margen_operativo",
    "ventas",
    "ebit",
    "ebitda",
    "deuda_neta",
    "patrimonio_neto",
    "flujo_caja_libre",
    "acciones_en_circulacion",
]


def ejecutar(
    cfg: Config,
    inicio: date,
    fin: date,
    tickers: list[str] | None = None,
) -> list[FilaDiagnostico]:
    """Recorre el universo y averigua que sirve cada fuente."""
    enrutador = Enrutador(cfg, verificar=False)
    mapa = MapaSectores(cfg)
    universo = tickers or cfg.universo.tickers()

    precios = enrutador.precios(universo, inicio, fin)
    fundamentales = enrutador.fundamentales(universo, inicio, fin)
    sectores = enrutador.sectores(universo)

    por_ticker_p = (
        {t: g for t, g in precios.groupby("ticker")} if not precios.empty else {}
    )
    por_ticker_f = (
        {t: g for t, g in fundamentales.groupby("ticker")}
        if not fundamentales.empty
        else {}
    )

    filas: list[FilaDiagnostico] = []
    for ticker in universo:
        mercado = cfg.universo.mercado_de_ticker.get(ticker, "?")
        fila = FilaDiagnostico(ticker=ticker, mercado=mercado)

        serie = por_ticker_p.get(ticker)
        if serie is not None:
            serie = serie.sort_values("fecha")
        if serie is None or serie.empty:
            fila.problemas.append("sin serie de precios")
        else:
            fila.sesiones = len(serie)
            fila.primera = serie["fecha"].min()
            fila.ultima = serie["fecha"].max()
            if fila.ultima < fin - pd.Timedelta(days=30).to_pytimedelta():
                fila.problemas.append(f"precios desfasados (ultimo {fila.ultima})")

        fila.sector_proveedor = sectores.get(ticker)
        directo = cfg.implementacion.sector(fila.sector_proveedor)
        clasificacion = mapa.clasificar(ticker, fila.sector_proveedor)
        fila.sector_traducido = clasificacion.sector
        fila.sector_mapeado = clasificacion.sector != SECTOR_DESCONOCIDO
        fila.sector_por_respaldo = (
            fila.sector_mapeado and directo == SECTOR_DESCONOCIDO
        )
        if not fila.sector_mapeado:
            fila.problemas.append(
                f"sector sin mapear: {fila.sector_proveedor!r}"
            )

        fund = por_ticker_f.get(ticker)
        if fund is None or fund.empty:
            fila.problemas.append("sin fundamentales")
        else:
            # Ordenados por fin de periodo: Yahoo los da del mas reciente al
            # mas antiguo, y sin ordenar el "ultimo" era el mas viejo.
            anuales = fund[fund["periodo"] == "anual"].sort_values("fin_periodo")
            fila.ejercicios = len(anuales)
            if "origen_fecha_publicacion" in anuales.columns:
                fila.fechas_publicacion_reales = int(
                    (anuales["origen_fecha_publicacion"] == "proveedor").sum()
                )
            fila.campos_vacios = [
                c for c in CAMPOS_VIGILADOS
                if c in anuales.columns and anuales[c].isna().all()
            ]
            if fila.campos_vacios:
                fila.problemas.append(
                    f"campos siempre vacios: {', '.join(fila.campos_vacios)}"
                )

            ultimo = anuales.iloc[-1] if not anuales.empty else None
            if ultimo is not None:
                fila.divisa_reporte = ultimo.get("divisa_reporte")
                fila.divisa_cotizacion = ultimo.get("divisa_cotizacion")
                # El EV va con el precio sin ajustar por dividendos, como en el
                # backtest.
                precio = (
                    float(serie.iloc[-1]["cierre_bruto"])
                    if serie is not None and not serie.empty
                    else None
                )
                ev, motivo = fundamental_mod.valor_empresa(ultimo, precio)
                fila.ev_calculable = ev is not None
                fila.motivo_sin_ev = motivo
                if not fila.ev_calculable:
                    fila.problemas.append(f"sin EV ({motivo})")

            # El crecimiento de ventas a tres anos necesita cuatro ejercicios.
            if fila.ejercicios < 4:
                fila.problemas.append(
                    f"solo {fila.ejercicios} ejercicios: no hay crecimiento a 3 anos"
                )

        filas.append(fila)
    return filas


@dataclass
class FilaAuxiliar:
    """Un dato que no es un valor del universo pero sin el que no se opera:
    el indice de regimen de un mercado, un ETF de referencia o una divisa."""

    tipo: str  # "indice", "referencia" o "divisa"
    nombre: str
    ticker: str
    filas: int = 0
    ultima: date | None = None
    problemas: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)

    @property
    def utilizable(self) -> bool:
        return self.filas > 0 and not self.problemas


def comprobar_auxiliares(
    cfg: Config, inicio: date, fin: date, hoy: date | None = None
) -> list[FilaAuxiliar]:
    """Indices de regimen, ETF de referencia y divisas.

    Sin el indice de un mercado, el regimen de ese mercado nunca se enciende y
    no compra nada; sin una divisa, no se puede valorar ni dimensionar. Son
    pocos datos y ninguno sale en la lista de valores, asi que se comprueban
    aparte.
    """
    hoy = hoy or date.today()
    enrutador = Enrutador(cfg, verificar=False, hoy=hoy)
    filas: list[FilaAuxiliar] = []

    for mercado, ticker in sorted(cfg.reglas.tecnico.indices_regimen.items()):
        filas.append(FilaAuxiliar("indice", f"regimen {mercado}", ticker))
    for nombre, ref in sorted(cfg.implementacion.referencias.items()):
        filas.append(FilaAuxiliar("referencia", nombre, ref.ticker))

    try:
        precios = enrutador.precios([f.ticker for f in filas], inicio, fin)
    except Exception as exc:  # noqa: BLE001 - se informa, no se revienta
        precios = pd.DataFrame()
        for f in filas:
            f.problemas.append(f"fallo al descargar: {exc}")
    limite_precio = fin - timedelta(days=30)
    for f in filas:
        serie = precios[precios["ticker"] == f.ticker] if not precios.empty else precios
        if serie.empty:
            if not f.problemas:
                f.problemas.append("sin serie de precios")
            continue
        f.filas = len(serie)
        f.ultima = max(serie["fecha"])
        if f.ultima < limite_precio:
            f.problemas.append(f"precios desfasados (ultimo {f.ultima})")

    base = cfg.reglas.cartera.divisa_base
    divisas = sorted(
        ({m.divisa for m in cfg.reglas.universo.mercados}
         | {r.divisa for r in cfg.implementacion.referencias.values()}) - {base}
    )
    fx_filas = [
        FilaAuxiliar("divisa", d, cfg.implementacion.divisas.get(d) or "?") for d in divisas
    ]
    try:
        fx = enrutador.fx(divisas, inicio, fin)
    except Exception as exc:  # noqa: BLE001
        fx = pd.DataFrame()
        for f in fx_filas:
            f.problemas.append(f"fallo al descargar: {exc}")
    limite = cfg.reglas.datos.fx_antiguedad_maxima_dias
    referencia = min(fin, hoy - timedelta(days=1))
    for f in fx_filas:
        serie = fx[fx["divisa"] == f.nombre] if not fx.empty else fx
        if serie.empty:
            if not f.problemas:
                f.problemas.append("sin tipo de cambio")
            continue
        f.filas = len(serie)
        f.ultima = max(pd.to_datetime(serie["fecha"]).dt.date)
        if (referencia - f.ultima).days > limite:
            f.problemas.append(
                f"cambio con mas de {limite} dias de antiguedad (ultimo {f.ultima})"
            )
        f.notas += contrato.huecos_fx(serie, limite)
    return filas + fx_filas


def a_texto(
    filas: list[FilaDiagnostico],
    cfg: Config,
    detalle: bool = False,
    auxiliares: list[FilaAuxiliar] | None = None,
) -> str:
    """Resumen legible, con lo que hay que arreglar en primer lugar."""
    total = len(filas)
    ok = [f for f in filas if f.utilizable]
    lineas: list[str] = [
        "# Diagnostico de fuentes",
        "",
        f"Valores utilizables: {len(ok)} de {total}",
        "",
    ]

    if auxiliares is not None:
        malos = [a for a in auxiliares if not a.utilizable]
        lineas.append("## Indices, referencias y divisas")
        lineas.append("")
        if not malos:
            lineas.append(
                f"Los {len(auxiliares)} datos auxiliares llegan completos y al dia."
            )
        else:
            lineas.append(
                f"**{len(malos)} de {len(auxiliares)} fallan.** Sin el indice de un "
                f"mercado no se enciende su regimen y no compra nada; sin una "
                f"divisa no se puede valorar ni dimensionar."
            )
        lineas.append("")
        for a in auxiliares:
            estado = "OK" if a.utilizable else "; ".join(a.problemas)
            lineas.append(
                f"- {a.tipo} {a.nombre} ({a.ticker}): {estado}"
                + (f", ultimo {a.ultima}" if a.ultima and a.utilizable else "")
            )
            for nota in a.notas:
                lineas.append(f"  - {nota}")
        lineas.append("")

    enrutador = Enrutador(cfg, verificar=False)
    lineas.append("## Reparto de fuentes")
    lineas.append("")
    for tipo, fuente in enrutador.reparto.items():
        lineas.append(f"- {tipo}: {fuente}")
    lineas.append("")

    # Lo primero, porque es lo que puede estar roto sin que se note.
    sin_ev = [f for f in filas if f.ejercicios and not f.ev_calculable]
    lineas.append("## Valoracion (EV/EBIT)")
    lineas.append("")
    if not sin_ev:
        lineas.append("Todos los valores con fundamentales tienen EV calculable.")
    else:
        lineas.append(
            f"**{len(sin_ev)} de {total} valores no tienen EV calculable.** Sin EV "
            f"la valoracion puntua cero, asi que si esto afecta a muchos valores "
            f"la mitad del peso de la puntuacion fundamental no esta haciendo nada."
        )
        lineas.append("")
        motivos = pd.Series([f.motivo_sin_ev or "?" for f in sin_ev]).value_counts()
        for motivo, n in motivos.items():
            lineas.append(f"- {motivo}: {n}")
    lineas.append("")

    for titulo, filtro in (
        ("Sin serie de precios", lambda f: f.sesiones == 0),
        ("Sector sin mapear", lambda f: not f.sector_mapeado),
        ("Sin fundamentales", lambda f: f.ejercicios == 0),
        (
            "Divisa de reporte distinta de la de cotizacion",
            lambda f: bool(
                f.divisa_reporte
                and f.divisa_cotizacion
                and f.divisa_reporte != f.divisa_cotizacion
            ),
        ),
        ("Menos de 4 ejercicios", lambda f: 0 < f.ejercicios < 4),
        (
            "Sector salvado por el respaldo de universo.yaml",
            lambda f: f.sector_por_respaldo,
        ),
    ):
        afectados = [f for f in filas if filtro(f)]
        if not afectados:
            continue
        lineas.append(f"## {titulo} ({len(afectados)})")
        lineas.append("")
        for f in afectados:
            extra = ""
            if titulo.startswith("Sector"):
                extra = f" -> la fuente devuelve {f.sector_proveedor!r}"
            elif titulo.startswith("Divisa"):
                extra = f" -> reporta en {f.divisa_reporte}, cotiza en {f.divisa_cotizacion}"
            lineas.append(f"- {f.ticker} ({f.mercado}){extra}")
        lineas.append("")

    # Incluye los que se salvaron por el respaldo: el mapeo sigue sin conocer
    # ese sector, y el dia que un valor nuevo llegue sin `sector_declarado` se
    # quedara fuera.
    sin_mapear = {}
    for f in filas:
        if (not f.sector_mapeado or f.sector_por_respaldo) and f.sector_proveedor:
            sin_mapear.setdefault(f.sector_proveedor, []).append(f.ticker)
    if sin_mapear:
        lineas += [
            "## Que anadir a implementacion.yaml",
            "",
            "```yaml",
            "sectores:",
        ]
        for sector, tickers in sorted(sin_mapear.items()):
            lineas.append(f'  "{sector}": ???   # {len(tickers)} valores')
        lineas += ["```", ""]

    # Cobertura de fechas de publicacion reales: es lo que separa un backtest
    # fundamental defendible de uno con las fechas inventadas.
    con_fund = [f for f in filas if f.ejercicios]
    if con_fund:
        reales = sum(f.fechas_publicacion_reales for f in con_fund)
        ejercicios = sum(f.ejercicios for f in con_fund)
        pct = reales / ejercicios if ejercicios else 0.0
        lineas += [
            "## Fechas de publicacion",
            "",
            f"{pct:.0%} de los ejercicios traen fecha real de presentacion; el "
            f"resto se estima sumando el retraso configurado. Cuanto mas alto sea "
            f"este numero, menos depende el backtest de una suposicion.",
            "",
        ]

    if detalle:
        lineas += ["## Detalle", ""]
        tabla = pd.DataFrame(
            [
                {
                    "ticker": f.ticker,
                    "mercado": f.mercado,
                    "sesiones": f.sesiones,
                    "sector": f.sector_traducido,
                    "ejercicios": f.ejercicios,
                    "ev": "si" if f.ev_calculable else "NO",
                    "problemas": "; ".join(f.problemas),
                }
                for f in filas
            ]
        )
        lineas.append(tabla.to_markdown(index=False))
        lineas.append("")

    return "\n".join(lineas)
