"""Tipos compartidos por toda la app.

Este modulo es una hoja del grafo de importaciones: no importa nada del propio
paquete. Esa disciplina es lo que evita el ciclo clasico de un proyecto con esta
forma (`cartera` necesita `riesgo`, que necesita `seleccion`, que necesita
`cartera`). Si algo hace falta en dos modulos, vive aqui.

Los motivos de rechazo y de salida son enumeraciones y no cadenas sueltas
porque el informe se construye contando: sin un vocabulario cerrado no se puede
responder a "por que no se compro la mejor candidata de esta semana".
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any


class MotivoRechazo(enum.StrEnum):
    """Por que una candidata no llego a comprarse.

    El orden de los miembros es el orden en que se comprueban, y esa secuencia
    es la que hace el backtest reproducible: si dos motivos pudieran aplicarse,
    siempre gana el primero.
    """

    YA_EN_CARTERA = "ya_en_cartera"
    REGIMEN_APAGADO = "regimen_apagado"
    HISTORIAL_INSUFICIENTE = "historial_insuficiente"
    FALLA_TECNICO = "falla_tecnico"
    FALLA_FUNDAMENTAL = "falla_fundamental"
    SIN_DATO_FUNDAMENTAL = "sin_dato_fundamental"
    FUNDAMENTAL_CADUCADO = "fundamental_caducado"
    SECTOR_DESCONOCIDO = "sector_desconocido"
    SECTOR_EXCLUIDO = "sector_excluido"
    LIQUIDEZ_INSUFICIENTE = "liquidez_insuficiente"
    SIN_HUECO = "sin_hueco"
    TOPE_SECTOR = "tope_sector"
    TOPE_MERCADO = "tope_mercado"
    TAMANO_CERO = "tamano_cero"
    EFECTIVO_INSUFICIENTE = "efectivo_insuficiente"
    SIN_PRECIO_EJECUCION = "sin_precio_ejecucion"


class MotivoSalida(enum.StrEnum):
    """Por que se cerro una posicion."""

    STOP_HUECO = "stop_hueco"
    STOP_INTRADIA = "stop_intradia"
    BAJO_MEDIA_LARGA = "bajo_media_larga"
    FALLA_FUNDAMENTAL = "falla_fundamental"
    CIERRE_FORZOSO_SIN_DATOS = "cierre_forzoso_sin_datos"
    ABIERTA_AL_FINAL = "abierta_al_final"


class CohorteUsada(enum.StrEnum):
    """Sobre que conjunto se percentilo una puntuacion.

    Se guarda en cada candidata para que una operacion rara se pueda rastrear
    hasta una cohorte demasiado pequena para significar nada.
    """

    MERCADO = "mercado"
    BLOQUE = "bloque"
    INSUFICIENTE = "insuficiente"


@dataclass(frozen=True, slots=True)
class SenalTecnica:
    """Lectura tecnica de un valor en una fecha, en divisa local."""

    ticker: str
    mercado: str
    fecha: date
    cierre: float
    media_corta: float | None
    media_larga: float | None
    momentum: float | None
    atr: float
    historial_suficiente: bool

    @property
    def tendencia_alcista(self) -> bool:
        """Cierre sobre la media larga y media corta sobre la larga."""
        if self.media_corta is None or self.media_larga is None:
            return False
        return self.cierre > self.media_larga and self.media_corta > self.media_larga

    @property
    def comprable(self) -> bool:
        """Las tres condiciones tecnicas del documento a la vez."""
        return (
            self.historial_suficiente
            and self.tendencia_alcista
            and self.momentum is not None
            and self.momentum > 0
        )


@dataclass(frozen=True, slots=True)
class PuntuacionFundamental:
    """Puntuacion fundamental de 0 a 100 y sus componentes."""

    ticker: str
    mercado: str
    sector: str
    aprueba: bool
    calidad: float | None
    valoracion: float | None
    puntuacion: float | None
    n_cohorte: int
    cohorte_usada: CohorteUsada
    motivo: MotivoRechazo | None = None


@dataclass(frozen=True, slots=True)
class Candidata:
    """Un valor comprable, ya puntuado y listo para ordenar."""

    ticker: str
    mercado: str
    sector: str
    fecha_decision: date
    puntuacion_fundamental: float
    percentil_momentum: float
    puntuacion_final: float
    senal: SenalTecnica
    n_cohorte: int
    cohorte_usada: CohorteUsada

    def clave_orden(self) -> tuple[float, str]:
        """Orden descendente por puntuacion, con el ticker como desempate.

        El desempate explicito no es cosmetico: sin el, dos ejecuciones del
        mismo backtest pueden dar carteras distintas segun como ordene pandas.
        """
        return (-self.puntuacion_final, self.ticker)


@dataclass(frozen=True, slots=True)
class Orden:
    """Una compra decidida en la revision semanal, aun sin ejecutar.

    Los huecos de cartera se reservan al decidir, no al ejecutar: si se
    comprobaran los limites en el momento del fill, el mercado que abre antes
    (India, 04:00 UTC) se quedaria siempre con los huecos antes que Europa o
    EE. UU., que es un sesgo de calendario, no una decision de estrategia.
    """

    ticker: str
    mercado: str
    sector: str
    fecha_decision: date
    acciones: int
    stop_inicial_local: float
    atr_entrada: float
    rango_asignacion: int
    puntuacion_final: float
    riesgo_teorico_pct: float
    riesgo_efectivo_pct: float
    limitada_por_peso_maximo: bool


@dataclass(frozen=True, slots=True)
class Posicion:
    """Una posicion abierta.

    `maximo_cierre_local` es el maximo de CIERRES desde la entrada, nunca de
    maximos intradia: usar maximos apretaria el stop y mejoraria el backtest
    sin que la estrategia lo diga.
    """

    ticker: str
    mercado: str
    sector: str
    divisa: str
    acciones: int
    fecha_entrada: date
    precio_entrada_local: float
    precio_entrada_base: float
    fx_entrada: float
    atr_entrada: float
    stop_inicial_local: float
    maximo_cierre_local: float
    stop_dinamico_local: float
    coste_entrada_base: float
    riesgo_teorico_pct: float
    riesgo_efectivo_pct: float
    sesiones_sin_datos: int = 0
    ultimo_cierre_local: float = 0.0

    @property
    def stop_efectivo_local(self) -> float:
        """El mas alto de los dos stops, como pide el documento."""
        return max(self.stop_inicial_local, self.stop_dinamico_local)

    def con_cierre(self, cierre: float, stop_dinamico_bruto: float) -> "Posicion":
        """Actualiza el trailing con el cierre del dia.

        El stop dinamico lleva trinquete: nunca baja, aunque el ATR se dispare
        y el calculo en bruto de hoy salga por debajo del de ayer.
        """
        return replace(
            self,
            maximo_cierre_local=max(self.maximo_cierre_local, cierre),
            stop_dinamico_local=max(self.stop_dinamico_local, stop_dinamico_bruto),
            ultimo_cierre_local=cierre,
            sesiones_sin_datos=0,
        )

    def sin_datos(self) -> "Posicion":
        return replace(self, sesiones_sin_datos=self.sesiones_sin_datos + 1)


@dataclass(frozen=True, slots=True)
class Operacion:
    """Una operacion cerrada, con todo lo que el informe necesita contar."""

    ticker: str
    mercado: str
    sector: str
    divisa: str
    acciones: int
    fecha_entrada: date
    fecha_salida: date
    precio_entrada_local: float
    precio_salida_local: float
    precio_entrada_base: float
    precio_salida_base: float
    fx_entrada: float
    fx_salida: float
    motivo_salida: MotivoSalida
    costes_base: float
    resultado_base: float
    riesgo_teorico_pct: float
    riesgo_efectivo_pct: float

    @property
    def ganadora(self) -> bool:
        return self.resultado_base > 0

    @property
    def dias(self) -> int:
        return (self.fecha_salida - self.fecha_entrada).days

    @property
    def coste_pct_posicion(self) -> float:
        """Costes de ida y vuelta sobre el nominal de entrada.

        Con 10.000 EUR de capital y una comision fija de 3 EUR por operacion,
        las posiciones pequenas se comen una parte del resultado que no se ve
        en la curva agregada. El informe lo saca a la superficie.
        """
        nominal = self.acciones * self.precio_entrada_base
        return self.costes_base / nominal if nominal else 0.0


@dataclass(frozen=True, slots=True)
class Evento:
    """Una linea del registro estructurado del backtest.

    El informe y el panel se derivan de estos eventos y no de las tripas del
    motor, para poder reconstruir despues por que una semana hizo lo que hizo.
    """

    fecha: date
    tipo: str
    mercado: str = ""
    ticker: str = ""
    motivo: str = ""
    detalles: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Aviso:
    """Un aviso del informe.

    `permanente` marca los que el documento exige que salgan siempre, haya o no
    haya datos que los disparen.
    """

    clave: str
    texto: str
    permanente: bool = False
    gravedad: str = "aviso"
