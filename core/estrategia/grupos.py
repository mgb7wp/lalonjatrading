"""Los cinco grupos fundamentales de §14, con sus metricas y su normalizacion.

## Que hace este modulo y que no

Convierte el historico de cuentas de una empresa en **cinco notas de 0 a 100**:
crecimiento, rentabilidad, salud financiera, calidad y valoracion. Esas cinco
componen el pilar fundamental del score.

No sustituye a `fundamental.py`. Aquel decide si una empresa **pasa el filtro**
del backtest —unos minimos y dos percentiles, en el camino critico del bucle
diario— y este describe **como de buena es en cada dimension**, para servirlo y
explicarlo. Mezclarlos habria hecho el filtro mas lento y este modulo mas atado.

## La regla que gobierna todo: una nota es un percentil

Un ROE del 18 % no significa nada por si solo: significa mucho comparado con la
banca y poco comparado con el software. Por eso ninguna metrica se puntua en
absoluto, sino como **percentil dentro de su cohorte** (mercado x sector), que es
lo que exige §14 al pedir que no se compare un banco con una tecnologica.

Cuando la cohorte es demasiado pequena el percentil no significa nada —con tres
empresas alguien saca un 0 y alguien un 100 por construccion— asi que se repliega
a una cohorte mas ancha y se deja constancia de cual se uso.

## Sobre el tamano

§14 pide normalizar tambien por tamano. La maquinaria lo admite —la cohorte es
una clave, no una pareja fija— pero **no se activa**, y es deliberado: con 61
valores, partir cada sector por tamano deja cohortes de dos o tres empresas. El
propio proyecto ya fija en 8 el minimo para que un percentil signifique algo.
Anadir la dimension ahora no daria una normalizacion mejor, daria una peor
disfrazada de mas fina.

## Huecos

Una metrica que no se puede calcular no puntua 50. Se descarta, y el grupo se
promedia sobre las que si tienen dato, dejando constancia de cuantas fueron. Es
la misma regla que la decision D-8 aplica a los pilares: imputar un valor medio
no es conservador, es inventar un dato que mueve el ranking.

Si de un grupo no se puede calcular ninguna metrica, el grupo queda a `None` y
el pilar se promedia sobre los grupos que si tienen nota.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .fundamental import percentiles_hazen
from .tipos import CohorteUsada

#: Ejercicios que se miran hacia atras para crecimiento y estabilidad.
ANIOS_HISTORIA = 5

#: Ejercicios que separan los dos extremos de un crecimiento a tres anos. Son
#: cuatro publicaciones para tres anos de variacion, que es la razon de que el
#: filtro fundamental no pueda operar hasta el cuarto ejercicio.
ANIOS_CRECIMIENTO = 3


@dataclass(frozen=True, slots=True)
class Metrica:
    """Una metrica del catalogo fundamental.

    `mejor` dice hacia donde puntua: un ROE alto es bueno y un PER alto es malo.
    Sin declararlo, la mitad de las metricas puntuarian del reves y el resultado
    seguiria pareciendo razonable, que es la peor forma de estar equivocado.
    """

    nombre: str
    grupo: str
    mejor: str  # "alto" | "bajo"
    descripcion: str


GRUPOS = ("crecimiento", "rentabilidad", "salud_financiera", "calidad", "valoracion")

METRICAS: tuple[Metrica, ...] = (
    # --- crecimiento ------------------------------------------------------
    Metrica("crecimiento_ventas", "crecimiento", "alto", "Crecimiento anual de ventas a 3 años"),
    Metrica("crecimiento_bpa", "crecimiento", "alto", "Crecimiento anual del BPA a 3 años"),
    Metrica("crecimiento_fcl", "crecimiento", "alto", "Crecimiento anual del flujo libre a 3 años"),
    # --- rentabilidad -----------------------------------------------------
    Metrica("roe", "rentabilidad", "alto", "Rentabilidad sobre fondos propios"),
    Metrica("roa", "rentabilidad", "alto", "Rentabilidad sobre activos"),
    Metrica("margen_bruto", "rentabilidad", "alto", "Margen bruto"),
    Metrica("margen_operativo", "rentabilidad", "alto", "Margen operativo"),
    Metrica("margen_neto", "rentabilidad", "alto", "Margen neto"),
    # --- salud financiera -------------------------------------------------
    Metrica("deuda_patrimonio", "salud_financiera", "bajo", "Deuda total sobre patrimonio"),
    Metrica("cobertura_intereses", "salud_financiera", "alto", "EBIT sobre gastos financieros"),
    Metrica("ratio_corriente", "salud_financiera", "alto", "Activo sobre pasivo corriente"),
    Metrica("fcl_deuda", "salud_financiera", "alto", "Flujo libre sobre deuda total"),
    # --- calidad ----------------------------------------------------------
    Metrica("variacion_beneficios", "calidad", "bajo", "Variabilidad del beneficio neto"),
    Metrica("anios_fcl_positivo", "calidad", "alto", "Proporción de años con flujo libre positivo"),
    Metrica("variacion_margen", "calidad", "bajo", "Variabilidad del margen operativo"),
    # --- valoracion -------------------------------------------------------
    Metrica("per", "valoracion", "bajo", "Precio sobre beneficio"),
    Metrica("precio_ventas", "valoracion", "bajo", "Precio sobre ventas"),
    Metrica("precio_valor_contable", "valoracion", "bajo", "Precio sobre valor contable"),
    Metrica("ev_ebitda", "valoracion", "bajo", "Valor de empresa sobre EBITDA"),
    Metrica("rentabilidad_fcl", "valoracion", "alto", "Flujo libre sobre capitalización"),
)

POR_GRUPO: dict[str, tuple[str, ...]] = {
    g: tuple(m.nombre for m in METRICAS if m.grupo == g) for g in GRUPOS
}
DIRECCION: dict[str, str] = {m.nombre: m.mejor for m in METRICAS}


# ---------------------------------------------------------------------------
# Metricas de una empresa
# ---------------------------------------------------------------------------


def _num(valor) -> float | None:
    """Convierte a float descartando nulos e infinitos.

    Los infinitos importan: aparecen al dividir por un denominador que es cero y
    envenenan cualquier media o percentil posterior sin que nada avise.
    """
    if valor is None:
        return None
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _cagr(serie: list[float | None], anios: int) -> float | None:
    """Crecimiento anual compuesto entre el primer y el ultimo ejercicio.

    Con base negativa o nula no hay porcentaje que calcular: pasar de perder 10
    a perder 5 no es "crecer un 50 %". Devuelve None en lugar de un numero que
    parece razonable y no lo es.
    """
    validos = [v for v in serie if v is not None]
    if len(validos) < anios + 1:
        return None
    inicio, fin = validos[-(anios + 1)], validos[-1]
    if inicio is None or inicio <= 0 or fin is None:
        return None
    if fin <= 0:
        return -1.0  # de beneficio a perdidas: el peor crecimiento posible
    return (fin / inicio) ** (1.0 / anios) - 1.0


def _variabilidad(serie: list[float | None]) -> float | None:
    """Desviacion tipica relativa a la media, en valor absoluto.

    Relativa porque una empresa que gana 1.000 y otra que gana 10 no se pueden
    comparar en unidades. En valor absoluto en el denominador para que una
    empresa con beneficio medio negativo no salga con variabilidad negativa,
    que la pondria como la mas estable del mercado.
    """
    validos = [v for v in serie if v is not None]
    if len(validos) < 3:
        return None
    media = float(np.mean(validos))
    if media == 0:
        return None
    return float(np.std(validos)) / abs(media)


def magnitudes_de(
    historico: pd.DataFrame, capitalizacion: float | None = None, ev: float | None = None
) -> dict[str, float | None]:
    """Las veinte metricas de una empresa, a partir de su historico anual.

    `historico` viene ya recortado a lo que se sabia en la fecha de decision: la
    vista puntual se encarga de eso antes, y este modulo no vuelve a filtrar
    porque no sabria por que fecha hacerlo.
    """
    anuales = historico[historico["periodo"] == "anual"].sort_values("fin_periodo")
    if anuales.empty:
        return dict.fromkeys(DIRECCION)

    reciente = anuales.iloc[-1]
    ventana = anuales.tail(ANIOS_HISTORIA)

    def serie(columna: str) -> list[float | None]:
        return [_num(v) for v in ventana.get(columna, [])]

    def ultimo(columna: str) -> float | None:
        return _num(reciente.get(columna))

    ventas = ultimo("ventas")
    ebit = ultimo("ebit")
    ebitda = ultimo("ebitda")
    beneficio = ultimo("beneficio_neto")
    patrimonio = ultimo("patrimonio_neto")
    activos = ultimo("activos_totales")
    deuda = ultimo("deuda_total")
    fcl = ultimo("flujo_caja_libre")
    gastos = ultimo("gastos_financieros")

    def ratio(numerador, denominador, exigir_positivo=True):
        """Division que se niega cuando el denominador no tiene sentido.

        Las trampas de signo son las mismas que ya corta `fundamental.py`: un
        patrimonio negativo convierte un ROE de perdidas en positivo, y un EBIT
        negativo haria "baratisima" a la empresa. Ante la duda, sin dato.
        """
        if numerador is None or denominador is None:
            return None
        if denominador == 0 or (exigir_positivo and denominador <= 0):
            return None
        return numerador / denominador

    fcl_positivos = [v for v in serie("flujo_caja_libre") if v is not None]

    return {
        # crecimiento
        "crecimiento_ventas": _cagr(serie("ventas"), ANIOS_CRECIMIENTO),
        "crecimiento_bpa": _cagr(serie("bpa"), ANIOS_CRECIMIENTO),
        "crecimiento_fcl": _cagr(serie("flujo_caja_libre"), ANIOS_CRECIMIENTO),
        # rentabilidad
        "roe": ratio(beneficio, patrimonio),
        "roa": ratio(beneficio, activos),
        "margen_bruto": ratio(ultimo("beneficio_bruto"), ventas),
        "margen_operativo": ratio(ebit, ventas),
        "margen_neto": ratio(beneficio, ventas),
        # salud financiera
        "deuda_patrimonio": ratio(deuda, patrimonio),
        "cobertura_intereses": ratio(ebit, gastos),
        "ratio_corriente": ratio(ultimo("activo_corriente"), ultimo("pasivo_corriente")),
        "fcl_deuda": ratio(fcl, deuda),
        # calidad
        "variacion_beneficios": _variabilidad(serie("beneficio_neto")),
        "anios_fcl_positivo": (
            sum(1 for v in fcl_positivos if v > 0) / len(fcl_positivos)
            if len(fcl_positivos) >= 3
            else None
        ),
        "variacion_margen": _variabilidad(serie("margen_operativo")),
        # valoracion
        "per": ratio(capitalizacion, beneficio),
        "precio_ventas": ratio(capitalizacion, ventas),
        "precio_valor_contable": ratio(capitalizacion, patrimonio),
        "ev_ebitda": ratio(ev, ebitda),
        "rentabilidad_fcl": ratio(fcl, capitalizacion),
    }


# ---------------------------------------------------------------------------
# Puntuacion por cohorte
# ---------------------------------------------------------------------------


@dataclass
class NotaFundamental:
    """Las cinco notas de una empresa, con de donde salen."""

    ticker: str
    grupos: dict[str, float | None] = field(default_factory=dict)
    fundamental: float | None = None
    cohorte_usada: CohorteUsada = CohorteUsada.INSUFICIENTE
    n_cohorte: int = 0
    metricas_usadas: dict[str, int] = field(default_factory=dict)


def _percentilar(valores: pd.Series, mejor: str) -> pd.Series:
    """Percentil de Hazen, invertido cuando lo bueno es tener poco."""
    pct = percentiles_hazen(valores)
    return 100.0 - pct if mejor == "bajo" else pct


def puntuar(
    magnitudes: dict[str, dict[str, float | None]],
    cohortes: dict[str, str],
    min_cohorte: int = 8,
    pesos: dict[str, float] | None = None,
) -> dict[str, NotaFundamental]:
    """Convierte las metricas en bruto de varias empresas en notas comparables.

    `cohortes` asigna a cada ticker su grupo de comparacion. Las cohortes que no
    llegan a `min_cohorte` se juntan en una sola, y las empresas afectadas lo
    llevan marcado: un percentil sobre tres empresas no significa lo mismo que
    sobre cuarenta, y quien lea el score tiene derecho a saberlo.
    """
    if not magnitudes:
        return {}

    tickers = list(magnitudes)
    marco = pd.DataFrame(
        [{"ticker": t, "cohorte": cohortes.get(t, ""), **magnitudes[t]} for t in tickers]
    )

    tamanos = marco["cohorte"].value_counts()
    pequenas = set(tamanos[tamanos < min_cohorte].index)
    # Las cohortes pequenas se refunden en una. No es lo ideal —mezcla sectores—
    # pero es mejor que un percentil calculado sobre tres empresas, que reparte
    # un 0 y un 100 por pura aritmetica.
    marco["cohorte_efectiva"] = marco["cohorte"].where(
        ~marco["cohorte"].isin(pequenas), "__refundida__"
    )

    for metrica in DIRECCION:
        marco[f"p_{metrica}"] = (
            marco.groupby("cohorte_efectiva")[metrica]
            .transform(lambda s, m=DIRECCION[metrica]: _percentilar(s, m))
        )

    pesos = pesos or dict.fromkeys(GRUPOS, 1.0)
    salida: dict[str, NotaFundamental] = {}
    for _, fila in marco.iterrows():
        nota = NotaFundamental(ticker=fila["ticker"])
        nota.n_cohorte = int((marco["cohorte_efectiva"] == fila["cohorte_efectiva"]).sum())
        nota.cohorte_usada = (
            CohorteUsada.BLOQUE
            if fila["cohorte_efectiva"] == "__refundida__"
            else CohorteUsada.MERCADO
        )

        for grupo, metricas in POR_GRUPO.items():
            valores = [
                fila[f"p_{m}"] for m in metricas if not pd.isna(fila.get(f"p_{m}", np.nan))
            ]
            nota.metricas_usadas[grupo] = len(valores)
            # Una metrica sin dato no puntua 50: se descarta y el grupo se
            # promedia sobre las que si lo tienen (decision D-8).
            nota.grupos[grupo] = float(np.mean(valores)) if valores else None

        con_nota = {g: v for g, v in nota.grupos.items() if v is not None}
        if con_nota:
            # Los pesos se renormalizan sobre los grupos con nota, por lo mismo.
            total = sum(pesos.get(g, 1.0) for g in con_nota)
            nota.fundamental = sum(v * pesos.get(g, 1.0) for g, v in con_nota.items()) / total
        salida[fila["ticker"]] = nota

    return salida
