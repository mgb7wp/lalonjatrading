"""Informe: metricas, desgloses y avisos.

El documento dedica una seccion entera a los sesgos y pide avisos permanentes.
Este modulo los trata como parte del producto y no como una nota al pie: hay
avisos que salen SIEMPRE, con datos o sin ellos, porque describen limitaciones
estructurales de los datos y no incidencias de una ejecucion concreta.

Los cuatro que mas condicionan la lectura de cualquier resultado de esta app:

- La rentabilidad en euros supone que repatriar el capital fue siempre posible
  al cambio de mercado, cosa que historicamente no ha sido cierta en algunos
  emergentes.
- El universo son las empresas que cotizan HOY, asi que falta todo lo que
  quebro o se excluyo: sesgo de supervivencia, mas fuerte en emergentes.
- El historico fundamental del proveedor gratuito da unos cuatro ejercicios,
  sin fechas de publicacion reales y con las cifras reexpresadas a hoy.
- Los precios ajustados reinvierten los dividendos BRUTOS, y un inversor en
  euros paga retencion en origen por los dividendos de EE. UU., India y Brasil.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from . import metricas as metricas_mod
from .backtest import Resultado
from .config import Config
from .tipos import Aviso


@dataclass
class Informe:
    """Todo lo que el panel o el HTML necesitan para pintarse."""

    resumen: metricas_mod.Resumen
    por_ano: pd.DataFrame
    por_mercado: pd.DataFrame
    por_bloque: pd.DataFrame
    uso_riesgo: metricas_mod.UsoDelRiesgo
    curva: pd.DataFrame
    referencias: dict[str, pd.Series]
    comparaciones: list[metricas_mod.Comparacion]
    operaciones: pd.DataFrame
    eventos: pd.DataFrame
    avisos: list[Aviso]
    rechazos_top: pd.DataFrame
    sensibilidad: pd.DataFrame | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def sintetico(self) -> bool:
        return es_sintetico(str(self.meta.get("origen", "")))


def es_sintetico(origen: str) -> bool:
    """Si en el origen interviene la fuente sintetica, aunque sea para un solo
    tipo de dato.

    El origen de un reparto mixto une las fuentes con `+` (`eodhd+sintetico`).
    Basta con que una sea inventada para que el resultado no valga: unos
    fundamentales reales con precios sinteticos siguen siendo una curva ficticia.

    Se mira cada palabra del origen, no solo las partes separadas por `+`: el
    backtest que corre desde la base de datos de la plataforma se anota como
    `base de datos (sintetico)`, y ese tambien es inventado.
    """
    return "sintetico" in re.findall(r"[a-z_]+", origen.lower())


def _avisos_permanentes() -> list[Aviso]:
    """Los que el documento exige que salgan siempre."""
    return [
        Aviso(
            "repatriacion",
            "La rentabilidad en divisa base supone que la conversión y la salida "
            "de capital fueron siempre posibles al tipo de cambio de mercado. En "
            "algunos mercados emergentes eso no ha sido cierto historicamente: "
            "ha habido controles de cambio y límites a la repatriación en "
            "momentos de estrés, justo cuando más habría importado.",
            permanente=True,
        ),
        Aviso(
            "dividendos_brutos",
            "Los precios ajustados reinvierten los dividendos BRUTOS. Un inversor "
            "en euros paga retención en origen por los dividendos de EE. UU., "
            "India y Brasil, que esta app no modela. La rentabilidad real sería "
            "algo menor que la que aparece aquí.",
            permanente=True,
        ),
    ]


def construir(
    resultado: Resultado,
    cfg: Config,
    instantanea,
    sensibilidad: pd.DataFrame | None = None,
    consultas_validacion: int = 0,
) -> Informe:
    """Ensambla el informe a partir de un resultado de backtest."""
    operaciones = resultado.operaciones_df
    eventos = resultado.eventos_df
    resumen = metricas_mod.resumir(resultado.curva, operaciones, cfg)

    vista_final = instantanea.vista(resultado.fin)
    referencias: dict[str, pd.Series] = {}
    comparaciones: list[metricas_mod.Comparacion] = []
    for nombre in cfg.reglas.referencias_informe:
        serie = metricas_mod.curva_referencia(nombre, resultado.curva, vista_final, cfg)
        if serie is None:
            continue
        referencias[nombre] = serie
        # El inicio real se pasa aparte a proposito: `serie` viene rellenada
        # hacia atras para poder pintarla entera, y medir alfa sobre ese relleno
        # le regalaria a la estrategia todo el tramo anterior al ETF.
        comp = metricas_mod.comparar_con_referencia(
            nombre,
            resultado.curva,
            serie,
            cfg,
            desde=metricas_mod.inicio_real_referencia(nombre, vista_final, cfg),
        )
        if comp is not None:
            comparaciones.append(comp)

    avisos = _avisos_permanentes()
    avisos += _avisos_de_datos(resultado, cfg, instantanea, operaciones, referencias)
    avisos += _aviso_periodo_muerto(resultado, operaciones, cfg)
    avisos += _aviso_cohortes(eventos, cfg)
    avisos += _avisos_de_suficiencia(operaciones, cfg)
    if consultas_validacion:
        avisos.append(
            Aviso(
                "consultas_validacion",
                f"El periodo de validación se ha consultado {consultas_validacion} "
                f"veces. Cada consulta lo acerca un poco más a ser un periodo de "
                f"diseño más: si el número es alto, lo que salga de ahí ya no es "
                f"una prueba independiente.",
                gravedad=(
                    "importante"
                    if consultas_validacion > cfg.reglas.validacion.consultas_para_alarma
                    else "aviso"
                ),
            )
        )

    return Informe(
        resumen=resumen,
        por_ano=metricas_mod.por_ano(resultado.curva, operaciones),
        por_mercado=metricas_mod.por_mercado(operaciones, cfg),
        por_bloque=metricas_mod.por_bloque(operaciones, cfg),
        uso_riesgo=metricas_mod.uso_del_riesgo(eventos),
        curva=resultado.curva,
        referencias=referencias,
        comparaciones=comparaciones,
        operaciones=operaciones,
        eventos=eventos,
        avisos=avisos,
        rechazos_top=_rechazos_top(eventos),
        sensibilidad=sensibilidad,
        meta={
            "origen": instantanea.origen,
            "fecha_descarga": str(instantanea.fecha_descarga or "desconocida"),
            "inicio": str(resultado.inicio),
            "fin": str(resultado.fin),
            "capital_inicial": resultado.capital_inicial,
            "divisa_base": cfg.reglas.cartera.divisa_base,
            "fundamental_activo": cfg.reglas.fundamental.activo,
        },
    )


def _avisos_de_datos(
    resultado: Resultado, cfg: Config, instantanea, operaciones, referencias
) -> list[Aviso]:
    avisos: list[Aviso] = []

    # Sesgo de supervivencia: con yfinance salta siempre, porque no da
    # deslistadas. Si algun dia se anaden, este aviso dejara de dispararse.
    avisos.append(
        Aviso(
            "supervivencia",
            "El universo está formado por empresas que cotizan hoy, así que las "
            "que quebraron o dejaron de cotizar no aparecen y el resultado está "
            "sesgado al alza. Afecta más a los mercados emergentes, donde las "
            "exclusiones y los deslistados son más frecuentes.",
            gravedad="importante",
        )
    )

    incompletos = getattr(instantanea, "incompletos", [])
    if incompletos:
        avisos.append(
            Aviso(
                "descarga_incompleta",
                f"La última descarga no pudo traer: {', '.join(incompletos)}. Lo "
                f"que haya de esos datos es de una descarga anterior, o no hay "
                f"nada. Vuelve a ejecutar `estrategia datos` antes de fiarte de "
                f"este informe.",
                gravedad="importante",
            )
        )

    # Fundamentales reconstruidos, no capturados en su momento.
    fund = instantanea.fundamentales
    if not fund.empty and "origen_pit" in fund.columns:
        pct = float((fund["origen_pit"] == "reconstruido").mean())
        if pct > 0:
            avisos.append(
                Aviso(
                    "fundamentales_reconstruidos",
                    f"El {pct:.0%} de los datos fundamentales es RECONSTRUIDO: no "
                    f"se capturó en su momento, se ha deducido después a partir de "
                    f"las cifras actuales. Esas cifras están reexpresadas, y las "
                    f"reexpresiones no son neutras. El comando `estrategia foto` "
                    f"existe para ir acumulando datos capturados de verdad.",
                    gravedad="importante",
                )
            )

    anos = cfg.reglas.proveedor_datos.fundamentales_anos_disponibles
    if cfg.reglas.fundamental.activo and anos <= 5:
        avisos.append(
            Aviso(
                "historico_fundamental_corto",
                f"El proveedor solo da unos {anos} ejercicios de fundamentales. "
                f"Con eso, el crecimiento de ventas a tres años tiene prácticamente "
                f"una sola observación por empresa y apenas varía durante el "
                f"backtest: el filtro fundamental es casi estatico. Para validar "
                f"el motor (calendarios, stops, costes, divisas) sobre un "
                f"histórico largo, pon `fundamental.activo: false` y usa solo la "
                f"pata técnica.",
                gravedad="importante",
            )
        )

    if resultado.sectores_sin_mapear:
        detalle = ", ".join(
            f"{s} ({len(t)} valores)" for s, t in resultado.sectores_sin_mapear.items()
        )
        avisos.append(
            Aviso(
                "sectores_sin_mapear",
                f"Sectores que el proveedor devuelve y el mapeo no conoce: "
                f"{detalle}. Esos valores se han quedado FUERA del universo. "
                f"Añádelos a `sectores` en config/implementacion.yaml.",
            )
        )

    if resultado.impuesto_extrapolado:
        avisos.append(
            Aviso(
                "impuesto_extrapolado",
                "Alguna operación ha usado una lista anual de impuesto de "
                "transacción de un año distinto al de la operación, porque no "
                "había lista de ese ejercicio. Revisa config/impuestos_transaccion.yaml.",
            )
        )

    faltan = set(cfg.reglas.referencias_informe) - set(referencias)
    if faltan:
        avisos.append(
            Aviso(
                "referencias_ausentes",
                f"No se ha podido construir la curva de estas referencias: "
                f"{sorted(faltan)}. La comparación con el mercado está incompleta.",
            )
        )

    if not resultado.curva.empty:
        exposicion = float(resultado.curva["exposicion"].mean())
        avisos.append(
            Aviso(
                "exposicion",
                f"La exposición media ha sido del {exposicion:.0%}: el resto del "
                f"tiempo el capital estuvo en liquidez. Las referencias están "
                f"invertidas al 100% siempre, así que comparar las curvas sin "
                f"tener esto delante no es una comparación justa.",
            )
        )

    return avisos


def _aviso_cohortes(eventos: pd.DataFrame, cfg: Config) -> list[Aviso]:
    """Cuantas compras se puntuaron fuera de su mercado.

    Cuando un mercado tiene menos de `fundamental.min_empresas_percentil`
    empresas, su puntuacion se percentila contra el bloque (desarrollado o
    emergente); si ni el bloque llega, la cohorte es insuficiente y la nota
    significa poco. Las dos cosas cambian como se compara una empresa con las
    de otros mercados, y quien lee el informe tiene que saber cuanto pesan.
    """
    if not cfg.reglas.fundamental.activo or eventos.empty or "cohorte" not in eventos:
        return []
    ordenes = eventos[eventos["tipo"] == "orden"]
    if ordenes.empty:
        return []
    fuera = ordenes[ordenes["cohorte"] != "mercado"]
    if fuera.empty:
        return []

    partes = []
    for (mercado, cohorte), grupo in fuera.groupby(["mercado", "cohorte"], sort=True):
        nombre = "contra el bloque" if cohorte == "bloque" else "con cohorte insuficiente"
        partes.append(f"{mercado}: {len(grupo)} {nombre}")
    insuficientes = int((fuera["cohorte"] == "insuficiente").sum())
    return [
        Aviso(
            "cohortes_fuera_de_mercado",
            f"{len(fuera)} de {len(ordenes)} compras se puntuaron fuera de su "
            f"mercado, porque su mercado tenia menos de "
            f"{cfg.reglas.fundamental.min_empresas_percentil} empresas con que "
            f"compararlas ({'; '.join(partes)}). Contra el bloque, la nota compara "
            f"con empresas de otros países de su mismo grupo (desarrollados o "
            f"emergentes). Con cohorte insuficiente, ni el bloque llegaba al "
            f"mínimo y el percentil significa poco.",
            gravedad="importante" if insuficientes else "aviso",
        )
    ]


def _aviso_periodo_muerto(
    resultado: Resultado, operaciones: pd.DataFrame, cfg: Config
) -> list[Aviso]:
    """Avisa del tramo inicial en que la estrategia no pudo operar.

    El crecimiento de ventas a tres anos necesita CUATRO ejercicios publicados,
    asi que con un proveedor que da cuatro, ninguna empresa pasa el filtro hasta
    que se publica el cuarto: del orden de tres anos y medio desde el inicio de
    los datos. Ese tramo no es "la estrategia prefirio liquidez", es "no habia
    con que decidir", y confundir las dos cosas hunde la rentabilidad
    anualizada sin que se vea por que.
    """
    if operaciones.empty or not cfg.reglas.fundamental.activo:
        return []

    primera = min(operaciones["fecha_entrada"])
    dias_muertos = (primera - resultado.inicio).days
    total = (resultado.fin - resultado.inicio).days
    if total <= 0 or dias_muertos <= 0:
        return []

    fraccion = dias_muertos / total
    if fraccion < cfg.reglas.metricas.fraccion_periodo_muerto_aviso:
        return []

    return [
        Aviso(
            "periodo_muerto_inicial",
            f"La primera operación no llega hasta {primera}: el "
            f"{fraccion:.0%} del periodo ({dias_muertos} días) transcurrió sin "
            f"que ninguna empresa pudiera pasar el filtro fundamental, porque el "
            f"crecimiento de ventas a tres años necesita CUATRO ejercicios "
            f"publicados y el cuarto tarda en llegar. Ese tramo entra en la "
            f"rentabilidad anualizada como si la estrategia hubiera elegido estar "
            f"en liquidez, y no es eso: es que no había datos con que decidir. "
            f"Para medir el motor sobre todo el histórico, usa "
            f"`fundamental.activo: false`.",
            gravedad="importante",
        )
    ]


def _avisos_de_suficiencia(operaciones: pd.DataFrame, cfg: Config) -> list[Aviso]:
    """Avisos de los minimos de `validacion` del documento."""
    val = cfg.reglas.validacion
    avisos: list[Aviso] = []
    n = len(operaciones)

    if n < val.min_operaciones:
        avisos.append(
            Aviso(
                "pocas_operaciones",
                f"Solo hay {n} operaciones y el mínimo para concluir algo es "
                f"{val.min_operaciones}. No hay base para afirmar nada sobre esta "
                f"estrategia con esta muestra.",
                gravedad="importante",
            )
        )

    if not operaciones.empty:
        cuenta = operaciones["mercado"].value_counts()
        flojos = {
            m: int(cuenta.get(m, 0))
            for m in cfg.reglas.mercados_por_id
            if int(cuenta.get(m, 0)) < val.min_operaciones_por_mercado
        }
        if flojos:
            detalle = ", ".join(f"{m}: {c}" for m, c in sorted(flojos.items()))
            avisos.append(
                Aviso(
                    "pocas_operaciones_por_mercado",
                    f"Mercados por debajo del mínimo de "
                    f"{val.min_operaciones_por_mercado} operaciones ({detalle}). "
                    f"El desglose por mercado de esos casos no dice nada.",
                    gravedad="importante",
                )
            )
    return avisos


def _rechazos_top(eventos: pd.DataFrame) -> pd.DataFrame:
    """Las candidatas mejor puntuadas que mas veces se quedaron fuera.

    Contesta a "por que no se compro la mejor de la semana" y deja ver si un
    limite de cartera esta costando dinero de forma sistematica.
    """
    if eventos.empty or "tipo" not in eventos.columns:
        return pd.DataFrame()
    rech = eventos[eventos["tipo"] == "rechazo"]
    if rech.empty or "rango" not in rech.columns:
        return pd.DataFrame()
    buenas = rech[rech["rango"] <= 3]
    if buenas.empty:
        return pd.DataFrame()
    return (
        buenas.groupby(["motivo", "mercado"])
        .size()
        .reset_index(name="veces")
        .sort_values("veces", ascending=False)
        .head(20)
        .reset_index(drop=True)
    )


def a_markdown(informe: Informe) -> str:
    """Version en texto del informe, para consola o fichero."""
    r = informe.resumen
    lineas: list[str] = []

    if informe.sintetico:
        lineas += [
            "# DATOS SINTÉTICOS - NO SON RESULTADOS REALES",
            "",
            "Este informe se ha generado con el proveedor de datos sintéticos.",
            "Sirve para comprobar que el motor funciona, no para decidir nada.",
            "",
        ]

    lineas += [
        "# Informe de la estrategia",
        "",
        f"Periodo: {informe.meta['inicio']} a {informe.meta['fin']} "
        f"({r.anos:.1f} años) | Origen de los datos: {informe.meta['origen']} "
        f"| Descarga: {informe.meta['fecha_descarga']}",
        f"Filtro fundamental: {'activo' if informe.meta['fundamental_activo'] else 'DESACTIVADO (solo pata tecnica)'}",
        "",
        "## Resumen",
        "",
        f"- Rentabilidad total: {r.rentabilidad_total:+.2%}",
        f"- Rentabilidad anualizada: {r.rentabilidad_anualizada:+.2%}",
        f"- Drawdown máximo: {r.drawdown_maximo:.2%}",
        f"- Ratio de Sharpe ({r.periodicidad_sharpe}): {r.sharpe:.2f}",
        f"- Ratio de Sortino ({r.periodicidad_sharpe}): {metricas_mod.como_texto(r.sortino)}",
        f"- Profit factor: {metricas_mod.como_texto(r.profit_factor)}",
        f"- Operaciones ganadoras: {r.pct_ganadoras:.1%}",
        f"- Número de operaciones: {r.n_operaciones}",
        f"- Días medios en cartera: {r.dias_medios_en_cartera:.0f}",
        f"- Rotación anual: {r.rotacion_anual:.2f}x",
        f"- Exposición media: {r.exposicion_media:.1%}",
        "",
    ]

    if informe.comparaciones:
        lineas += ["## Contra las referencias", ""]
        for c in informe.comparaciones:
            lineas += [
                f"### {c.nombre}",
                "",
                f"- Anualizada estrategia: {c.anualizada_estrategia:+.2%}",
                f"- Anualizada referencia: {c.anualizada_referencia:+.2%}",
                f"- Exceso anualizado: {c.exceso_anualizado:+.2%}",
                f"- Alfa de Jensen (anualizada): "
                f"{metricas_mod.como_texto(c.alfa_jensen * 100)}%",
                f"- Beta: {metricas_mod.como_texto(c.beta)}",
                f"- Correlacion: {metricas_mod.como_texto(c.correlacion)}",
                f"- Drawdown máximo estrategia: {c.drawdown_estrategia:.2%}",
                f"- Drawdown máximo referencia: {c.drawdown_referencia:.2%}",
            ]
            if c.recortada:
                lineas.append(
                    f"- **Comparacion desde {c.desde}**, no desde el inicio del "
                    f"backtest: la referencia no tiene datos antes de esa fecha."
                )
            lineas.append("")

    u = informe.uso_riesgo
    if u.n:
        lineas += [
            "## Riesgo nominal frente a riesgo real",
            "",
            f"- Riesgo teórico por operación: {u.riesgo_teorico_medio:.2%}",
            f"- Riesgo efectivo medio: {u.riesgo_efectivo_medio:.2%}",
            f"- Órdenes limitadas por `peso_maximo`: {u.pct_limitadas_por_peso:.0%}",
            "",
            "Si el porcentaje de órdenes limitadas es alto, quien manda en el",
            "tamaño es `cartera.peso_maximo` y no `riesgo.por_operacion`. En ese",
            "caso, que la sensibilidad de `riesgo.por_operacion` salga plana no",
            "significa que la estrategia sea robusta, sino que ese parámetro no",
            "estaba actuando.",
            "",
        ]

    for titulo, tabla in (
        ("Por año", informe.por_ano),
        ("Por mercado", informe.por_mercado),
        ("Por bloque", informe.por_bloque),
    ):
        if not tabla.empty:
            lineas += [f"## {titulo}", "", tabla.to_markdown(index=False), ""]

    if not informe.rechazos_top.empty:
        lineas += [
            "## Candidatas del top 3 que se quedaron fuera",
            "",
            informe.rechazos_top.to_markdown(index=False),
            "",
        ]

    if informe.sensibilidad is not None and not informe.sensibilidad.empty:
        lineas += [
            "## Sensibilidad",
            "",
            informe.sensibilidad.to_markdown(index=False),
            "",
        ]

    lineas += ["## Avisos", ""]
    for aviso in informe.avisos:
        marca = "PERMANENTE" if aviso.permanente else aviso.gravedad.upper()
        lineas.append(f"- **[{marca}]** {aviso.texto}")
    lineas.append("")

    return "\n".join(lineas)
