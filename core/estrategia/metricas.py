"""Metricas de la curva de capital y de las operaciones.

Una decision que conviene conocer antes de leer un Sharpe de esta app: se
calcula por defecto sobre rentabilidades SEMANALES, no diarias. Con cinco
calendarios distintos, una parte de la cartera esta congelada cualquier dia en
que su mercado tiene fiesta y los demas no. Esos ceros artificiales hunden la
volatilidad diaria medida e inflan el Sharpe sin que la estrategia haya hecho
nada mejor. La periodicidad se fija en `metricas.periodicidad_sharpe` y el
informe dice cual se ha usado.

El factor de anualizacion tampoco es un 252 incrustado: se mide sobre las
sesiones que hay de verdad en el periodo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .config import Config
from .constantes import DIAS_POR_ANO, SEMANAS_POR_ANO


@dataclass(frozen=True, slots=True)
class Resumen:
    """Las metricas que pide el documento, para un conjunto de operaciones."""

    rentabilidad_total: float
    rentabilidad_anualizada: float
    drawdown_maximo: float
    sharpe: float
    pct_ganadoras: float
    n_operaciones: int
    exposicion_media: float
    anos: float
    periodicidad_sharpe: str = "semanal"
    # Las cuatro de la FASE 7. Con valor por defecto porque `Resumen` se
    # construye posicionalmente en el camino de curva vacia.
    #
    # `nan` no es un descuido: sortino y profit_factor no estan definidos
    # cuando no hay perdidas, y devolver 0.0 ahi seria el peor valor posible
    # para la mejor situacion posible. Es preferible "no disponible" a un
    # numero que dice lo contrario de lo que pasa.
    sortino: float = float("nan")
    profit_factor: float = float("nan")
    rotacion_anual: float = 0.0
    dias_medios_en_cartera: float = 0.0

    def como_dict(self) -> dict:
        return {
            "rentabilidad_total": self.rentabilidad_total,
            "rentabilidad_anualizada": self.rentabilidad_anualizada,
            "drawdown_maximo": self.drawdown_maximo,
            "sharpe": self.sharpe,
            "pct_ganadoras": self.pct_ganadoras,
            "n_operaciones": self.n_operaciones,
            "exposicion_media": self.exposicion_media,
            "anos": self.anos,
            "sortino": self.sortino,
            "profit_factor": self.profit_factor,
            "rotacion_anual": self.rotacion_anual,
            "dias_medios_en_cartera": self.dias_medios_en_cartera,
        }


NO_DISPONIBLE = "no disponible"


def como_texto(valor: float, decimales: int = 2) -> str:
    """Formatea una metrica que puede no estar definida.

    Existe para que "no disponible" se escriba igual en los dos informes y,
    sobre todo, para que un `nan` no acabe impreso como "nan" en un informe que
    alguien va a leer para decidir donde pone su dinero.
    """
    if valor is None or not np.isfinite(valor):
        return NO_DISPONIBLE
    return f"{valor:.{decimales}f}"


def drawdown_maximo(valores: np.ndarray) -> float:
    """Caida maxima desde un maximo previo, en tanto por uno y positiva."""
    if valores.size == 0:
        return 0.0
    maximos = np.maximum.accumulate(valores)
    caidas = np.where(maximos > 0, (maximos - valores) / maximos, 0.0)
    return float(np.max(caidas))


def serie_periodica(curva: pd.DataFrame, periodicidad: str) -> pd.Series:
    """Valor de la cartera al final de cada periodo."""
    if curva.empty:
        return pd.Series(dtype=float)
    s = pd.Series(
        curva["valor"].to_numpy(dtype=float),
        index=pd.to_datetime(curva["fecha"]),
    )
    return s.resample("W").last().dropna() if periodicidad == "semanal" else s


def sharpe(
    curva: pd.DataFrame, tasa_libre_riesgo_anual: float, periodicidad: str
) -> float:
    """Ratio de Sharpe sobre las rentabilidades del periodo elegido."""
    serie = serie_periodica(curva, periodicidad)
    if len(serie) < 3:
        return 0.0
    retornos = serie.pct_change().dropna()
    if retornos.empty or float(retornos.std()) == 0.0:
        return 0.0

    por_ano = SEMANAS_POR_ANO if periodicidad == "semanal" else _sesiones_por_ano(curva)
    rf_periodo = (1.0 + tasa_libre_riesgo_anual) ** (1.0 / por_ano) - 1.0
    exceso = retornos - rf_periodo
    return float(exceso.mean() / exceso.std() * np.sqrt(por_ano))


def sortino(
    curva: pd.DataFrame, tasa_libre_riesgo_anual: float, periodicidad: str
) -> float:
    """Sortino: como el Sharpe, pero castigando solo la volatilidad a la baja.

    La diferencia con el Sharpe no es cosmetica. El Sharpe divide por la
    desviacion de TODAS las rentabilidades, asi que penaliza igual una semana de
    +8% que una de -8%. Para una estrategia direccional eso es justo al reves de
    lo que interesa medir: la sorpresa que duele es la de abajo.

    El denominador es la desviacion de los retornos POR DEBAJO del objetivo, con
    los que estan por encima puestos a cero en lugar de excluidos. Excluirlos
    seria dividir por la desviacion de una muestra distinta —la de los meses
    malos solos— y daria un numero que sube cuando la estrategia pierde menos
    veces, aunque pierda mas.
    """
    serie = serie_periodica(curva, periodicidad)
    if len(serie) < 3:
        return float("nan")
    retornos = serie.pct_change().dropna()
    if retornos.empty:
        return float("nan")

    por_ano = SEMANAS_POR_ANO if periodicidad == "semanal" else _sesiones_por_ano(curva)
    rf_periodo = (1.0 + tasa_libre_riesgo_anual) ** (1.0 / por_ano) - 1.0
    exceso = retornos - rf_periodo

    bajistas = np.minimum(exceso.to_numpy(dtype=float), 0.0)
    desviacion = float(np.sqrt(np.mean(bajistas**2)))
    if desviacion == 0.0:
        # Ni una sola semana por debajo del activo sin riesgo. Es un resultado
        # real, no un error, pero el ratio no esta definido: dividir por cero
        # daria infinito y devolver 0.0 diria "pesimo". Que el informe lo
        # presente como no disponible.
        return float("nan")
    return float(exceso.mean() / desviacion * np.sqrt(por_ano))


def profit_factor(operaciones: pd.DataFrame) -> float:
    """Ganancia bruta dividida entre perdida bruta, ambas en positivo.

    Por encima de 1 la estrategia gana. Complementa al porcentaje de ganadoras,
    que por si solo engana: una estrategia puede acertar el 80% de las veces y
    arruinarse si el 20% restante pierde el triple de lo que ganan las otras.
    """
    if operaciones.empty or "resultado_base" not in operaciones:
        return float("nan")
    resultados = operaciones["resultado_base"].to_numpy(dtype=float)
    ganancia = float(resultados[resultados > 0].sum())
    perdida = float(-resultados[resultados < 0].sum())
    if perdida == 0.0:
        # Sin una sola operacion perdedora. Igual que en sortino: no definido.
        return float("nan")
    return ganancia / perdida


def rotacion_anual(curva: pd.DataFrame, operaciones: pd.DataFrame) -> float:
    """Rotacion de la cartera al ano, en veces sobre el patrimonio medio.

    Se mide en una direccion: se suma lo comprado y lo vendido y se divide entre
    dos. Sin esa division, una cartera que compra y vende una vez cada posicion
    saldria con rotacion 2 en lugar de 1, que es lo que uno entiende al decir
    "rota la cartera entera una vez al ano".

    Importa porque los costes son proporcionales a ella: una rotacion de 6
    multiplica por seis el peaje de comisiones y deslizamiento sobre el mismo
    capital.

    **Limitacion, y no es menor:** solo cuenta operaciones CERRADAS. Lo que
    sigue abierto al final del backtest se compro y no aparece aqui, asi que en
    un periodo corto, o con posiciones muy largas, este numero se queda bajo.
    """
    if curva.empty or operaciones.empty:
        return 0.0
    faltan = {"acciones", "precio_entrada_base", "precio_salida_base"} - set(operaciones)
    if faltan:
        return 0.0

    acciones = operaciones["acciones"].to_numpy(dtype=float)
    comprado = float((acciones * operaciones["precio_entrada_base"]).sum())
    vendido = float((acciones * operaciones["precio_salida_base"]).sum())

    patrimonio_medio = float(curva["valor"].mean())
    dias = (curva["fecha"].iloc[-1] - curva["fecha"].iloc[0]).days
    anos = max(dias / DIAS_POR_ANO, 1e-9)
    if patrimonio_medio <= 0:
        return 0.0
    return (comprado + vendido) / 2.0 / patrimonio_medio / anos


def dias_medios_en_cartera(operaciones: pd.DataFrame) -> float:
    """Dias NATURALES medios que dura una posicion abierta.

    Naturales y no sesiones: son los que cuenta `Operacion.dias`, y con cinco
    calendarios distintos convertirlos a sesiones obligaria a saber de que
    mercado es cada una. Para lo que sirve el dato —saber si la estrategia opera
    en semanas o en meses— la diferencia no cambia ninguna decision.
    """
    if operaciones.empty or "dias" not in operaciones:
        return 0.0
    return float(operaciones["dias"].mean())


def _sesiones_por_ano(curva: pd.DataFrame) -> float:
    """Sesiones por ano medidas sobre el propio historico, no supuestas."""
    if len(curva) < 2:
        return 252.0
    dias = (curva["fecha"].iloc[-1] - curva["fecha"].iloc[0]).days
    return len(curva) / max(dias / DIAS_POR_ANO, 1e-9) if dias > 0 else 252.0


def resumir(curva: pd.DataFrame, operaciones: pd.DataFrame, cfg: Config) -> Resumen:
    """Resumen completo de un backtest."""
    periodicidad = cfg.reglas.metricas.periodicidad_sharpe
    if curva.empty:
        return Resumen(0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, periodicidad)

    valores = curva["valor"].to_numpy(dtype=float)
    inicial, final = float(valores[0]), float(valores[-1])
    dias = (curva["fecha"].iloc[-1] - curva["fecha"].iloc[0]).days
    anos = max(dias / DIAS_POR_ANO, 1e-9)

    total = final / inicial - 1.0 if inicial > 0 else 0.0
    anualizada = (final / inicial) ** (1.0 / anos) - 1.0 if inicial > 0 and anos > 0 else 0.0

    ganadoras = (
        float(operaciones["ganadora"].mean()) if not operaciones.empty else 0.0
    )
    return Resumen(
        rentabilidad_total=total,
        rentabilidad_anualizada=anualizada,
        drawdown_maximo=drawdown_maximo(valores),
        sharpe=sharpe(curva, cfg.reglas.metricas.tasa_libre_riesgo_anual, periodicidad),
        pct_ganadoras=ganadoras,
        n_operaciones=int(len(operaciones)),
        exposicion_media=float(curva["exposicion"].mean()),
        anos=anos,
        periodicidad_sharpe=periodicidad,
        sortino=sortino(
            curva, cfg.reglas.metricas.tasa_libre_riesgo_anual, periodicidad
        ),
        profit_factor=profit_factor(operaciones),
        rotacion_anual=rotacion_anual(curva, operaciones),
        dias_medios_en_cartera=dias_medios_en_cartera(operaciones),
    )


def por_ano(curva: pd.DataFrame, operaciones: pd.DataFrame) -> pd.DataFrame:
    """Rentabilidad y numero de operaciones de cada ano natural."""
    if curva.empty:
        return pd.DataFrame()
    c = curva.copy()
    c["ano"] = [f.year for f in c["fecha"]]
    filas = []
    for ano, grupo in c.groupby("ano"):
        v = grupo["valor"].to_numpy(dtype=float)
        ops = (
            operaciones[[f.year == ano for f in operaciones["fecha_salida"]]]
            if not operaciones.empty
            else pd.DataFrame()
        )
        filas.append(
            {
                "ano": int(ano),
                "rentabilidad": float(v[-1] / v[0] - 1.0) if v[0] > 0 else 0.0,
                "drawdown_maximo": drawdown_maximo(v),
                "n_operaciones": int(len(ops)),
                "pct_ganadoras": float(ops["ganadora"].mean()) if len(ops) else 0.0,
            }
        )
    return pd.DataFrame(filas)


def por_mercado(operaciones: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Resultado agregado por mercado.

    El documento lo pide expresamente: una estrategia global puede parecer
    solida en el agregado mientras una region concreta arrastra el resultado.
    """
    if operaciones.empty:
        return pd.DataFrame()
    filas = []
    for mercado, g in operaciones.groupby("mercado"):
        filas.append(
            {
                "mercado": mercado,
                "bloque": cfg.reglas.mercado(str(mercado)).clasificacion,
                "n_operaciones": int(len(g)),
                "resultado_base": float(g["resultado_base"].sum()),
                "pct_ganadoras": float(g["ganadora"].mean()),
                "resultado_medio": float(g["resultado_base"].mean()),
                "costes_base": float(g["costes_base"].sum()),
                "coste_pct_medio": float(g["coste_pct_posicion"].mean()),
            }
        )
    return pd.DataFrame(filas).sort_values("mercado").reset_index(drop=True)


def por_bloque(operaciones: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Resultado agregado por bloque desarrollado/emergente."""
    if operaciones.empty:
        return pd.DataFrame()
    o = operaciones.copy()
    o["bloque"] = [cfg.reglas.mercado(str(m)).clasificacion for m in o["mercado"]]
    filas = []
    for bloque, g in o.groupby("bloque"):
        filas.append(
            {
                "bloque": bloque,
                "n_operaciones": int(len(g)),
                "resultado_base": float(g["resultado_base"].sum()),
                "pct_ganadoras": float(g["ganadora"].mean()),
                "costes_base": float(g["costes_base"].sum()),
            }
        )
    return pd.DataFrame(filas).sort_values("bloque").reset_index(drop=True)


@dataclass(frozen=True, slots=True)
class UsoDelRiesgo:
    """Cuanto se parece el riesgo real al riesgo nominal.

    Existe porque el tope de peso muerde casi siempre y `riesgo.por_operacion`
    casi nunca: sin este desglose, el analisis de sensibilidad diria que la
    estrategia es robusta a ese parametro cuando lo que pasa es que estaba
    inactivo.
    """

    riesgo_teorico_medio: float
    riesgo_efectivo_medio: float
    pct_limitadas_por_peso: float
    n: int


def uso_del_riesgo(eventos: pd.DataFrame) -> UsoDelRiesgo:
    if eventos.empty or "riesgo_efectivo_pct" not in eventos.columns:
        return UsoDelRiesgo(0.0, 0.0, 0.0, 0)
    ordenes = eventos[eventos["tipo"] == "orden"].dropna(subset=["riesgo_efectivo_pct"])
    if ordenes.empty:
        return UsoDelRiesgo(0.0, 0.0, 0.0, 0)
    return UsoDelRiesgo(
        riesgo_teorico_medio=float(ordenes["riesgo_teorico_pct"].mean()),
        riesgo_efectivo_medio=float(ordenes["riesgo_efectivo_pct"].mean()),
        pct_limitadas_por_peso=float(ordenes["limitada_por_peso_maximo"].mean()),
        n=int(len(ordenes)),
    )


def curva_referencia(
    nombre: str, curva: pd.DataFrame, vista_final, cfg: Config
) -> pd.Series | None:
    """Curva de una referencia, escalada al capital inicial.

    Se usan ETF de acumulacion cotizados en euros, de modo que los dividendos
    van dentro del precio y no hay una conversion de divisa mas donde
    equivocarse.
    """
    ref = cfg.implementacion.referencias.get(nombre)
    if ref is None or curva.empty:
        return None
    serie = vista_final.serie(ref.ticker)
    if serie is None or len(serie.cierre) == 0:
        return None

    fechas = list(curva["fecha"])
    valores = []
    for f in fechas:
        i = serie.posicion(f)
        valores.append(float(serie.cierre[i]) if i >= 0 else np.nan)
    s = pd.Series(valores, index=pd.Index(fechas, name="fecha")).ffill().bfill()
    if s.isna().all() or float(s.iloc[0]) == 0.0:
        return None
    return s / float(s.iloc[0]) * float(curva["valor"].iloc[0])
