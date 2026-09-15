"""Filtro fundamental y puntuacion de 0 a 100.

Dos cosas de este modulo merecen explicacion, porque no se deducen del
documento y cambian los resultados.

**Las trampas de signo.** Tres ratios del filtro se dan la vuelta cuando su
denominador o su numerador se vuelven negativos, y en los tres casos una
comprobacion ingenua deja pasar justo a la empresa que habria que descartar:

- EV/EBIT con EBIT negativo sale negativo, y un percentil inverso ("mas barata,
  mejor nota") la coloca como la mas barata del mercado.
- Deuda neta/EBITDA con EBITDA negativo sale negativo y pasa un `<= 3.0`.
- ROE con patrimonio negativo y perdidas sale positivo, y pasa un `>= 0.10`.

Cada uno se corta explicitamente. En cambio la deuda neta negativa (caja neta)
si debe pasar: es una empresa sin deuda, y eso es bueno. Queda escrito para que
nadie lo "arregle" mas adelante.

**La cohorte del percentil.** El documento dice que los percentiles se calculan
dentro de cada mercado y que la puntuacion se calcula entre las que pasan el
filtro. Si la cohorte fuesen solo las aprobadas, un mercado con dos aprobadas
produciria un 0 y un 100, y esa segunda empresa —mediocre en terminos absolutos—
competiria de tu a tu con la mejor de un mercado bien cribado. Por eso la
cohorte por defecto es el universo elegible del mercado y la puntuacion se emite
solo para las aprobadas; se puede volver al otro criterio desde
`fundamental.cohorte_percentiles`.

Ademas se usan posiciones de trazado de Hazen, `(rango - 0.5) / n`, en lugar de
`(rango - 1) / (n - 1)`. Con Hazen, una cohorte de uno da 50 y una de dos da 25
y 75, en vez de 0 y 100: el percentil deja de afirmar una certeza que la muestra
no sostiene.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import Config
from .tipos import CohorteUsada, MotivoRechazo, PuntuacionFundamental


@dataclass(frozen=True, slots=True)
class Ratios:
    """Los ratios que necesita el filtro, ya calculados y con su validez."""

    ticker: str
    roe: float | None
    margen_operativo: float | None
    crecimiento_ventas_3a: float | None
    flujo_caja_libre: float | None
    deuda_neta_ebitda: float | None
    ev_ebit: float | None
    fin_periodo: date
    fecha_publicacion: date
    origen_pit: str
    motivo_invalidez: MotivoRechazo | None = None
    # Por que no se ha podido calcular el EV, cuando no se ha podido. Lo usa el
    # diagnostico: una cartera entera sin EV significa media puntuacion muerta.
    motivo_sin_ev: str | None = None


def percentiles_hazen(valores: pd.Series) -> pd.Series:
    """Percentil 0-100 con posiciones de trazado de Hazen.

    Los empates comparten el rango medio, para que dos empresas identicas
    reciban la misma nota.
    """
    n = len(valores)
    if n == 0:
        return pd.Series(dtype=float)
    rangos = valores.rank(method="average", ascending=True)
    return (rangos - 0.5) / n * 100.0


def valor_empresa(
    ultimo: pd.Series, precio_local: float | None
) -> tuple[float | None, str | None]:
    """EV en la fecha de decision, y el motivo si no se ha podido calcular.

    El EV no es un dato del ejercicio. El EBIT es anual y mira hacia atras, pero
    la valoracion tiene que reflejar el precio de HOY, asi que se calcula cada
    vez a partir de las acciones en circulacion a cierre del ultimo periodo
    publicado —que es un dato puntual, del balance— y del precio del dia:

        EV = acciones x precio_local + deuda_neta

    Sin precio se usa el EV almacenado, que es lo que da el proveedor sintetico.

    La comprobacion de divisas no es un detalle: los estados financieros vienen
    en la divisa en que REPORTA la empresa, que no siempre es la de su
    cotizacion. Multiplicar acciones por un precio en otra divisa da un EV sin
    ningun sentido y convierte a una empresa normal en baratisima o carisima
    segun el par. Cuando no coinciden, no hay EV.
    """
    almacenado = _num(ultimo.get("ev"))
    if precio_local is None:
        return (almacenado, None if almacenado else "sin_ev_almacenado")

    acciones = _num(ultimo.get("acciones_en_circulacion"))
    if acciones is None or acciones <= 0:
        if almacenado:
            return almacenado, None
        return None, "sin_acciones_en_circulacion"

    reporte = ultimo.get("divisa_reporte")
    cotizacion = ultimo.get("divisa_cotizacion")
    if reporte and cotizacion and str(reporte) != str(cotizacion):
        return None, f"divisas_distintas:{reporte}/{cotizacion}"

    deuda_neta = _num(ultimo.get("deuda_neta")) or 0.0
    ev = acciones * precio_local + deuda_neta
    return (ev if ev > 0 else None), (None if ev > 0 else "ev_no_positivo")


def ratios_de(
    ticker: str,
    fundamentales: pd.DataFrame,
    cfg: Config,
    fecha: date,
    precio_local: float | None = None,
) -> Ratios | None:
    """Ratios del ultimo ejercicio publicado, con las trampas de signo cortadas.

    `precio_local` es el precio de la fecha de decision. Si se pasa, el EV se
    calcula con el; si no, se usa el que venga almacenado.
    """
    if fundamentales.empty:
        return None
    anuales = fundamentales[fundamentales["periodo"] == "anual"]
    if anuales.empty:
        return None

    ultimo = anuales.iloc[-1]
    fin_periodo = ultimo["fin_periodo"]
    publicacion = ultimo["fecha_publicacion"]

    base = dict(
        ticker=ticker,
        fin_periodo=fin_periodo,
        fecha_publicacion=publicacion,
        origen_pit=str(ultimo.get("origen_pit", "reconstruido")),
    )

    # Un dato demasiado viejo no dice nada del presente. Se falla hacia el lado
    # prudente: la empresa deja de pasar el filtro en vez de arrastrar cifras
    # de hace tres anos como si fueran actuales.
    if (fecha - publicacion).days > cfg.reglas.fundamental.antiguedad_maxima_dias:
        return Ratios(
            roe=None, margen_operativo=None, crecimiento_ventas_3a=None,
            flujo_caja_libre=None, deuda_neta_ebitda=None, ev_ebit=None,
            motivo_invalidez=MotivoRechazo.FUNDAMENTAL_CADUCADO, **base,
        )

    patrimonio = _num(ultimo.get("patrimonio_neto"))
    ebit = _num(ultimo.get("ebit"))
    ebitda = _num(ultimo.get("ebitda"))
    ev, motivo_sin_ev = valor_empresa(ultimo, precio_local)
    ventas = _num(ultimo.get("ventas"))
    deuda_neta = _num(ultimo.get("deuda_neta"))

    # Trampa 1: patrimonio negativo hace positivo un ROE de perdidas.
    roe = _num(ultimo.get("roe"))
    if patrimonio is not None and patrimonio <= 0:
        roe = None

    margen = _num(ultimo.get("margen_operativo"))
    if margen is None and ventas and ebit is not None and ventas > 0:
        margen = ebit / ventas

    # Trampa 2: EBITDA negativo invierte el ratio de deuda.
    deuda_ebitda: float | None = None
    if ebitda is not None and ebitda > 0 and deuda_neta is not None:
        # Caja neta (deuda negativa) sale negativa y debe pasar: es correcto.
        deuda_ebitda = deuda_neta / ebitda

    # Trampa 3: EBIT negativo haria "baratisima" a la empresa.
    ev_ebit: float | None = None
    if ebit is not None and ebit > 0 and ev is not None and ev > 0:
        ev_ebit = ev / ebit

    crecimiento = _crecimiento_ventas(anuales)

    return Ratios(
        roe=roe,
        margen_operativo=margen,
        crecimiento_ventas_3a=crecimiento,
        flujo_caja_libre=_num(ultimo.get("flujo_caja_libre")),
        deuda_neta_ebitda=deuda_ebitda,
        ev_ebit=ev_ebit,
        motivo_sin_ev=motivo_sin_ev if ev_ebit is None else None,
        **base,
    )


def _crecimiento_ventas(anuales: pd.DataFrame) -> float | None:
    """Crecimiento anual compuesto de ventas a tres anos.

    Con el proveedor gratuito suele haber cuatro ejercicios, asi que sale
    exactamente una observacion por empresa y practicamente no varia a lo largo
    del backtest. El informe lo advierte: este filtro es casi estatico.
    """
    if len(anuales) < 4:
        return None
    reciente = _num(anuales.iloc[-1].get("ventas"))
    antigua = _num(anuales.iloc[-4].get("ventas"))
    if not reciente or not antigua or antigua <= 0 or reciente <= 0:
        return None
    return (reciente / antigua) ** (1.0 / 3.0) - 1.0


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if (np.isnan(f) or np.isinf(f)) else f


def aprueba_minimos(ratios: Ratios, sector: str, cfg: Config) -> tuple[bool, MotivoRechazo | None]:
    """Si la empresa cumple todos los minimos de su sector.

    Todas las comparaciones son `>=`, salvo el flujo de caja libre, que el
    documento pide estrictamente positivo. Un ratio que no se ha podido calcular
    NO pasa: sin el dato no hay forma de afirmar que cumple.
    """
    if ratios.motivo_invalidez is not None:
        return False, ratios.motivo_invalidez

    minimos = cfg.reglas.fundamental.minimos_para(sector)

    if ratios.roe is None or ratios.margen_operativo is None:
        return False, MotivoRechazo.SIN_DATO_FUNDAMENTAL
    if ratios.crecimiento_ventas_3a is None or ratios.deuda_neta_ebitda is None:
        return False, MotivoRechazo.SIN_DATO_FUNDAMENTAL
    if ratios.flujo_caja_libre is None:
        return False, MotivoRechazo.SIN_DATO_FUNDAMENTAL

    if ratios.roe < minimos.roe:
        return False, MotivoRechazo.FALLA_FUNDAMENTAL
    if ratios.margen_operativo < minimos.margen_operativo:
        return False, MotivoRechazo.FALLA_FUNDAMENTAL
    if ratios.crecimiento_ventas_3a < minimos.crecimiento_ventas_3a:
        return False, MotivoRechazo.FALLA_FUNDAMENTAL
    if minimos.flujo_caja_libre_positivo and ratios.flujo_caja_libre <= 0:
        return False, MotivoRechazo.FALLA_FUNDAMENTAL
    if ratios.deuda_neta_ebitda > minimos.deuda_neta_ebitda_max:
        return False, MotivoRechazo.FALLA_FUNDAMENTAL
    return True, None


def puntuar(
    elegibles: dict[str, tuple[Ratios, str, str]],
    cfg: Config,
) -> dict[str, PuntuacionFundamental]:
    """Puntua a las empresas elegibles, percentilando dentro de cada mercado.

    `elegibles` mapea ticker -> (ratios, mercado, sector).
    """
    fcfg = cfg.reglas.fundamental
    if not elegibles:
        return {}

    filas = []
    for ticker, (ratios, mercado, sector) in elegibles.items():
        aprueba, motivo = aprueba_minimos(ratios, sector, cfg)
        filas.append(
            {
                "ticker": ticker,
                "mercado": mercado,
                "sector": sector,
                "bloque": cfg.reglas.mercado(mercado).clasificacion,
                "aprueba": aprueba,
                "motivo": motivo,
                "roe": ratios.roe,
                "margen": ratios.margen_operativo,
                "ev_ebit": ratios.ev_ebit,
            }
        )
    df = pd.DataFrame(filas)

    # La cohorte decide cuanta gente hay en la foto contra la que se compara.
    if fcfg.cohorte_percentiles == "solo_aprobadas":
        base = df[df["aprueba"]]
    else:
        base = df

    salida: dict[str, PuntuacionFundamental] = {}
    for mercado, grupo_mercado in base.groupby("mercado", sort=True):
        n = len(grupo_mercado)
        if n >= fcfg.min_empresas_percentil:
            cohorte, usada = grupo_mercado, CohorteUsada.MERCADO
        else:
            # Demasiado poca gente para que el percentil signifique algo. Se
            # amplia al bloque (desarrollado/emergente) en lugar de excluir el
            # mercado, porque excluirlo crearia un sesgo por tamano de mercado
            # correlacionado justo con la distincion que al documento le importa.
            bloque = cfg.reglas.mercado(mercado).clasificacion
            cohorte = base[base["bloque"] == bloque]
            usada = (
                CohorteUsada.BLOQUE
                if len(cohorte) >= fcfg.min_empresas_percentil
                else CohorteUsada.INSUFICIENTE
            )

        pct_roe = percentiles_hazen(cohorte["roe"].astype(float))
        pct_margen = percentiles_hazen(cohorte["margen"].astype(float))
        # Percentil inverso: cuanto menor EV/EBIT, mejor nota.
        pct_val = 100.0 - percentiles_hazen(cohorte["ev_ebit"].astype(float))

        for idx, fila in grupo_mercado.iterrows():
            ticker = fila["ticker"]
            if not fila["aprueba"]:
                salida[ticker] = PuntuacionFundamental(
                    ticker=ticker, mercado=mercado, sector=fila["sector"],
                    aprueba=False, calidad=None, valoracion=None, puntuacion=None,
                    n_cohorte=len(cohorte), cohorte_usada=usada, motivo=fila["motivo"],
                )
                continue

            calidad_partes = [p for p in (pct_roe.get(idx), pct_margen.get(idx)) if _ok(p)]
            calidad = float(np.mean(calidad_partes)) if calidad_partes else 50.0
            v = pct_val.get(idx)
            # Sin EV/EBIT utilizable (EBIT negativo, por ejemplo) la valoracion
            # se puntua en el peor percentil, no en uno neutro: no saber si
            # esta barata no es lo mismo que estar barata.
            valoracion = float(v) if _ok(v) else 0.0

            puntuacion = (
                fcfg.puntuacion.peso_calidad * calidad
                + fcfg.puntuacion.peso_valoracion * valoracion
            )
            salida[ticker] = PuntuacionFundamental(
                ticker=ticker, mercado=mercado, sector=fila["sector"], aprueba=True,
                calidad=calidad, valoracion=valoracion, puntuacion=puntuacion,
                n_cohorte=len(cohorte), cohorte_usada=usada,
            )
    return salida


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and np.isnan(v))


def sigue_aprobando(
    ticker: str,
    sector: str,
    fecha: date,
    vista,
    cfg: Config,
    precio_local: float | None = None,
) -> bool:
    """Si una empresa en cartera sigue pasando el filtro.

    El documento habla de re-evaluar "tras publicar resultados". Aqui se
    re-evalua en cada revision semanal con el ultimo dato conocido a esa fecha,
    que es mas simple, mas frecuente y da el mismo resultado salvo en la semana
    exacta de la publicacion. Queda anotado porque es mas estricto que la letra.
    """
    if not cfg.reglas.fundamental.activo:
        return True
    ratios = ratios_de(ticker, vista.fundamentales(ticker), cfg, fecha, precio_local)
    if ratios is None:
        return False
    aprueba, _ = aprueba_minimos(ratios, sector, cfg)
    return aprueba
