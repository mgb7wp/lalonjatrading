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
            raise ErrorDatos(
                f"los datos no cumplen el contrato de fuentes:\n{lineas}"
            )


def _faltan_columnas(df: pd.DataFrame, esperadas: list[str]) -> list[str]:
    return [c for c in esperadas if c not in df.columns]


def _columnas_vacias(df: pd.DataFrame, columnas: list[str]) -> list[str]:
    vacias = []
    for col in columnas:
        if col in df.columns and df[col].isna().all():
            vacias.append(col)
    return vacias


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

    # Coherencia OHLC. Un OHLC incoherente hace que la logica de stops produzca
    # disparates que parecen fallos de la estrategia y no de los datos.
    completas = df.dropna(subset=["apertura", "maximo", "minimo", "cierre"])
    if not completas.empty:
        peor_min = completas[["apertura", "cierre"]].min(axis=1)
        mejor_max = completas[["apertura", "cierre"]].max(axis=1)
        malas = completas[
            (completas["minimo"] > peor_min + 1e-9)
            | (completas["maximo"] < mejor_max - 1e-9)
        ]
        if not malas.empty:
            ejemplo = malas.iloc[0]
            falla(
                "OHLC incoherente",
                f"{len(malas)} filas; p. ej. {ejemplo['ticker']} el "
                f"{ejemplo['fecha']}: minimo {ejemplo['minimo']:.4f}, "
                f"maximo {ejemplo['maximo']:.4f}",
            )

    duplicadas = df.duplicated(subset=["ticker", "fecha"]).sum()
    if duplicadas:
        falla("fechas repetidas para un mismo ticker", f"{duplicadas} filas")

    return inf


def verificar_fundamentales(df: pd.DataFrame, fuente: str) -> Informe:
    """Comprueba un lote de fundamentales."""
    inf = Informe()

    def falla(problema: str, detalle: str = "") -> None:
        inf.incumplimientos.append(
            Incumplimiento(fuente, "fundamentales", problema, detalle)
        )

    if df.empty:
        falla("no ha devuelto ni una fila de fundamentales")
        return inf

    faltan = _faltan_columnas(df, COLUMNAS_FUNDAMENTALES)
    if faltan:
        falla("faltan columnas", ", ".join(faltan))
        return inf

    vacias = _columnas_vacias(df, FUNDAMENTALES_NO_VACIAS)
    if vacias:
        falla(
            "columnas obligatorias enteras a nulo",
            f"{', '.join(vacias)} - suele ser un mapeo roto, no datos que falten",
        )

    # La comprobacion que habria cazado el fallo del EV.
    for grupo in FUNDAMENTALES_AL_MENOS_UNA:
        presentes = [c for c in grupo if c in df.columns]
        if presentes and all(df[c].isna().all() for c in presentes):
            falla(
                "ninguna de estas columnas trae dato y hace falta al menos una",
                f"{' o '.join(grupo)} - sin ninguna de las dos no hay EV/EBIT y "
                f"la valoracion puntua cero para todas las empresas",
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


def verificar_fx(df: pd.DataFrame, fuente: str) -> Informe:
    """Comprueba un lote de tipos de cambio."""
    inf = Informe()

    def falla(problema: str, detalle: str = "") -> None:
        inf.incumplimientos.append(Incumplimiento(fuente, "divisas", problema, detalle))

    if df.empty:
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

    return inf
