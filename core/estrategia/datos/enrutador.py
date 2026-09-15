"""Enrutador: quien sirve cada tipo de dato.

Cada tipo de dato tiene una fuente dueña, declarada en `reglas.yaml`:

```yaml
proveedor_datos:
  precios: yfinance
  fundamentales: eodhd
  divisas: yfinance
  sectores: eodhd
```

El reparto por especialidad es lo que escala: cuando entre una sexta fuente, la
decision es de que dato es dueña, no como se enchufa. Y cubre el caso que de
verdad importa en este proyecto, que es poder quedarse con los precios gratuitos
de yfinance y traer los fundamentales de una fuente con historico largo y fechas
de publicacion reales, que es la limitacion mas seria que tiene hoy el sistema.

Este modulo es el **unico sitio por el que pasan todos los datos**, y por eso
hace aqui dos cosas que no se pueden dejar a la buena voluntad de cada adaptador:

1. **Estampa la procedencia.** Cada fila sale con su columna `fuente`. Sin eso,
   en cuanto se mezclan origenes el backtest deja de ser reproducible y un numero
   raro no hay por donde cogerlo.
2. **Aplica el contrato.** Ningun lote entra en el almacen sin pasar por
   `contrato.py`. Es lo que convierte un mapeo roto en un error ruidoso en vez de
   en media puntuacion fundamental muerta en silencio.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..config import Config
from ..errores import ErrorConfiguracion
from . import contrato, registro
from .proveedor import TIPOS_DE_DATO, Capacidades, Fuente


class Enrutador:
    """Reparte cada peticion a la fuente que corresponde."""

    def __init__(self, cfg: Config, verificar: bool = True) -> None:
        self._cfg = cfg
        self._verificar = verificar
        self._instancias: dict[str, Fuente] = {}
        self._por_tipo: dict[str, str] = {
            tipo: cfg.reglas.proveedor_datos.fuente_de(tipo) for tipo in TIPOS_DE_DATO
        }

    # -- resolucion --------------------------------------------------------

    def nombre_de(self, tipo: str) -> str:
        return self._por_tipo[tipo]

    @property
    def reparto(self) -> dict[str, str]:
        return dict(self._por_tipo)

    @property
    def fuentes_usadas(self) -> list[str]:
        return sorted(set(self._por_tipo.values()))

    def fuente(self, tipo: str) -> Fuente:
        """La fuente dueña de un tipo de dato, ya construida."""
        if tipo not in TIPOS_DE_DATO:
            raise ErrorConfiguracion(f"tipo de dato desconocido: {tipo!r}")
        nombre = self._por_tipo[tipo]
        if nombre not in self._instancias:
            self._instancias[nombre] = registro.crear(nombre, self._cfg)
        fuente = self._instancias[nombre]

        if not fuente.capacidades.sirve(tipo):
            raise ErrorConfiguracion(
                f"la fuente '{nombre}' esta asignada a '{tipo}' pero declara que "
                f"solo sirve {', '.join(fuente.capacidades.tipos)}"
            )
        return fuente

    def capacidades(self) -> dict[str, Capacidades]:
        """Capacidades de cada fuente en uso, para que el informe avise solo."""
        salida: dict[str, Capacidades] = {}
        for tipo in TIPOS_DE_DATO:
            nombre = self._por_tipo[tipo]
            if nombre not in salida:
                salida[nombre] = self.fuente(tipo).capacidades
        return salida

    def comprobar_disponibilidad(self) -> list[str]:
        """Problemas que impedirian usar alguna fuente, antes de empezar.

        Que falte una clave de API debe ser un mensaje claro al arrancar y no un
        error a mitad de una descarga de media hora.
        """
        problemas: list[str] = []
        for nombre in self.fuentes_usadas:
            fuente = registro.crear(nombre, self._cfg)
            self._instancias.setdefault(nombre, fuente)
            ok, motivo = fuente.disponible()
            if not ok:
                problemas.append(f"{nombre}: {motivo}")
        return problemas

    # -- datos -------------------------------------------------------------

    def precios(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        fuente = self.fuente("precios")
        df = fuente.precios(tickers, inicio, fin)
        df = _estampar(df, fuente.nombre)
        if self._verificar:
            contrato.verificar_precios(df, fuente.nombre).exigir()
        return df

    def fundamentales(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        fuente = self.fuente("fundamentales")
        df = fuente.fundamentales(tickers, inicio, fin)
        df = _estampar(df, fuente.nombre)
        if self._verificar:
            contrato.verificar_fundamentales(df, fuente.nombre).exigir()
        return df

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        fuente = self.fuente("divisas")
        df = fuente.fx(divisas, inicio, fin)
        df = _estampar(df, fuente.nombre)
        if self._verificar:
            contrato.verificar_fx(df, fuente.nombre).exigir()
        return df

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        return self.fuente("sectores").sectores(tickers)


def _estampar(df: pd.DataFrame, nombre: str) -> pd.DataFrame:
    """Marca cada fila con la fuente de la que salio.

    Se respeta lo que ya venga puesto: un adaptador que agregue varias fuentes
    por dentro sabe mejor que nadie de donde sale cada fila.
    """
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    if "fuente" in df.columns and df["fuente"].notna().all():
        return df
    df = df.copy()
    df["fuente"] = nombre
    return df
