"""Motor de senales (§25) y regimen de mercado (§26).

Una senal **no** sale solo del score, y el encargo lo pide explicitamente.
Entran el score, su variacion, la probabilidad del modelo, el momentum, el
riesgo, la valoracion y el regimen del mercado. Un score alto en un valor que se
desploma, en un mercado en caida y con la volatilidad disparada no es una
compra; es un score alto.

## Por que hay un vocabulario cerrado de motivos

`Motivo` es una enumeracion y no texto libre porque el informe se construye
CONTANDO. La pregunta que hay que poder responder es "por que no hubo ni una
compra esta semana", y con frases distintas cada vez no se puede agrupar. Con
esto, se cuenta: 40 limitadas por regimen, 12 por riesgo, 3 por momentum.

## Como se decide, y por que asi

Primero el score fija una senal **base**. Despues se aplican limitadores, cada
uno capaz de rebajarla pero **nunca de subirla**. La senal final se queda con el
motivo del limitador que de verdad mordio.

Ese diseno es deliberado. La alternativa —sumar o promediar los siete
componentes en un numero— produce compensaciones absurdas: un riesgo pesimo
queda tapado por un fundamental excelente y la senal sale igual de buena. Un
limitador no se compensa con nada, y ademas deja explicado el porque.

## Umbrales

Ninguno esta en este fichero. Todos vienen de `reglas.yaml`, versionados junto
al modelo, porque una senal es una recomendacion publicada: tiene que poder
reproducirse sabiendo que version de la configuracion la produjo.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .config import Config
from .datos.almacen import VistaPuntual


class Tipo(enum.StrEnum):
    """Los cinco niveles. Coinciden con `SignalType` del esquema (D-14)."""

    COMPRA_FUERTE = "strong_buy"
    COMPRA = "buy"
    MANTENER = "hold"
    VENTA = "sell"
    VENTA_FUERTE = "strong_sell"


#: De mejor a peor. El orden es lo que da sentido a "rebajar una senal".
ESCALA = (
    Tipo.COMPRA_FUERTE,
    Tipo.COMPRA,
    Tipo.MANTENER,
    Tipo.VENTA,
    Tipo.VENTA_FUERTE,
)


class Regimen(enum.StrEnum):
    ALCISTA = "alcista"
    LATERAL = "lateral"
    BAJISTA = "bajista"
    #: No hay indice, o esta desfasado. **No** es lo mismo que lateral: es que
    #: no se sabe, y se trata como el caso adverso.
    DESCONOCIDO = "desconocido"


class Motivo(enum.StrEnum):
    """Vocabulario cerrado. Anadir uno es una decision, no un descuido."""

    SCORE_ALTO = "score_alto"
    SCORE_INTERMEDIO = "score_intermedio"
    SCORE_BAJO = "score_bajo"
    LIMITA_REGIMEN = "limita_regimen"
    LIMITA_RIESGO = "limita_riesgo"
    LIMITA_MOMENTUM = "limita_momentum"
    LIMITA_SCORE_CAYENDO = "limita_score_cayendo"
    LIMITA_VALORACION = "limita_valoracion"
    DATOS_INSUFICIENTES = "datos_insuficientes"


@dataclass(frozen=True, slots=True)
class Senal:
    """Una senal con lo que hace falta para publicarla y para explicarla."""

    tipo: Tipo
    motivo: Motivo
    detalle: dict = field(default_factory=dict)
    regimen: Regimen = Regimen.DESCONOCIDO
    #: NO es una probabilidad. Es cuanta de la informacion esperada habia
    #: disponible, de 0 a 1. Llamarla probabilidad invitaria a multiplicarla por
    #: un importe, que es justo lo que no significa.
    confianza: float = 0.0
    horizonte_dias: int | None = None


def _peor(a: Tipo, b: Tipo) -> Tipo:
    return ESCALA[max(ESCALA.index(a), ESCALA.index(b))]


def _rebajar(tipo: Tipo, pasos: int = 1) -> Tipo:
    return ESCALA[min(ESCALA.index(tipo) + pasos, len(ESCALA) - 1)]


# ---------------------------------------------------------------------------
# Regimen de mercado (§26)
# ---------------------------------------------------------------------------


def regimen_de_mercado(
    mercado_id: str, fecha: date, vista: VistaPuntual, cfg: Config
) -> tuple[Regimen, dict]:
    """Regimen a partir de tendencia, drawdown y volatilidad del indice.

    Los tres, y no solo la tendencia: un indice puede estar por encima de su
    media y venir de caer un 25% con la volatilidad al triple, y eso no es un
    mercado alcista por mucho que el precio supere una linea.

    Si falta el indice o esta desfasado devuelve DESCONOCIDO, que aguas abajo se
    trata como adverso. Equivocarse hacia el lado prudente cuesta operaciones no
    hechas; hacia el otro cuesta dinero.
    """
    s = cfg.reglas.senales
    ticker = cfg.reglas.tecnico.indices_regimen.get(mercado_id)
    detalle: dict = {"indice": ticker}
    if not ticker:
        return Regimen.DESCONOCIDO, detalle | {"falta": "sin indice configurado"}

    serie = vista.serie(ticker)
    if serie is None:
        return Regimen.DESCONOCIDO, detalle | {"falta": "sin serie"}
    i = vista.posicion_hasta(ticker)
    if i < 0:
        return Regimen.DESCONOCIDO, detalle | {"falta": "sin sesiones antes del corte"}
    if serie.fechas[i] < fecha - timedelta(days=s.indice_antiguedad_maxima_dias):
        return Regimen.DESCONOCIDO, detalle | {
            "falta": "indice desfasado",
            "ultima_sesion": str(serie.fechas[i]),
        }

    cierre = float(serie.cierre[i])
    media = serie.ma_regimen[i]
    sobre_media = bool(media is not None and not np.isnan(media) and cierre > float(media))

    ventana = serie.cierre[max(0, i + 1 - s.ventana_drawdown) : i + 1]
    maximo = float(np.nanmax(ventana)) if len(ventana) else cierre
    drawdown = (maximo - cierre) / maximo if maximo > 0 else 0.0

    trozo = serie.cierre[max(0, i + 1 - s.ventana_volatilidad) : i + 1]
    if len(trozo) >= 3:
        retornos = np.diff(trozo) / trozo[:-1]
        volatilidad = float(np.nanstd(retornos)) * float(np.sqrt(s.sesiones_por_ano))
    else:
        volatilidad = float("nan")

    detalle |= {
        "sobre_media": sobre_media,
        "drawdown": round(drawdown, 4),
        "volatilidad_anualizada": None if np.isnan(volatilidad) else round(volatilidad, 4),
    }

    if drawdown >= s.drawdown_bajista or not sobre_media:
        return Regimen.BAJISTA, detalle
    if drawdown >= s.drawdown_lateral or (
        not np.isnan(volatilidad) and volatilidad >= s.volatilidad_lateral
    ):
        return Regimen.LATERAL, detalle
    return Regimen.ALCISTA, detalle


# ---------------------------------------------------------------------------
# Senal (§25)
# ---------------------------------------------------------------------------


def evaluar(
    *,
    score: float | None,
    variacion_score: float | None = None,
    probabilidad: float | None = None,
    momentum: float | None = None,
    riesgo: float | None = None,
    valoracion: float | None = None,
    regimen: Regimen = Regimen.DESCONOCIDO,
    cfg: Config,
) -> Senal:
    """Combina los siete componentes de §25 en una senal explicada.

    `riesgo` y `valoracion` son sub-scores en percentil: **mas alto es mejor**,
    igual que el resto. Un riesgo de 10 significa que el valor esta entre los
    peores de su cohorte en riesgo, no que tenga poco.
    """
    s = cfg.reglas.senales

    if score is None:
        return Senal(
            tipo=Tipo.MANTENER,
            motivo=Motivo.DATOS_INSUFICIENTES,
            detalle={"score": None},
            regimen=regimen,
            confianza=0.0,
            horizonte_dias=s.horizonte_dias,
        )

    # 1. Senal base, solo con el score.
    if score >= s.umbral_compra_fuerte:
        base, motivo = Tipo.COMPRA_FUERTE, Motivo.SCORE_ALTO
    elif score >= s.umbral_compra:
        base, motivo = Tipo.COMPRA, Motivo.SCORE_ALTO
    elif score <= s.umbral_venta_fuerte:
        base, motivo = Tipo.VENTA_FUERTE, Motivo.SCORE_BAJO
    elif score <= s.umbral_venta:
        base, motivo = Tipo.VENTA, Motivo.SCORE_BAJO
    else:
        base, motivo = Tipo.MANTENER, Motivo.SCORE_INTERMEDIO

    detalle: dict = {"score": round(score, 2), "base": str(base)}
    tipo = base

    # 2. Limitadores. Cada uno solo puede empeorar la senal, nunca mejorarla, y
    #    el motivo se queda con el que de verdad mordio. Un limitador que no
    #    cambia nada no roba la explicacion.
    def limitar(nuevo: Tipo, razon: Motivo, **datos) -> None:
        nonlocal tipo, motivo
        peor = _peor(tipo, nuevo)
        if peor != tipo:
            tipo, motivo = peor, razon
        detalle.update(datos)

    if regimen in (Regimen.BAJISTA, Regimen.DESCONOCIDO):
        limitar(Tipo(s.tope_regimen_adverso), Motivo.LIMITA_REGIMEN, regimen=str(regimen))
    elif regimen is Regimen.LATERAL:
        limitar(Tipo(s.tope_regimen_lateral), Motivo.LIMITA_REGIMEN, regimen=str(regimen))

    if riesgo is not None and riesgo <= s.riesgo_minimo:
        limitar(Tipo(s.tope_riesgo_alto), Motivo.LIMITA_RIESGO, riesgo=round(riesgo, 2))

    if momentum is not None and momentum <= s.momentum_minimo:
        limitar(Tipo(s.tope_momentum_negativo), Motivo.LIMITA_MOMENTUM, momentum=round(momentum, 4))

    if valoracion is not None and valoracion <= s.valoracion_minima:
        limitar(Tipo(s.tope_valoracion), Motivo.LIMITA_VALORACION, valoracion=round(valoracion, 2))

    if variacion_score is not None and variacion_score <= s.caida_score_maxima:
        peor = _rebajar(tipo)
        if peor != tipo:
            tipo, motivo = peor, Motivo.LIMITA_SCORE_CAYENDO
        detalle["variacion_score"] = round(variacion_score, 2)

    if probabilidad is not None:
        detalle["probabilidad"] = round(probabilidad, 4)
        if probabilidad <= s.probabilidad_minima:
            limitar(Tipo(s.tope_probabilidad_baja), Motivo.LIMITA_RIESGO)

    # 3. Confianza: cuanta de la informacion esperada habia. No es una
    #    probabilidad, y por eso no se llama asi.
    esperados = (variacion_score, momentum, riesgo, valoracion)
    disponibles = sum(1 for v in esperados if v is not None)
    confianza = (1 + disponibles) / (1 + len(esperados))
    if regimen is Regimen.DESCONOCIDO:
        confianza *= s.penalizacion_confianza_regimen

    return Senal(
        tipo=tipo,
        motivo=motivo,
        detalle=detalle,
        regimen=regimen,
        confianza=round(confianza, 4),
        horizonte_dias=s.horizonte_dias,
    )
