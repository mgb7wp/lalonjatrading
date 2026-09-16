"""Motor de scoring: de los factores a los pilares y al score global.

## La estructura, y por que no es la del encargo

§18 propone pesos que suman 100: fundamental 25, technical 20, momentum 15,
quality 15, valuation 10, sentiment 10, risk 5. La suma cuadra pero la
descomposicion no: **momentum es parte de technical, y calidad y valoracion son
parte de fundamental**. Sumarlos como independientes cuenta el momentum dos
veces —dentro de su pilar y otra vez por su cuenta— y la calidad igual. Un valor
con momentum fuerte se llevaria el 35 % del score por el mismo hecho medido dos
veces.

De ahi la decision D-3, que separa dos niveles:

- **Pilares** (ortogonales, agregan al score): fundamental, tecnico, sentimiento
  y riesgo.
- **Sub-scores** (descomponen un pilar, se publican, **no** suman aparte):
  crecimiento, rentabilidad, salud financiera, calidad y valoracion dentro del
  fundamental; momentum, tendencia, volatilidad y volumen dentro del tecnico.

La API devuelve los dos niveles porque la explicabilidad de §28 los necesita,
pero el total solo agrega pilares.

## Riesgo: 100 es MENOS riesgo

Lo dice §17 y conviene repetirlo aqui porque es la fuente de error mas facil de
cometer en todo el modulo: en el pilar de riesgo, una nota alta significa una
empresa **mas segura**, no mas arriesgada. Cada factor declara su direccion para
que la inversion ocurra en un solo sitio.

## Un pilar sin datos no puntua 50

Cuando falta un pilar —hoy el de sentimiento siempre— **los pesos se renormalizan
sobre los que si estan** y el score declara cuales fueron. Imputar un 50 neutro
no es conservador: es inventar un dato que mueve el ranking. Decision D-8.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .fundamental import percentiles_hazen
from .tipos import CohorteUsada

#: Los cuatro pilares ortogonales. El orden es el de presentacion.
PILARES = ("fundamental", "tecnico", "sentimiento", "riesgo")


@dataclass(frozen=True, slots=True)
class Factor:
    """Una medida que alimenta un sub-score.

    `mejor` dice hacia donde puntua. Sin declararlo, la mitad de los factores de
    riesgo puntuarian del reves —una volatilidad alta saldria como seguridad— y
    el resultado seguiria pareciendo razonable, que es la peor forma de estar
    equivocado.
    """

    nombre: str
    pilar: str
    subscore: str
    mejor: str  # "alto" | "bajo"
    descripcion: str


#: Factores tecnicos. Salen del catalogo de indicadores, que ya los calcula.
FACTORES_TECNICOS: tuple[Factor, ...] = (
    Factor("momentum_12_1", "tecnico", "momentum", "alto", "Momentum 12-1"),
    Factor("roc_20", "tecnico", "momentum", "alto", "Variación a 20 sesiones"),
    Factor("aceleracion_precio", "tecnico", "momentum", "alto", "Aceleración del precio"),
    Factor("fuerza_relativa_126", "tecnico", "momentum", "alto", "Fuerza relativa vs índice"),
    Factor("distancia_sma_200", "tecnico", "tendencia", "alto", "Precio sobre su media de 200"),
    Factor("pendiente_medias", "tecnico", "tendencia", "alto", "Media de 50 sobre la de 200"),
    Factor("adx_14", "tecnico", "tendencia", "alto", "Fuerza de la tendencia"),
    Factor("macd_histograma", "tecnico", "tendencia", "alto", "MACD sobre su señal"),
    Factor("volatilidad_60", "tecnico", "volatilidad", "bajo", "Volatilidad anualizada"),
    Factor("atr_relativo", "tecnico", "volatilidad", "bajo", "ATR sobre el precio"),
    Factor("ratio_volumen_20", "tecnico", "volumen", "alto", "Volumen frente a su media"),
    Factor("liquidez", "tecnico", "volumen", "alto", "Volumen negociado medio"),
)

#: Factores de riesgo. Mezclan tecnico y fundamental a proposito: §17 pide
#: volatilidad y drawdown, pero tambien deuda y volatilidad de beneficios.
FACTORES_RIESGO: tuple[Factor, ...] = (
    Factor("volatilidad_60", "riesgo", "riesgo", "bajo", "Volatilidad anualizada"),
    Factor("drawdown_maximo_1a", "riesgo", "riesgo", "alto", "Peor caída del año"),
    Factor("beta_252", "riesgo", "riesgo", "bajo", "Sensibilidad al mercado"),
    Factor("liquidez", "riesgo", "riesgo", "alto", "Volumen negociado medio"),
    Factor("deuda_patrimonio", "riesgo", "riesgo", "bajo", "Apalancamiento"),
    Factor("variacion_beneficios", "riesgo", "riesgo", "bajo", "Variabilidad del beneficio"),
)

TODOS: tuple[Factor, ...] = FACTORES_TECNICOS + FACTORES_RIESGO
DIRECCION: dict[str, str] = {f.nombre: f.mejor for f in TODOS}

SUBSCORES_TECNICOS = ("momentum", "tendencia", "volatilidad", "volumen")


@dataclass
class Puntuacion:
    """El score de un valor, con todo lo necesario para explicarlo."""

    ticker: str
    overall: float | None = None
    pilares: dict[str, float | None] = field(default_factory=dict)
    subscores: dict[str, float | None] = field(default_factory=dict)
    cohorte_usada: CohorteUsada = CohorteUsada.INSUFICIENTE
    n_cohorte: int = 0
    pilares_disponibles: list[str] = field(default_factory=list)
    pilares_no_disponibles: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Factores derivados de los indicadores
# ---------------------------------------------------------------------------


def factores_tecnicos(indicadores: dict[str, float | None], cierre: float | None) -> dict:
    """Convierte la lectura de indicadores de un dia en factores comparables.

    Algunos indicadores no son comparables entre valores tal cual: una media de
    200 sesiones vale 40 en un valor y 400 en otro, asi que lo que puntua es la
    **distancia relativa** del precio a esa media, no la media. Lo mismo con el
    ATR, que en unidades monetarias no dice nada sin el precio al lado.
    """

    def de(nombre: str) -> float | None:
        v = indicadores.get(nombre)
        if v is None:
            return None
        f = float(v)
        return None if np.isnan(f) or np.isinf(f) else f

    sma_50, sma_200 = de("sma_50"), de("sma_200")
    macd, senal = de("macd"), de("macd_signal")
    atr = de("atr_14")
    volumen = de("ratio_volumen_20")

    return {
        "momentum_12_1": de("momentum_12_1"),
        "roc_20": de("roc_20"),
        "aceleracion_precio": de("aceleracion_precio"),
        "fuerza_relativa_126": de("fuerza_relativa_126"),
        "distancia_sma_200": (
            cierre / sma_200 - 1.0 if cierre and sma_200 and sma_200 > 0 else None
        ),
        "pendiente_medias": (
            sma_50 / sma_200 - 1.0 if sma_50 and sma_200 and sma_200 > 0 else None
        ),
        "adx_14": de("adx_14"),
        "macd_histograma": (
            # Normalizado por el precio: un MACD de 2 es enorme en un valor de
            # 10 e irrelevante en uno de 400.
            (macd - senal) / cierre if macd is not None and senal is not None and cierre else None
        ),
        "volatilidad_60": de("volatilidad_60"),
        "atr_relativo": atr / cierre if atr and cierre else None,
        "ratio_volumen_20": volumen,
    }


# ---------------------------------------------------------------------------
# Agregacion
# ---------------------------------------------------------------------------


def _percentilar(valores: pd.Series, mejor: str) -> pd.Series:
    pct = percentiles_hazen(valores)
    return 100.0 - pct if mejor == "bajo" else pct


def _media(valores: list[float]) -> float | None:
    return float(np.mean(valores)) if valores else None


def puntuar(
    factores: dict[str, dict[str, float | None]],
    cohortes: dict[str, str],
    notas_fundamentales: dict | None = None,
    pesos: dict[str, float] | None = None,
    min_cohorte: int = 8,
) -> dict[str, Puntuacion]:
    """Convierte factores en bruto en pilares y en un score global.

    `notas_fundamentales` son las que produce `grupos.puntuar`: el pilar
    fundamental ya viene calculado de alli, con sus cinco sub-scores. Aqui se
    calculan el tecnico y el de riesgo, y se agregan los cuatro.
    """
    if not factores:
        return {}

    marco = pd.DataFrame(
        [{"ticker": t, "cohorte": cohortes.get(t, ""), **v} for t, v in factores.items()]
    )
    tamanos = marco["cohorte"].value_counts()
    pequenas = set(tamanos[tamanos < min_cohorte].index)
    marco["cohorte_efectiva"] = marco["cohorte"].where(
        ~marco["cohorte"].isin(pequenas), "__refundida__"
    )

    for nombre, mejor in DIRECCION.items():
        if nombre not in marco.columns:
            marco[nombre] = np.nan
        marco[f"p_{nombre}"] = marco.groupby("cohorte_efectiva")[nombre].transform(
            lambda s, m=mejor: _percentilar(s, m)
        )

    pesos = pesos or dict.fromkeys(PILARES, 1.0)
    notas_fundamentales = notas_fundamentales or {}
    salida: dict[str, Puntuacion] = {}

    for _, fila in marco.iterrows():
        p = Puntuacion(ticker=fila["ticker"])
        p.n_cohorte = int((marco["cohorte_efectiva"] == fila["cohorte_efectiva"]).sum())
        p.cohorte_usada = (
            CohorteUsada.BLOQUE
            if fila["cohorte_efectiva"] == "__refundida__"
            else CohorteUsada.MERCADO
        )

        def pct(nombre, _f=fila):
            v = _f.get(f"p_{nombre}")
            return None if v is None or pd.isna(v) else float(v)

        # --- pilar tecnico, por sub-scores --------------------------------
        for sub in SUBSCORES_TECNICOS:
            miembros = [f.nombre for f in FACTORES_TECNICOS if f.subscore == sub]
            p.subscores[sub] = _media([v for v in (pct(m) for m in miembros) if v is not None])
        tecnicos = [v for k, v in p.subscores.items() if k in SUBSCORES_TECNICOS and v is not None]
        p.pilares["tecnico"] = _media(tecnicos)

        # --- pilar de riesgo ----------------------------------------------
        # Una sola nota, sin sub-scores: §17 lo pide como puntuacion
        # independiente y partirlo no anadiria nada que se pueda explicar.
        riesgo = [v for v in (pct(f.nombre) for f in FACTORES_RIESGO) if v is not None]
        p.pilares["riesgo"] = _media(riesgo)

        # --- pilar fundamental, de grupos.puntuar -------------------------
        nota = notas_fundamentales.get(fila["ticker"])
        p.pilares["fundamental"] = nota.fundamental if nota else None
        if nota:
            p.subscores.update(nota.grupos)

        # --- sentimiento ---------------------------------------------------
        # Siempre ausente hoy: no hay fuente gratuita, legal y con cobertura de
        # los mercados del universo. §16 lo anticipa y manda no inventar datos.
        p.pilares["sentimiento"] = None

        disponibles = {k: v for k, v in p.pilares.items() if v is not None}
        p.pilares_disponibles = sorted(disponibles)
        p.pilares_no_disponibles = {
            "sentimiento": "sin fuente de datos de sentimiento",
            **{
                k: "sin datos suficientes"
                for k in p.pilares
                if p.pilares[k] is None and k != "sentimiento"
            },
        }
        if disponibles:
            # Los pesos se renormalizan sobre los pilares con nota (D-8).
            total = sum(pesos.get(k, 0.0) for k in disponibles)
            if total > 0:
                p.overall = sum(v * pesos.get(k, 0.0) for k, v in disponibles.items()) / total
        salida[fila["ticker"]] = p

    return salida
