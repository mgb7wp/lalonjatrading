"""Contrato que toda fuente debe cumplir antes de que sus datos entren.

Esto no es burocracia. El fallo que motivo este modulo es real y estuvo en el
repositorio: el proveedor de yfinance devolvia la columna `ev` entera a nulo
—con un comentario que decia que se completaria mas adelante y que nadie
completo— y el efecto era que la valoracion puntuaba cero para todas las
empresas y **la mitad del peso de la puntuacion fundamental dejaba de hacer
nada**. Ni se caia nada ni salia ningun aviso: el ranking simplemente pasaba a
decidirse solo por calidad.

La leccion no es "revisar mejor", es que una fuente puede cumplir la forma del
contrato y no su fondo. De ahi la comprobacion que mas valor da de todas:
**ninguna columna obligatoria puede venir entera a nulo**. Un hueco suelto es un
dato que falta, cosa normal; una columna entera vacia es un mapeo roto.

Cada fuente nueva traera fallos de esta misma familia, con otro nombre. Por eso
el contrato se aplica en el enrutador, en el unico sitio por el que pasan todos
los datos, y no depende de que quien escriba el adaptador se acuerde.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from ..errores import ErrorDatos
from .proveedor import COLUMNAS_FUNDAMENTALES, COLUMNAS_FX, COLUMNAS_PRECIOS

#: Columnas de precios que no pueden venir enteras a nulo.
PRECIOS_NO_VACIAS = ["apertura", "maximo", "minimo", "cierre", "volumen"]

#: Igual para fundamentales. `flujo_caja_libre` no esta porque hay fuentes que
#: legitimamente no lo dan y el filtro ya sabe rechazar a quien le falte.
FUNDAMENTALES_NO_VACIAS = [
    "roe",
    "margen_operativo",
    "ventas",
    "ebit",
    "ebitda",
    "deuda_neta",
    "patrimonio_neto",
]

#: Grupos donde basta con que UNA de las columnas sirva. El EV se puede dar
#: hecho o se puede calcular a partir de las acciones en circulacion; lo que no
#: vale es que no haya ninguno de los dos caminos, que es justo el fallo que
#: paso desapercibido.
FUNDAMENTALES_AL_MENOS_UNA = [("ev", "acciones_en_circulacion")]

#: Valores distintos que debe traer un lote para que "columna entera a nulo"
#: signifique algo. Por debajo, una columna vacia es indistinguible de una
#: empresa que no publica esa magnitud, y exigirla convierte la consulta de un
#: valor suelto en un error que no lo es.
MINIMO_PARA_EXIGIR_COLUMNA = 5


@dataclass
class Incumplimiento:
    """Un problema concreto encontrado en los datos de una fuente."""

    fuente: str
    tipo_dato: str
    problema: str
    detalle: str = ""

    def __str__(self) -> str:
        cola = f" ({self.detalle})" if self.detalle else ""
        return f"[{self.fuente}/{self.tipo_dato}] {self.problema}{cola}"


@dataclass
class Informe:
    """Resultado de verificar un lote de datos."""

    incumplimientos: list[Incumplimiento] = field(default_factory=list)

    @property
    def cumple(self) -> bool:
        return not self.incumplimientos

    def exigir(self) -> None:
        """Lanza si algo no cumple, con todos los problemas de una vez.

        De una vez y no uno a uno: al conectar una fuente nueva interesa la lista
        entera para arreglarla de una pasada, no ir descubriendolos de uno en uno
        a base de reejecutar.
        """
        if self.incumplimientos:
            lineas = "\n".join(f"  - {i}" for i in self.incumplimientos)
            raise ErrorDatos(f"los datos no cumplen el contrato de fuentes:\n{lineas}")


#: Fraccion de filas corruptas por encima de la cual el problema deja de ser
#: "un proveedor con ruido" y pasa a ser "este lote no sirve".
FRACCION_MAXIMA_CORRUPTA = 0.001


def filas_ohlc_incoherentes(df: pd.DataFrame) -> pd.Series:
    """Filas donde el minimo esta por encima del cierre, o el maximo por debajo.

    Es imposible por definicion, asi que cuando aparece es ruido del proveedor.
    """
    completas = df[["apertura", "maximo", "minimo", "cierre"]].notna().all(axis=1)
    peor = df[["apertura", "cierre"]].min(axis=1)
    mejor = df[["apertura", "cierre"]].max(axis=1)
    return completas & ((df["minimo"] > peor + 1e-9) | (df["maximo"] < mejor - 1e-9))


def sanear_precios(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Quita las filas imposibles y dice cuantas eran.

    Un lote de 250.000 precios con cinco filas corruptas de hace once anos no es
    un mapeo roto: es un proveedor gratuito con ruido. Rechazarlo entero deja un
    mercado sin datos por un problema que afecta al 0,002 % de las filas, y eso
    es desproporcionado.

    Asi que las filas imposibles se descartan y se cuentan, y el contrato
    verifica lo que queda. Lo que sigue siendo un incumplimiento es que sean
    MUCHAS: ahi ya no es ruido, es que el lote no sirve.
    """
    if df.empty:
        return df, 0
    malas = filas_ohlc_incoherentes(df)
    n = int(malas.sum())
    return (df[~malas].reset_index(drop=True), n) if n else (df, 0)



def verificar_descartes(descartadas: int, total: int, fuente: str) -> Informe:
    """Rechaza el lote si `sanear_precios` tuvo que descartar demasiadas filas.

    Unas pocas filas imposibles son ruido; muchas son un lote que no sirve. Se
    mide sobre lo que habia ANTES de descartar, porque despues ya no queda
    ninguna fila mala que contar.
    """
    inf = Informe()
    if total and descartadas / total > FRACCION_MAXIMA_CORRUPTA:
        inf.incumplimientos.append(
            Incumplimiento(
                fuente,
                "precios",
                "demasiadas filas con OHLC incoherente",
                f"{descartadas} de {total} filas ({descartadas / total:.2%}) descartadas",
            )
        )
    return inf

def _faltan_columnas(df: pd.DataFrame, esperadas: list[str]) -> list[str]:
    return [c for c in esperadas if c not in df.columns]


def _columnas_vacias(df: pd.DataFrame, columnas: list[str]) -> list[str]:
    vacias = []
    for col in columnas:
        if col in df.columns and df[col].isna().all():
            vacias.append(col)
    return vacias


@dataclass
class Limpieza:
    """Lo que `limpiar_precios` ha tenido que tocar, para contarlo."""

    sin_cierre: int = 0
    precios_negativos: int = 0
    sesion_en_curso: int = 0
    duplicadas: int = 0
    ohlc_reparadas: int = 0
    ohlc_rellenadas: int = 0
    ejemplos: list[str] = field(default_factory=list)

    @property
    def apartadas(self) -> int:
        return self.sin_cierre + self.precios_negativos + self.sesion_en_curso + self.duplicadas

    @property
    def total(self) -> int:
        return self.apartadas + self.ohlc_reparadas + self.ohlc_rellenadas

    def avisos(self, fuente: str, tipo_dato: str = "precios") -> list[str]:
        """Una linea por cosa tocada, para imprimirla al descargar."""
        cola = f" (p. ej. {'; '.join(self.ejemplos[:3])})" if self.ejemplos else ""
        partes = [
            (self.sin_cierre, "filas sin cierre apartadas"),
            (self.precios_negativos, "filas con precios negativos o cero apartadas"),
            (self.sesion_en_curso, "filas de la sesion en curso apartadas (aun no ha cerrado)"),
            (self.duplicadas, "filas con fecha repetida apartadas (se queda la ultima)"),
            (self.ohlc_reparadas, "filas con OHLC incoherente reparadas (maximo y minimo "
                                  "recalculados con apertura y cierre)"),
            (self.ohlc_rellenadas, "filas sin apertura, maximo o minimo rellenadas con "
                                   "el cierre"),
        ]
        return [f"[{fuente}/{tipo_dato}] {n} {texto}{cola}" for n, texto in partes if n]


def limpiar_precios(
    df: pd.DataFrame, hoy: date | None = None
) -> tuple[pd.DataFrame, Limpieza]:
    """Repara o aparta las filas malas en lugar de rechazar todo el lote.

    Con 140 valores, Yahoo devuelve casi siempre alguna fila rara: una fecha
    repetida, un minimo por encima del cierre, una sesion sin cierre. Antes una
    sola de esas filas tumbaba la descarga entera. Ahora:

    - Se APARTAN las filas que no se pueden arreglar sin inventar: sin cierre,
      con precios negativos o cero, y las de la sesion en curso (`hoy` o
      posterior), que todavia no ha cerrado y cuyo "cierre" es el ultimo precio
      del momento.
    - De una fecha repetida se queda la ultima fila que llego.
    - Se REPARAN las que tienen cierre pero un OHLC incoherente: el maximo pasa
      a ser el mayor de los cuatro precios y el minimo el menor. Si falta la
      apertura, el maximo o el minimo, se rellenan con el cierre.

    Todo se cuenta en la `Limpieza` devuelta, y el contrato se sigue aplicando
    despues: lo que no se ha podido arreglar sigue siendo un error.
    """
    info = Limpieza()
    if df is None or df.empty or any(c not in df.columns for c in COLUMNAS_PRECIOS):
        return df, info
    df = df.copy()
    ohlc = ["apertura", "maximo", "minimo", "cierre"]

    def ejemplo(filas: pd.DataFrame, que: str) -> None:
        if not filas.empty and len(info.ejemplos) < 5:
            f = filas.iloc[0]
            info.ejemplos.append(f"{f['ticker']} {f['fecha']}: {que}")

    fechas = pd.to_datetime(df["fecha"]).dt.date
    if hoy is not None:
        en_curso = fechas >= hoy
        info.sesion_en_curso = int(en_curso.sum())
        df, fechas = df[~en_curso], fechas[~en_curso]

    sin_cierre = df["cierre"].isna()
    info.sin_cierre = int(sin_cierre.sum())
    ejemplo(df[sin_cierre], "sin cierre")
    df = df[~sin_cierre]

    negativos = (df[ohlc] <= 0).any(axis=1)
    info.precios_negativos = int(negativos.sum())
    ejemplo(df[negativos], "precio negativo o cero")
    df = df[~negativos]

    repetidas = df.duplicated(subset=["ticker", "fecha"], keep="last")
    info.duplicadas = int(repetidas.sum())
    ejemplo(df[repetidas], "fecha repetida")
    df = df[~repetidas].copy()

    huecos = df[["apertura", "maximo", "minimo"]].isna().any(axis=1)
    info.ohlc_rellenadas = int(huecos.sum())
    ejemplo(df[huecos], "sin apertura, maximo o minimo")
    for col in ("apertura", "maximo", "minimo"):
        df[col] = df[col].fillna(df["cierre"])

    alto = df[ohlc].max(axis=1)
    bajo = df[ohlc].min(axis=1)
    incoherente = ~np.isclose(df["maximo"], alto) | ~np.isclose(df["minimo"], bajo)
    info.ohlc_reparadas = int(incoherente.sum())
    ejemplo(df[incoherente], "OHLC incoherente")
    df["maximo"] = alto
    df["minimo"] = bajo

    return df.reset_index(drop=True), info


def limpiar_fx(df: pd.DataFrame, hoy: date | None = None) -> tuple[pd.DataFrame, Limpieza]:
    """Lo mismo para los tipos de cambio: fuera la sesion en curso, las tasas
    sin valor o no positivas y las fechas repetidas (se queda la ultima)."""
    info = Limpieza()
    if df is None or df.empty or any(c not in df.columns for c in COLUMNAS_FX):
        return df, info
    df = df.copy()
    if hoy is not None:
        en_curso = pd.to_datetime(df["fecha"]).dt.date >= hoy
        info.sesion_en_curso = int(en_curso.sum())
        df = df[~en_curso]
    malas = df["tasa"].isna() | (df["tasa"] <= 0)
    info.sin_cierre = int(malas.sum())
    df = df[~malas]
    repetidas = df.duplicated(subset=["divisa", "fecha"], keep="last")
    info.duplicadas = int(repetidas.sum())
    return df[~repetidas].reset_index(drop=True), info


def verificar_precios(df: pd.DataFrame, fuente: str) -> Informe:
    """Comprueba un lote de precios."""
    inf = Informe()

    def falla(problema: str, detalle: str = "") -> None:
        inf.incumplimientos.append(Incumplimiento(fuente, "precios", problema, detalle))

    if df.empty:
        falla("no ha devuelto ni una fila de precios")
        return inf

    faltan = _faltan_columnas(df, COLUMNAS_PRECIOS)
    if faltan:
        falla("faltan columnas", ", ".join(faltan))
        return inf

    vacias = _columnas_vacias(df, PRECIOS_NO_VACIAS)
    if vacias:
        falla(
            "columnas obligatorias enteras a nulo",
            f"{', '.join(vacias)} - suele ser un mapeo roto, no datos que falten",
        )

    numericas = ["apertura", "maximo", "minimo", "cierre", "cierre_bruto", "volumen"]
    for col in numericas:
        if not pd.api.types.is_numeric_dtype(df[col]):
            falla("columna no numerica", col)

    if df[["apertura", "maximo", "minimo", "cierre"]].lt(0).any().any():
        falla("hay precios negativos")

    # Un OHLC incoherente hace que la logica de stops produzca disparates que
    # parecen fallos de la estrategia y no de los datos. Pero unas pocas filas
    # corruptas en un lote grande son ruido de un proveedor gratuito, no un
    # mapeo roto, y `sanear_precios` ya las habra quitado antes de llegar aqui.
    # Lo que se comprueba es que no sean tantas como para invalidar el lote.
    malas = df[filas_ohlc_incoherentes(df)]
    if not malas.empty:
        fraccion = len(malas) / len(df)
        ejemplo = malas.iloc[0]
        detalle = (
            f"{len(malas)} de {len(df)} filas ({fraccion:.2%}); p. ej. "
            f"{ejemplo['ticker']} el {ejemplo['fecha']}: minimo "
            f"{ejemplo['minimo']:.4f}, maximo {ejemplo['maximo']:.4f}"
        )
        if fraccion > FRACCION_MAXIMA_CORRUPTA:
            falla("demasiadas filas con OHLC incoherente", detalle)
        else:
            falla("OHLC incoherente", detalle)

    duplicadas = df.duplicated(subset=["ticker", "fecha"]).sum()
    if duplicadas:
        falla("fechas repetidas para un mismo ticker", f"{duplicadas} filas")

    return inf


def verificar_fundamentales(
    df: pd.DataFrame, fuente: str, magnitudes: tuple[str, ...] = ()
) -> Informe:
    """Comprueba un lote de fundamentales.

    `magnitudes` son las opcionales que la fuente DICE servir. Lo declarado se
    comprueba con el mismo rasero que lo obligatorio —una columna entera a nulo
    es un mapeo roto, no un dato que falta— y lo no declarado se deja pasar
    vacio. Sin esa distincion, ampliar el contrato obligaria a que todas las
    fuentes sirvieran todo, que es la via rapida para que nadie lo amplie nunca.
    """
    inf = Informe()

    def falla(problema: str, detalle: str = "") -> None:
        inf.incumplimientos.append(Incumplimiento(fuente, "fundamentales", problema, detalle))

    if df.empty:
        falla("no ha devuelto ni una fila de fundamentales")
        return inf

    faltan = _faltan_columnas(df, COLUMNAS_FUNDAMENTALES)
    if faltan:
        falla("faltan columnas", ", ".join(faltan))
        return inf

    # La comprobacion de "columna entera a nulo" solo significa algo sobre un
    # lote grande. Con una empresa o dos, una columna vacia no distingue un
    # mapeo roto de una empresa que legitimamente no publica esa magnitud:
    # McDonald's, por ejemplo, no declara GrossProfit en su XBRL.
    #
    # Sin este limite, la ficha de un valor —que pide un solo ticker— fallaria
    # por una razon que no es un error. El fallo que motivo esta comprobacion
    # era el de una descarga completa, y ahi se sigue aplicando entera.
    valores_distintos = df["ticker"].nunique()
    if valores_distintos >= MINIMO_PARA_EXIGIR_COLUMNA:
        vacias = _columnas_vacias(df, FUNDAMENTALES_NO_VACIAS)
        if vacias:
            falla(
                "columnas obligatorias enteras a nulo",
                f"{', '.join(vacias)} - suele ser un mapeo roto, no datos que falten",
            )

    # La comprobacion que habria cazado el fallo del EV.
    for grupo in (
        FUNDAMENTALES_AL_MENOS_UNA if valores_distintos >= MINIMO_PARA_EXIGIR_COLUMNA else []
    ):
        presentes = [c for c in grupo if c in df.columns]
        if presentes and all(df[c].isna().all() for c in presentes):
            falla(
                "ninguna de estas columnas trae dato y hace falta al menos una",
                f"{' o '.join(grupo)} - sin ninguna de las dos no hay EV/EBIT y "
                f"la valoracion puntua cero para todas las empresas",
            )

    declaradas_vacias = (
        _columnas_vacias(df, [m for m in magnitudes if m in df.columns])
        if valores_distintos >= MINIMO_PARA_EXIGIR_COLUMNA
        else []
    )
    if declaradas_vacias:
        falla(
            "columnas que la fuente dice servir y vienen enteras a nulo",
            f"{', '.join(declaradas_vacias)} - o el mapeo esta roto, o sobran de "
            f"`Capacidades.magnitudes`",
        )

    if df["fecha_publicacion"].isna().any():
        n = int(df["fecha_publicacion"].isna().sum())
        falla(
            "hay fundamentales sin fecha de publicacion",
            f"{n} filas - sin ella no se puede saber que se conocia en cada momento",
        )

    validos = {"capturado", "reconstruido"}
    desconocidos = set(df["origen_pit"].dropna().unique()) - validos
    if desconocidos:
        falla("valores de origen_pit desconocidos", ", ".join(sorted(desconocidos)))

    duplicadas = df.duplicated(subset=["ticker", "fin_periodo", "periodo"]).sum()
    if duplicadas:
        falla("periodos repetidos para un mismo ticker", f"{duplicadas} filas")

    return inf


def verificar_fx(
    df: pd.DataFrame,
    fuente: str,
    esperadas: list[str] | None = None,
    hasta: date | None = None,
    antiguedad_maxima_dias: int | None = None,
) -> Informe:
    """Comprueba un lote de tipos de cambio.

    Con `esperadas`, falta una divisa pedida es un error: un mercado sin cambio
    no se puede valorar ni dimensionar, y antes pasaba en silencio. Con `hasta`
    y `antiguedad_maxima_dias`, el ultimo cambio de cada divisa no puede ser
    mas viejo que ese limite: un par que dejo de actualizarse daria semanas de
    valoraciones con un cambio congelado.
    """
    inf = Informe()

    def falla(problema: str, detalle: str = "") -> None:
        inf.incumplimientos.append(Incumplimiento(fuente, "divisas", problema, detalle))

    if df.empty:
        if esperadas:
            falla("no ha llegado ningun tipo de cambio", ", ".join(sorted(esperadas)))
        # Una cartera enteramente en divisa base no necesita tipos de cambio.
        return inf

    faltan = _faltan_columnas(df, COLUMNAS_FX)
    if faltan:
        falla("faltan columnas", ", ".join(faltan))
        return inf

    if df["tasa"].isna().all():
        falla("la columna de tasas viene entera a nulo")
    elif (df["tasa"].dropna() <= 0).any():
        falla("hay tipos de cambio nulos o negativos")

    duplicadas = df.duplicated(subset=["divisa", "fecha"]).sum()
    if duplicadas:
        falla("fechas repetidas para una misma divisa", f"{duplicadas} filas")

    if esperadas:
        faltan = sorted(set(esperadas) - set(df["divisa"].dropna().unique()))
        if faltan:
            falla("faltan divisas", ", ".join(faltan))

    if hasta is not None and antiguedad_maxima_dias is not None:
        ultimas = pd.to_datetime(df["fecha"]).dt.date.groupby(df["divisa"]).max()
        viejas = [
            f"{d} (ultimo {u})" for d, u in ultimas.items()
            if (hasta - u).days > antiguedad_maxima_dias
        ]
        if viejas:
            falla(
                f"tipo de cambio con mas de {antiguedad_maxima_dias} dias de antiguedad",
                ", ".join(viejas),
            )

    return inf


def huecos_fx(df: pd.DataFrame, antiguedad_maxima_dias: int) -> list[str]:
    """Tramos del historico en que un cambio estuvo sin actualizarse mas dias
    que el limite. No es un error —el backtest arrastra el ultimo cambio—, pero
    se avisa: durante ese tramo la valoracion usa un cambio viejo."""
    if df is None or df.empty:
        return []
    avisos = []
    for divisa, grupo in df.groupby("divisa", sort=True):
        fechas = pd.Series(sorted(pd.to_datetime(grupo["fecha"]).dt.date))
        saltos = [
            (a, b) for a, b in zip(fechas[:-1], fechas[1:])
            if (b - a).days > antiguedad_maxima_dias
        ]
        if saltos:
            a, b = max(saltos, key=lambda s: (s[1] - s[0]).days)
            avisos.append(
                f"[divisas] {divisa}: {len(saltos)} tramos sin cotizacion de mas de "
                f"{antiguedad_maxima_dias} dias; el mayor, de {a} a {b}"
            )
    return avisos
