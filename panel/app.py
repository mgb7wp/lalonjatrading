"""Panel de la estrategia.

Solo lee y pinta: ninguna regla de estrategia vive aqui. Si el panel y el CLI
dieran resultados distintos seria porque hay logica duplicada, asi que ambos
llaman al mismo motor.

Streamlit reejecuta el script entero con cada clic, asi que el backtest va
cacheado sobre la configuracion y el proveedor. La configuracion es inmutable
(pydantic `frozen=True`), que es lo que permite usarla como parte de la clave
sin sustos.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

from estrategia import backtest as backtest_mod  # noqa: E402
from estrategia import config as config_mod  # noqa: E402
from estrategia import informe as informe_mod  # noqa: E402
from estrategia import universo as universo_mod  # noqa: E402
from estrategia import validacion as validacion_mod  # noqa: E402
from estrategia.datos.almacen import Instantanea  # noqa: E402
from estrategia.sectores import MapaSectores  # noqa: E402

DIR_CACHE = RAIZ / "datos" / "cache"
RUTA_CONSULTAS = RAIZ / "datos" / "consultas_validacion.json"

st.set_page_config(page_title="Estrategia mixta", page_icon="📈", layout="wide")


@st.cache_resource(show_spinner="Cargando datos...")
def cargar(proveedor: str):
    cfg = config_mod.cargar()
    inst = Instantanea.cargar(DIR_CACHE / proveedor)
    inst.preparar(cfg)
    return cfg, inst


@st.cache_data(show_spinner="Corriendo el backtest...")
def correr(proveedor: str, periodo: str, _cfg, _inst):
    division = validacion_mod.dividir(_inst, _cfg)
    if periodo == "diseno":
        inicio, fin = division.diseno
    elif periodo == "validacion":
        inicio, fin = division.validacion
    else:
        inicio, fin = division.inicio, division.fin
    r = backtest_mod.ejecutar(_inst, _cfg, inicio, fin)
    consultas = validacion_mod.RegistroConsultas(RUTA_CONSULTAS).n
    return informe_mod.construir(r, _cfg, _inst, consultas_validacion=consultas)


def barra_sintetico(inf) -> None:
    if inf.sintetico:
        st.error(
            "**DATOS SINTETICOS — NO SON RESULTADOS REALES.** Estas cifras salen "
            "de un generador determinista que sirve para comprobar que el motor "
            "funciona. No describen ningun mercado y no valen para decidir nada.",
            icon="⚠️",
        )


def pintar_avisos(inf) -> None:
    permanentes = [a for a in inf.avisos if a.permanente]
    importantes = [a for a in inf.avisos if not a.permanente and a.gravedad == "importante"]
    normales = [a for a in inf.avisos if not a.permanente and a.gravedad != "importante"]

    for a in permanentes:
        st.warning(f"**Aviso permanente.** {a.texto}")
    for a in importantes:
        st.warning(a.texto)
    if normales:
        with st.expander(f"Otros avisos ({len(normales)})"):
            for a in normales:
                st.info(a.texto)


# --------------------------------------------------------------------------
# Barra lateral
# --------------------------------------------------------------------------

st.sidebar.title("Estrategia mixta")
proveedores = [d.name for d in DIR_CACHE.iterdir() if d.is_dir()] if DIR_CACHE.is_dir() else []
if not proveedores:
    st.error(
        "No hay datos disponibles todavia.\n\n"
        "Si estas en local: `estrategia --proveedor sintetico datos`"
    )
    st.stop()

proveedor = st.sidebar.selectbox("Proveedor de datos", proveedores)
cfg, inst = cargar(proveedor)
division = validacion_mod.dividir(inst, cfg)

MODO_PUBLICO = cfg.reglas.panel.modo_publico

st.sidebar.caption(
    f"Descarga: {inst.fecha_descarga or 'desconocida'}  \n"
    f"Origen: {inst.origen}  \n"
    f"Rango: {division.inicio} a {division.fin}  \n"
    f"Corte diseno/validacion: {division.corte}"
)

vista = st.sidebar.radio(
    "Vista", ["Universo", "Senales", "Backtest", "Validacion"], index=2
)

# --------------------------------------------------------------------------
# Universo
# --------------------------------------------------------------------------

if vista == "Universo":
    st.title("Universo")
    st.caption(
        "Quien puede entrar y por que no. La elegibilidad se evalua a fecha: un "
        "valor liquido hoy pudo no serlo hace cinco anos."
    )
    fecha = st.date_input(
        "Fecha", value=division.fin, min_value=division.inicio, max_value=division.fin
    )
    v = inst.vista(fecha if isinstance(fecha, date) else division.fin)
    mapa = MapaSectores(cfg)
    resultado = universo_mod.evaluar(v.fecha_corte, v, cfg, mapa)

    df = pd.DataFrame(
        [
            {
                "ticker": e.ticker, "mercado": e.mercado, "sector": e.sector,
                "elegible": e.elegible, "volumen_medio_eur": e.volumen_medio_base,
                "motivo": str(e.motivo) if e.motivo else "",
            }
            for e in resultado.values()
        ]
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Valores en el universo", len(df))
    c2.metric("Elegibles", int(df["elegible"].sum()))
    c3.metric("Descartados", int((~df["elegible"]).sum()))

    st.subheader("Por mercado")
    st.dataframe(
        df.groupby("mercado").agg(
            valores=("ticker", "count"), elegibles=("elegible", "sum")
        ),
        use_container_width=True,
    )
    st.subheader("Motivos de descarte")
    descartes = df[~df["elegible"]]["motivo"].value_counts()
    if not descartes.empty:
        st.bar_chart(descartes)
    st.subheader("Detalle")
    st.dataframe(df.sort_values(["mercado", "ticker"]), use_container_width=True)

    if mapa.sin_mapear:
        st.warning(
            f"Sectores que el proveedor devuelve y el mapeo no conoce: "
            f"{mapa.sin_mapear}. Esos valores se quedan fuera."
        )

# --------------------------------------------------------------------------
# Senales
# --------------------------------------------------------------------------

elif vista == "Senales":
    st.title("Senales de la ultima revision")
    st.caption(
        "Salen del mismo motor que las produce en el backtest, no de un camino "
        "paralelo: si divergieran, el panel estaria mintiendo."
    )
    inf = correr(proveedor, "todo", cfg, inst)
    barra_sintetico(inf)

    ev = inf.eventos
    if ev.empty:
        st.info("No hay eventos.")
    else:
        ordenes = ev[ev["tipo"] == "orden"]
        if ordenes.empty:
            st.info("No se genero ninguna orden en el periodo.")
        else:
            ultima = ordenes["fecha"].max()
            st.subheader(f"Ordenes del {ultima}")
            st.dataframe(ordenes[ordenes["fecha"] == ultima], use_container_width=True)

            st.subheader("Historial de ordenes")
            st.dataframe(ordenes.tail(200), use_container_width=True)

        st.subheader("Candidatas del top 3 que se quedaron fuera")
        st.caption(
            "Contesta a «por que no se compro la mejor de la semana» y deja ver "
            "si un limite de cartera esta costando dinero de forma sistematica."
        )
        if inf.rechazos_top.empty:
            st.info("Ninguna candidata del top 3 fue rechazada.")
        else:
            st.dataframe(inf.rechazos_top, use_container_width=True)

# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------

elif vista == "Backtest":
    st.title("Backtest")
    periodo = st.radio(
        "Periodo", ["diseno", "todo", "validacion"], horizontal=True,
        help="El periodo de validacion deja de ser una prueba independiente si "
             "se consulta muchas veces.",
    )
    if periodo == "validacion":
        n = validacion_mod.RegistroConsultas(RUTA_CONSULTAS).n
        st.warning(
            f"Estas mirando el periodo reservado. Van {n} consultas anotadas. "
            f"Cada una lo acerca un poco mas a ser un segundo periodo de diseno."
        )

    inf = correr(proveedor, periodo, cfg, inst)
    barra_sintetico(inf)
    r = inf.resumen

    c = st.columns(4)
    c[0].metric("Anualizada", f"{r.rentabilidad_anualizada:+.2%}")
    c[1].metric("Drawdown maximo", f"{r.drawdown_maximo:.2%}")
    c[2].metric(f"Sharpe ({r.periodicidad_sharpe})", f"{r.sharpe:.2f}")
    c[3].metric("Ganadoras", f"{r.pct_ganadoras:.1%}")
    c = st.columns(3)
    c[0].metric("Operaciones", r.n_operaciones)
    c[1].metric("Exposicion media", f"{r.exposicion_media:.1%}")
    c[2].metric("Anos", f"{r.anos:.1f}")

    st.subheader("Curva de capital")
    st.caption(
        "Las referencias estan invertidas al 100% todo el tiempo y la estrategia "
        f"no: su exposicion media fue del {r.exposicion_media:.0%}."
    )
    curva = inf.curva.set_index("fecha")[["valor"]].rename(columns={"valor": "estrategia"})
    for nombre, serie in inf.referencias.items():
        curva[nombre] = serie
    st.line_chart(curva)

    st.subheader("Riesgo nominal frente a riesgo real")
    u = inf.uso_riesgo
    if u.n:
        c = st.columns(3)
        c[0].metric("Riesgo teorico", f"{u.riesgo_teorico_medio:.2%}")
        c[1].metric("Riesgo efectivo medio", f"{u.riesgo_efectivo_medio:.2%}")
        c[2].metric("Limitadas por peso_maximo", f"{u.pct_limitadas_por_peso:.0%}")
        if u.pct_limitadas_por_peso > 0.5:
            st.info(
                "En la mayoria de las ordenes manda `cartera.peso_maximo`, no "
                "`riesgo.por_operacion`. Si la sensibilidad de ese segundo "
                "parametro sale plana, no es que la estrategia sea robusta: es "
                "que el parametro no estaba actuando."
            )

    for titulo, tabla in (
        ("Por ano", inf.por_ano),
        ("Por mercado", inf.por_mercado),
        ("Por bloque desarrollado/emergente", inf.por_bloque),
    ):
        if not tabla.empty:
            st.subheader(titulo)
            st.dataframe(tabla, use_container_width=True)

    if not inf.operaciones.empty:
        st.subheader("Operaciones")
        st.dataframe(inf.operaciones, use_container_width=True)

    st.subheader("Avisos")
    pintar_avisos(inf)

# --------------------------------------------------------------------------
# Validacion
# --------------------------------------------------------------------------

else:
    st.title("Validacion")
    st.caption(
        "La sensibilidad mueve cada parametro arriba y abajo sobre el periodo de "
        "diseno. Correrla sobre el de validacion seria gastar la unica prueba "
        "independiente que hay."
    )
    inf = correr(proveedor, "diseno", cfg, inst)
    barra_sintetico(inf)

    registro = validacion_mod.RegistroConsultas(RUTA_CONSULTAS)
    st.metric("Consultas anotadas al periodo de validacion", registro.n)
    if registro.n:
        with st.expander("Historial de consultas"):
            st.dataframe(pd.DataFrame(registro.leer()), use_container_width=True)

    pct = cfg.reglas.validacion.sensibilidad_pct
    st.subheader(f"Sensibilidad (±{pct:.0%})")

    if MODO_PUBLICO:
        # El analisis corre unos treinta backtests. Dejar ese boton abierto a
        # internet en la maquina de uno es regalar un boton de "ocupame la CPU".
        st.info(
            "El analisis de sensibilidad esta desactivado en modo publico: son "
            "unos treinta backtests y este panel es accesible desde internet. "
            "Ejecutalo en local con `estrategia validar`, que ademas guarda el "
            "resultado en `datos/resultados/`."
        )
        ruta_sens = RAIZ / "datos" / "resultados" / f"sensibilidad_{proveedor}.parquet"
        if ruta_sens.is_file():
            st.caption("Ultimo analisis guardado:")
            st.dataframe(pd.read_parquet(ruta_sens), use_container_width=True)
    elif st.button("Ejecutar analisis de sensibilidad (tarda varios minutos)"):
        division_d = validacion_mod.dividir(inst, cfg)
        with st.spinner("Corriendo una variante por parametro y sentido..."):
            sens = validacion_mod.sensibilidad(
                inst, cfg, *division_d.diseno, inf.resumen
            )
        st.dataframe(sens, use_container_width=True)
        inactivos = (
            sorted(sens[sens["actividad"] == "inactivo"]["parametro"].unique())
            if "actividad" in sens.columns
            else []
        )
        if inactivos:
            st.info(
                "Parametros que no movieron el resultado: "
                f"{', '.join(inactivos)}. Que salgan planos NO significa que la "
                "estrategia sea robusta frente a ellos, sino que no estaban "
                "actuando en este periodo."
            )

    st.subheader("Suficiencia de la muestra")
    val = cfg.reglas.validacion
    st.write(
        f"Minimos del documento: {val.min_operaciones} operaciones en total y "
        f"{val.min_operaciones_por_mercado} por mercado."
    )
    if not inf.por_mercado.empty:
        tabla = inf.por_mercado[["mercado", "n_operaciones"]].copy()
        tabla["suficiente"] = tabla["n_operaciones"] >= val.min_operaciones_por_mercado
        st.dataframe(tabla, use_container_width=True)

    st.subheader("Avisos")
    pintar_avisos(inf)
