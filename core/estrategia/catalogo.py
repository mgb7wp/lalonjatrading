"""Catalogo de indicadores tecnicos, con registro.

## Por que un registro y no treinta funciones sueltas

§13 del encargo pide "una arquitectura que permita anadir indicadores
facilmente". Aqui eso significa algo concreto: **anadir un indicador es escribir
una funcion y decorarla**. No hay que tocar el motor, ni la tabla, ni el
pipeline, ni acordarse de anadirlo a tres listas distintas.

Pero el registro da algo mas valioso que la comodidad, y es la razon de fondo
para tenerlo: permite escribir **una vez** las comprobaciones que deben cumplir
todos. La que importa es la de sesgo de anticipacion. Con funciones sueltas hay
que acordarse de probar cada indicador nuevo contra el futuro; con un registro,
el test recorre el catalogo y **un indicador nuevo queda cubierto el dia que se
escribe**, sin que su autor haga nada.

## La regla que cumplen todos

Cada indicador es una **ventana hacia atras**: la posicion `i` de su vector solo
puede depender de datos en posiciones `<= i`. Los recursivos (EMA, RSI, ATR y
ADX de Wilder) arrastran todo el historial anterior, lo cual cumple la regla
igual: miran hacia atras, no hacia delante.

De ahi sale la propiedad que se comprueba: **recortar la serie por el final no
cambia el valor en la fecha de corte**. Si lo cambiara, el indicador estaria
usando datos que ese dia no existian.

## Que es esto y que no

Aqui estan los indicadores que se **muestran y se sirven**. El motor de
backtesting tiene los suyos precalculados en `indicadores.py`, en el camino
critico del bucle diario, y esos no se tocan: son cinco, estan probados y
cualquier cosa que los ralentice hace inutilizable el analisis de sensibilidad.
Los de aqui se calculan una vez al dia y van a `technical_indicator`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from .indicadores import atr_wilder_vector, media_movil_vector

#: Sesiones bursatiles en un ano. Se usa para anualizar volatilidad y para las
#: ventanas de 52 semanas; es una convencion, no una medida del calendario.
SESIONES_ANO = 252


@dataclass(frozen=True, slots=True)
class Ventana:
    """Los datos de un valor, alineados por sesion.

    `referencia` son los cierres del indice del mercado en las MISMAS fechas.
    Alinear es responsabilidad de quien construye la ventana: un indicador que
    tuviera que buscar la fecha equivalente en otra serie seria un indicador con
    una oportunidad de mirar hacia delante.
    """

    fechas: np.ndarray
    apertura: np.ndarray
    maximo: np.ndarray
    minimo: np.ndarray
    cierre: np.ndarray
    cierre_bruto: np.ndarray
    volumen: np.ndarray
    referencia: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.cierre)


@dataclass(frozen=True, slots=True)
class Indicador:
    """Un indicador del catalogo."""

    nombre: str
    calcular: Callable[[Ventana], np.ndarray]
    ventana_minima: int
    descripcion: str
    necesita_referencia: bool = False


REGISTRO: dict[str, Indicador] = {}


def registrar(
    nombre: str,
    ventana_minima: int,
    descripcion: str,
    necesita_referencia: bool = False,
) -> Callable:
    """Da de alta un indicador en el catalogo.

    `ventana_minima` no es documentacion: es lo que permite decir "este valor no
    tiene historico suficiente para este indicador" en lugar de servir un numero
    calculado sobre cuatro sesiones como si valiera lo mismo que uno calculado
    sobre doscientas.
    """

    def decorador(funcion: Callable[[Ventana], np.ndarray]) -> Callable:
        if nombre in REGISTRO:
            raise ValueError(f"indicador duplicado en el catalogo: {nombre}")
        REGISTRO[nombre] = Indicador(
            nombre=nombre,
            calcular=funcion,
            ventana_minima=ventana_minima,
            descripcion=descripcion,
            necesita_referencia=necesita_referencia,
        )
        return funcion

    return decorador


# ---------------------------------------------------------------------------
# Primitivas
# ---------------------------------------------------------------------------


def _vacio(n: int) -> np.ndarray:
    return np.full(n, np.nan)


def ema_vector(valores: np.ndarray, periodo: int) -> np.ndarray:
    """Media exponencial, sembrada con la media simple de la primera ventana.

    Sembrarla con el primer valor en lugar de con la media simple da numeros
    distintos durante las primeras decenas de sesiones. Se fija la convencion
    aqui y se comprueba, porque de esto depende el MACD.
    """
    n = len(valores)
    salida = _vacio(n)
    if n < periodo or periodo <= 0:
        return salida
    alfa = 2.0 / (periodo + 1.0)
    actual = float(np.mean(valores[:periodo]))
    salida[periodo - 1] = actual
    for i in range(periodo, n):
        actual = alfa * float(valores[i]) + (1.0 - alfa) * actual
        salida[i] = actual
    return salida


def _suavizado_wilder(valores: np.ndarray, periodo: int) -> np.ndarray:
    """Suavizado de Wilder: la media del primer tramo y despues recursivo.

    No es una media exponencial con `alfa = 2/(n+1)`: Wilder usa `1/n`. Da
    numeros parecidos y distintos, y como de esto dependen RSI y ADX, la
    definicion se fija y se comprueba.
    """
    n = len(valores)
    salida = _vacio(n)
    if n < periodo or periodo <= 0:
        return salida
    actual = float(np.mean(valores[:periodo]))
    salida[periodo - 1] = actual
    for i in range(periodo, n):
        actual = (actual * (periodo - 1) + float(valores[i])) / periodo
        salida[i] = actual
    return salida


def _rodante(valores: np.ndarray, periodo: int, funcion) -> np.ndarray:
    """Aplica una funcion a cada ventana hacia atras de tamano `periodo`."""
    n = len(valores)
    salida = _vacio(n)
    if n < periodo or periodo <= 0:
        return salida
    ventanas = sliding_window_view(valores, periodo)
    salida[periodo - 1 :] = funcion(ventanas, axis=1)
    return salida


def _desplazar(valores: np.ndarray, periodo: int) -> np.ndarray:
    """El valor de hace `periodo` sesiones, con NaN donde aun no lo hay."""
    salida = _vacio(len(valores))
    if periodo < len(valores):
        salida[periodo:] = valores[:-periodo]
    return salida


def _division(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Division que devuelve NaN en lugar de infinito al dividir por cero."""
    with np.errstate(divide="ignore", invalid="ignore"):
        salida = np.where(b != 0, a / b, np.nan)
    return salida


# ---------------------------------------------------------------------------
# Tendencia
# ---------------------------------------------------------------------------


def _registrar_medias() -> None:
    """Las medias simples, que solo se diferencian en el periodo."""
    for periodo in (20, 50, 100, 200):
        registrar(
            f"sma_{periodo}",
            periodo,
            f"Media movil simple de {periodo} sesiones",
        )(lambda v, p=periodo: media_movil_vector(v.cierre, p))


_registrar_medias()


@registrar("ema_20", 20, "Media movil exponencial de 20 sesiones")
def _ema_20(v: Ventana) -> np.ndarray:
    return ema_vector(v.cierre, 20)


@registrar("macd", 26, "MACD: EMA(12) menos EMA(26)")
def _macd(v: Ventana) -> np.ndarray:
    return ema_vector(v.cierre, 12) - ema_vector(v.cierre, 26)


@registrar("macd_signal", 34, "Senal del MACD: EMA(9) del propio MACD")
def _macd_signal(v: Ventana) -> np.ndarray:
    macd = _macd(v)
    salida = _vacio(len(macd))
    validos = ~np.isnan(macd)
    if validos.sum() < 9:
        return salida
    primero = int(np.argmax(validos))
    # La EMA se calcula solo sobre el tramo con dato: arrastrar los NaN
    # iniciales los propagaria a toda la serie.
    salida[primero:] = ema_vector(macd[primero:], 9)
    return salida


# ---------------------------------------------------------------------------
# Momento
# ---------------------------------------------------------------------------


@registrar("rsi_14", 15, "Indice de fuerza relativa de Wilder, 14 sesiones")
def _rsi_14(v: Ventana) -> np.ndarray:
    periodo = 14
    n = len(v.cierre)
    salida = _vacio(n)
    if n < periodo + 1:
        return salida

    cambios = np.diff(v.cierre)
    subidas = np.where(cambios > 0, cambios, 0.0)
    bajadas = np.where(cambios < 0, -cambios, 0.0)

    media_sube = _suavizado_wilder(subidas, periodo)
    media_baja = _suavizado_wilder(bajadas, periodo)

    # `cambios` tiene un elemento menos que la serie: el indice i de `cambios`
    # corresponde al i+1 de los cierres.
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(media_baja != 0, media_sube / media_baja, np.inf)
        rsi = 100.0 - 100.0 / (1.0 + rs)

    # Tres casos que conviene no confundir:
    #
    # - Sin bajadas pero con subidas: RSI 100 por definicion.
    # - Sin subidas pero con bajadas: RSI 0.
    # - **Ni subidas ni bajadas**: no hay fuerza relativa que medir. Es 0/0, y
    #   la formula devolveria 100 porque trata la division por cero como
    #   infinito. Servir un 100 para un precio quieto es peor que no servir
    #   nada: un valor cuya cotizacion se ha congelado —deslistado, suspendido,
    #   o al que el proveedor ha dejado de dar datos— apareceria como el de
    #   momento mas fuerte de todo el mercado.
    quieto = (media_sube == 0) & (media_baja == 0)
    rsi = np.where(quieto | np.isnan(media_baja), np.nan, rsi)
    salida[1:] = rsi
    return salida


@registrar("roc_20", 21, "Tasa de cambio a 20 sesiones")
def _roc_20(v: Ventana) -> np.ndarray:
    return _division(v.cierre, _desplazar(v.cierre, 20)) - 1.0


@registrar("momentum_12_1", 252, "Momentum de 12 meses excluyendo el ultimo")
def _momentum_12_1(v: Ventana) -> np.ndarray:
    """Los ultimos ~21 dias se excluyen: el efecto de reversion a corto plazo
    contamina la medida de tendencia a doce meses."""
    hace_12m = _desplazar(v.cierre, 252)
    hace_1m = _desplazar(v.cierre, 21)
    return _division(hace_1m, hace_12m) - 1.0


@registrar("aceleracion_precio", 41, "Cambio del ROC(20) respecto a hace 20 sesiones")
def _aceleracion(v: Ventana) -> np.ndarray:
    """Segunda derivada del precio: no si sube, sino si sube cada vez mas.

    Un valor que lleva tres meses subiendo al mismo ritmo y otro que ha empezado
    a acelerar tienen el mismo momentum y no son la misma oportunidad.
    """
    roc = _roc_20(v)
    return roc - _desplazar(roc, 20)


# ---------------------------------------------------------------------------
# Volatilidad y riesgo
# ---------------------------------------------------------------------------


@registrar("atr_14", 15, "Rango verdadero medio de Wilder, 14 sesiones")
def _atr_14(v: Ventana) -> np.ndarray:
    return atr_wilder_vector(v.maximo, v.minimo, v.cierre, 14)


@registrar("volatilidad_60", 61, "Volatilidad anualizada de 60 sesiones")
def _volatilidad_60(v: Ventana) -> np.ndarray:
    n = len(v.cierre)
    salida = _vacio(n)
    if n < 2:
        return salida
    with np.errstate(divide="ignore", invalid="ignore"):
        log_ret = np.diff(np.log(np.where(v.cierre > 0, v.cierre, np.nan)))
    desviacion = _rodante(log_ret, 60, np.std)
    salida[1:] = desviacion * np.sqrt(SESIONES_ANO)
    return salida


@registrar("drawdown_maximo_1a", SESIONES_ANO, "Peor caida desde maximo en 252 sesiones")
def _drawdown_maximo_1a(v: Ventana) -> np.ndarray:
    """Negativo por convenio: -0,25 es una caida del 25 %."""
    n = len(v.cierre)
    salida = _vacio(n)
    if n < SESIONES_ANO:
        return salida
    ventanas = sliding_window_view(v.cierre, SESIONES_ANO)
    maximos = np.maximum.accumulate(ventanas, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        caidas = np.where(maximos > 0, ventanas / maximos - 1.0, np.nan)
    salida[SESIONES_ANO - 1 :] = np.nanmin(caidas, axis=1)
    return salida


@registrar("beta_252", SESIONES_ANO + 1, "Beta frente al indice, 252 sesiones", True)
def _beta_252(v: Ventana) -> np.ndarray:
    n = len(v.cierre)
    salida = _vacio(n)
    if v.referencia is None or n < SESIONES_ANO + 1:
        return salida

    # Se descarta el primer elemento: no hay retorno para la primera sesion. Sin
    # recortarlo, la ventana que acaba en la sesion 252 incluiria ese hueco y el
    # vector saldria desplazado una posicion, que es un sesgo de un dia entero.
    #
    # Los huecos que queden dentro de una ventana se propagan como NaN en lugar
    # de sustituirse por cero: un retorno desconocido no es un retorno nulo, y
    # rellenarlo con cero baja la beta sin que nada avise.
    a = _retornos(v.cierre)[1:]
    b = _retornos(v.referencia)[1:]
    if len(a) < SESIONES_ANO or len(b) < SESIONES_ANO:
        return salida

    ventanas_a = sliding_window_view(a, SESIONES_ANO)
    ventanas_b = sliding_window_view(b, SESIONES_ANO)
    media_a = ventanas_a.mean(axis=1, keepdims=True)
    media_b = ventanas_b.mean(axis=1, keepdims=True)
    covarianza = ((ventanas_a - media_a) * (ventanas_b - media_b)).mean(axis=1)
    varianza = ((ventanas_b - media_b) ** 2).mean(axis=1)
    salida[SESIONES_ANO:] = _division(covarianza, varianza)
    return salida


def _retornos(valores: np.ndarray) -> np.ndarray:
    salida = _vacio(len(valores))
    if len(valores) < 2:
        return salida
    previo = valores[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        salida[1:] = np.where(previo > 0, valores[1:] / previo - 1.0, np.nan)
    return salida


# ---------------------------------------------------------------------------
# Estructura de precio
# ---------------------------------------------------------------------------


@registrar("adx_14", 28, "Indice direccional medio de Wilder, 14 sesiones")
def _adx_14(v: Ventana) -> np.ndarray:
    periodo = 14
    n = len(v.cierre)
    salida = _vacio(n)
    if n < 2 * periodo:
        return salida

    sube = v.maximo[1:] - v.maximo[:-1]
    baja = v.minimo[:-1] - v.minimo[1:]
    mas_dm = np.where((sube > baja) & (sube > 0), sube, 0.0)
    menos_dm = np.where((baja > sube) & (baja > 0), baja, 0.0)

    previo = v.cierre[:-1]
    rango = np.maximum(
        v.maximo[1:] - v.minimo[1:],
        np.maximum(np.abs(v.maximo[1:] - previo), np.abs(v.minimo[1:] - previo)),
    )

    tr = _suavizado_wilder(rango, periodo)
    mas_di = 100.0 * _division(_suavizado_wilder(mas_dm, periodo), tr)
    menos_di = 100.0 * _division(_suavizado_wilder(menos_dm, periodo), tr)

    with np.errstate(divide="ignore", invalid="ignore"):
        dx = 100.0 * _division(np.abs(mas_di - menos_di), mas_di + menos_di)
    validos = ~np.isnan(dx)
    if validos.sum() < periodo:
        return salida
    primero = int(np.argmax(validos))
    salida[primero + 1 :] = _suavizado_wilder(dx[primero:], periodo)
    return salida


@registrar("estocastico_k", 14, "Estocastico %K de 14 sesiones")
def _estocastico_k(v: Ventana) -> np.ndarray:
    minimos = _rodante(v.minimo, 14, np.min)
    maximos = _rodante(v.maximo, 14, np.max)
    return 100.0 * _division(v.cierre - minimos, maximos - minimos)


@registrar("bollinger_posicion", 20, "Posicion dentro de las bandas de Bollinger")
def _bollinger_posicion(v: Ventana) -> np.ndarray:
    """0 es la banda inferior y 1 la superior; fuera de [0,1] es rotura.

    Se publica la posicion y no las tres bandas porque es lo que responde a la
    pregunta util —donde esta el precio dentro de su rango habitual— con un
    numero en lugar de con tres.
    """
    media = media_movil_vector(v.cierre, 20)
    desviacion = _rodante(v.cierre, 20, np.std)
    inferior = media - 2.0 * desviacion
    superior = media + 2.0 * desviacion
    return _division(v.cierre - inferior, superior - inferior)


@registrar("distancia_maximo_52s", SESIONES_ANO, "Distancia al maximo de 52 semanas")
def _distancia_maximo(v: Ventana) -> np.ndarray:
    """Negativa o cero: cuanto hay que subir para volver al maximo del ano."""
    return _division(v.cierre, _rodante(v.cierre, SESIONES_ANO, np.max)) - 1.0


@registrar("distancia_minimo_52s", SESIONES_ANO, "Distancia al minimo de 52 semanas")
def _distancia_minimo(v: Ventana) -> np.ndarray:
    return _division(v.cierre, _rodante(v.cierre, SESIONES_ANO, np.min)) - 1.0


# ---------------------------------------------------------------------------
# Volumen y fuerza relativa
# ---------------------------------------------------------------------------


@registrar("ratio_volumen_20", 20, "Volumen frente a su media de 20 sesiones")
def _ratio_volumen_20(v: Ventana) -> np.ndarray:
    return _division(v.volumen, media_movil_vector(v.volumen, 20))


@registrar("fuerza_relativa_126", 127, "Rentabilidad a 6 meses frente al indice", True)
def _fuerza_relativa(v: Ventana) -> np.ndarray:
    """Cuanto ha batido al indice de su mercado en seis meses.

    Se mide contra el indice del propio mercado y no contra uno global: una
    accion espanola que sube un 5 % mientras el IBEX sube un 15 % no es fuerte,
    por mucho que suba.
    """
    if v.referencia is None:
        return _vacio(len(v.cierre))
    valor = _division(v.cierre, _desplazar(v.cierre, 126))
    indice = _division(v.referencia, _desplazar(v.referencia, 126))
    return _division(valor, indice) - 1.0


# ---------------------------------------------------------------------------
# Calculo del catalogo completo
# ---------------------------------------------------------------------------


@dataclass
class Resultado:
    """Los vectores de cada indicador, mas los que no se pudieron calcular."""

    valores: dict[str, np.ndarray] = field(default_factory=dict)
    omitidos: dict[str, str] = field(default_factory=dict)


def calcular(ventana: Ventana, nombres: list[str] | None = None) -> Resultado:
    """Calcula el catalogo entero sobre una ventana.

    Un indicador que no se puede calcular —falta historico, falta el indice de
    referencia— se omite **con su motivo** en lugar de devolver un vector de
    NaN indistinguible de un fallo silencioso.
    """
    resultado = Resultado()
    for nombre in nombres or list(REGISTRO):
        indicador = REGISTRO[nombre]
        if indicador.necesita_referencia and ventana.referencia is None:
            resultado.omitidos[nombre] = "necesita el indice del mercado"
            continue
        if len(ventana) < indicador.ventana_minima:
            resultado.omitidos[nombre] = (
                f"historico insuficiente: {len(ventana)} sesiones, "
                f"necesita {indicador.ventana_minima}"
            )
            continue
        resultado.valores[nombre] = indicador.calcular(ventana)
    return resultado
