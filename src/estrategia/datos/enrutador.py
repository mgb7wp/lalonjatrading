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

Y una tercera, solo para precios y divisas: **el respaldo**. Los cinco mercados
cuelgan de la misma fuente, asi que si cae no cae un mercado, caen los cinco. Si
la duena falla —excepcion, lote vacio o contrato incumplido— o deja tickers sin
servir, lo que falta se pide a las fuentes de `implementacion.yaml`
(`respaldos`), por orden. La unidad es la serie entera: un ticker sale de una
sola fuente, nunca media serie de una y media de otra, porque cada proveedor
ajusta a su manera y la costura seria un hueco inventado. Todo lo que pasa queda
en `incidencias`, y cada fila sigue diciendo de donde salio.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

import pandas as pd

from ..config import Config
from ..errores import ErrorConfiguracion, ErrorDatos
from . import contrato, registro
from .proveedor import COLUMNAS_FX, TIPOS_DE_DATO, Capacidades, Fuente


class Enrutador:
    """Reparte cada peticion a la fuente que corresponde."""

    def __init__(self, cfg: Config, verificar: bool = True) -> None:
        self._cfg = cfg
        self._verificar = verificar
        self._instancias: dict[str, Fuente] = {}
        self._por_tipo: dict[str, str] = {
            tipo: cfg.reglas.proveedor_datos.fuente_de(tipo) for tipo in TIPOS_DE_DATO
        }
        #: Lo que ha pasado durante la descarga y conviene que alguien lea:
        #: fuentes que han fallado, respaldos usados, tickers sin servir.
        self.incidencias: list[str] = []
        self._servidas: set[str] = set()

    # -- resolucion --------------------------------------------------------

    def nombre_de(self, tipo: str) -> str:
        return self._por_tipo[tipo]

    @property
    def reparto(self) -> dict[str, str]:
        return dict(self._por_tipo)

    @property
    def fuentes_usadas(self) -> list[str]:
        return sorted(set(self._por_tipo.values()))

    @property
    def fuentes_servidas(self) -> list[str]:
        """Las fuentes que de verdad han dado datos, respaldos incluidos.

        No es lo mismo que `fuentes_usadas`: si la principal cae y el respaldo
        sirve todo, el origen honesto de la descarga es el respaldo.
        """
        return sorted(self._servidas)

    def respaldos_de(self, tipo: str) -> list[str]:
        principal = self._por_tipo[tipo]
        return [n for n in self._cfg.implementacion.respaldos_de(tipo) if n != principal]

    def fuente(self, tipo: str) -> Fuente:
        """La fuente dueña de un tipo de dato, ya construida."""
        if tipo not in TIPOS_DE_DATO:
            raise ErrorConfiguracion(f"tipo de dato desconocido: {tipo!r}")
        return self._construir(self._por_tipo[tipo], tipo)

    def _construir(self, nombre: str, tipo: str) -> Fuente:
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

    def respaldos_no_disponibles(self) -> list[str]:
        """Respaldos que no se podrian usar si hicieran falta.

        No impiden arrancar —la principal puede ir bien—, pero conviene saberlo
        antes y no el dia que cae la principal.
        """
        avisos: list[str] = []
        for tipo in TIPOS_DE_DATO:
            for nombre in self.respaldos_de(tipo):
                ok, motivo = self._construir(nombre, tipo).disponible()
                if not ok:
                    avisos.append(f"respaldo de {tipo} {nombre}: {motivo}")
        return avisos

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
        return self._con_respaldo(
            "precios",
            list(dict.fromkeys(tickers)),
            "ticker",
            lambda fuente, faltan: fuente.precios(faltan, inicio, fin),
            contrato.verificar_precios,
        )

    def fundamentales(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        fuente = self.fuente("fundamentales")
        df = fuente.fundamentales(tickers, inicio, fin)
        df = _estampar(df, fuente.nombre)
        if self._verificar:
            contrato.verificar_fundamentales(df, fuente.nombre).exigir()
        return df

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        # Solo se esperan las que necesitan cruce: la divisa base no viene nunca.
        base = self._cfg.reglas.cartera.divisa_base
        pares = self._cfg.implementacion.divisas
        necesarias = [d for d in dict.fromkeys(divisas) if d != base and pares.get(d)]
        if not necesarias:
            # Una cartera enteramente en divisa base no necesita tipos de cambio.
            return pd.DataFrame(columns=COLUMNAS_FX + ["fuente"])
        return self._con_respaldo(
            "divisas",
            necesarias,
            "divisa",
            lambda fuente, faltan: fuente.fx(faltan, inicio, fin),
            contrato.verificar_fx,
        )

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        return self.fuente("sectores").sectores(tickers)

    # -- respaldo ----------------------------------------------------------

    def _con_respaldo(
        self,
        tipo: str,
        claves: list[str],
        columna: str,
        pedir: Callable[[Fuente, list[str]], pd.DataFrame],
        verificar: Callable[[pd.DataFrame, str], contrato.Informe],
    ) -> pd.DataFrame:
        """Pide `claves` a la duena y lo que falte a los respaldos, por orden.

        Cada fuente recibe solo lo que las anteriores no han servido, y su lote
        pasa el contrato por separado, para que un incumplimiento se atribuya a
        quien lo cometio. Si al final nadie ha servido nada, se lanza con la
        lista entera de lo ocurrido.
        """
        principal = self._por_tipo[tipo]
        lotes: list[pd.DataFrame] = []
        fallos: list[str] = []
        faltan = list(claves)

        for nombre in [principal, *self.respaldos_de(tipo)]:
            if not faltan:
                break
            fuente = self._construir(nombre, tipo)
            ok, motivo = fuente.disponible()
            if not ok:
                fallos.append(f"{nombre} no disponible: {motivo}")
                continue
            try:
                df = pedir(fuente, faltan)
            except Exception as exc:  # noqa: BLE001 - cualquier fallo pasa al respaldo
                fallos.append(f"{nombre} ha fallado: {exc}")
                continue
            if df is None or df.empty or columna not in df.columns:
                fallos.append(f"{nombre} no ha devuelto nada")
                continue

            # Solo lo que se le pidio: el resto ya vino de una fuente anterior,
            # y una serie no se cose con trozos de dos proveedores.
            df = _estampar(df[df[columna].isin(faltan)], nombre)
            if df.empty:
                fallos.append(f"{nombre} no ha devuelto nada de lo pedido")
                continue
            if self._verificar:
                inf = verificar(df, nombre)
                if not inf.cumple:
                    detalle = "; ".join(str(i) for i in inf.incumplimientos)
                    fallos.append(
                        f"{nombre} no cumple el contrato, se descarta su lote: {detalle}"
                    )
                    continue

            servidas = set(df[columna].unique())
            if nombre != principal:
                self.incidencias.append(
                    f"{tipo}: {len(servidas)} de {len(claves)} servidos por el "
                    f"respaldo {nombre}"
                )
            lotes.append(df)
            self._servidas.add(nombre)
            faltan = [c for c in faltan if c not in servidas]

        self.incidencias.extend(f"{tipo}: {f}" for f in fallos)
        if not lotes:
            lineas = "\n".join(f"  - {f}" for f in fallos)
            raise ErrorDatos(
                f"ninguna fuente ha podido servir {tipo} "
                f"(principal {principal}, respaldos: "
                f"{', '.join(self.respaldos_de(tipo)) or 'ninguno'}). "
                f"Lo que ha pasado, contrato incluido:\n{lineas}"
            )
        if faltan:
            muestra = ", ".join(faltan[:10]) + (" ..." if len(faltan) > 10 else "")
            self.incidencias.append(f"{tipo}: sin datos de {len(faltan)}: {muestra}")
        return pd.concat(lotes, ignore_index=True)


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
