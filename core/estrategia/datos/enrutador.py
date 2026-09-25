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

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from ..config import Config
from ..errores import ErrorConfiguracion
from . import contrato, registro
from .proveedor import MAGNITUDES_OPCIONALES, TIPOS_DE_DATO, Capacidades, Fuente


@dataclass(frozen=True, slots=True)
class CalidadFundamental:
    """Con que calidad cubre una fuente los fundamentales de un mercado.

    `completa` significa point-in-time de verdad: fechas de publicacion reales y
    cifras sin reexpresar. Es lo unico sobre lo que se puede construir un
    backtest fundamental creible, y hoy solo lo dan la SEC y la CVM.
    """

    nivel: str  # completa | degradada | no_disponible
    fuente: str
    motivo: str
    anios: int | None = None

    @property
    def sirve_para_puntuar(self) -> bool:
        return self.nivel == "completa"


class Enrutador:
    """Reparte cada peticion a la fuente que corresponde."""

    def __init__(self, cfg: Config, verificar: bool = True, hoy: date | None = None) -> None:
        self._cfg = cfg
        self._verificar = verificar
        # Las filas con fecha `hoy` o posterior se apartan: la sesion todavia no
        # ha cerrado y su "cierre" es el ultimo precio del momento. Por defecto
        # es el dia de hoy. El pipeline programado, que descarga DESPUES del
        # cierre de cada mercado (y las divisas despues de que el BCE publique),
        # pasa el dia siguiente: si no, la plataforma iria siempre un dia por
        # detras.
        self._hoy = hoy or date.today()
        self._instancias: dict[str, Fuente] = {}
        #: Filas de precios imposibles descartadas en la ultima descarga.
        self.precios_descartados = 0
        #: Lo que se ha tenido que reparar o apartar en esta descarga. No son
        #: errores: el CLI lo imprime y la descarga sigue.
        self.avisos: list[str] = []
        self._por_tipo: dict[str, str] = {
            tipo: cfg.reglas.proveedor_datos.fuente_de(tipo) for tipo in TIPOS_DE_DATO
        }

    # -- resolucion --------------------------------------------------------

    def nombre_de(self, tipo: str, mercado: str | None = None) -> str:
        """El nombre de la fuente de un tipo de dato, en un mercado si se dice.

        Sin `mercado` devuelve el reparto global, y eso para los fundamentales
        es una respuesta equivocada: son el unico tipo que se reparte por
        mercado —la SEC solo cubre EE. UU. y la CVM solo Brasil—, asi que
        preguntar en global contestaba 'yfinance' para los cinco. El panel de
        `/health/data` lo estuvo publicando asi: decia que los fundamentales de
        EE. UU. venian de yfinance mientras el API servia los de la SEC, con
        `pit_origin = captured`. El sitio que existe para saber de donde sale
        cada cifra era el que peor la contaba.
        """
        if mercado is None:
            return self._por_tipo[tipo]
        return self._cfg.reglas.proveedor_datos.fuente_de(tipo, mercado)

    @property
    def reparto(self) -> dict[str, str]:
        return dict(self._por_tipo)

    @property
    def fuentes_usadas(self) -> list[str]:
        """Todas las fuentes del reparto, incluidas las de fundamentales por
        mercado (la SEC para EE. UU., la CVM para Brasil)."""
        nombres = set(self._por_tipo.values())
        nombres |= set(self._cfg.reglas.proveedor_datos.fundamentales_por_mercado.values())
        return sorted(nombres)

    @property
    def origen(self) -> str:
        """Nombre del reparto: `yfinance` si hay una sola fuente, o las fuentes
        unidas por `+` (`bce+cvm+sec+yfinance`) si se mezclan.

        Es el origen que queda anotado en la instantanea y tambien el nombre de
        su carpeta de cache, que es la que lista el panel.
        """
        return "+".join(self.fuentes_usadas)

    def _instancia(self, nombre: str) -> Fuente:
        """La fuente por su nombre, construida una sola vez.

        Cachear importa: algunas fuentes guardan en memoria lo que descargan
        —la ficha de la SEC sirve para fundamentales y para sectores, el fichero
        anual de la CVM sirve para las veintiocho empresas—, y reconstruirlas
        tira esa cache y multiplica las descargas.
        """
        if nombre not in self._instancias:
            self._instancias[nombre] = registro.crear(nombre, self._cfg)
        return self._instancias[nombre]

    def fuente(self, tipo: str) -> Fuente:
        """La fuente dueña de un tipo de dato, ya construida."""
        if tipo not in TIPOS_DE_DATO:
            raise ErrorConfiguracion(f"tipo de dato desconocido: {tipo!r}")
        fuente = self._instancia(self._por_tipo[tipo])
        nombre = fuente.nombre

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
        self._recoger_avisos(fuente)
        df = _estampar(df, fuente.nombre)
        # Primero se apartan la sesion en curso, las filas sin cierre, los
        # precios no positivos y las fechas repetidas, y se rellenan los huecos
        # de apertura, maximo y minimo con el cierre (`limpiar_precios`).
        df, limpieza = contrato.limpiar_precios(df, self._hoy)
        self.avisos += limpieza.avisos(fuente.nombre)
        # Despues, las filas con OHLC imposible se DESCARTAN, no se reparan: con
        # el maximo por debajo del cierre no hay forma de saber cual de los dos
        # precios es el bueno. Unas pocas son ruido de un proveedor gratuito;
        # `precios_descartados` queda para que el pipeline lo registre, y si son
        # demasiadas el contrato rechaza el lote.
        total = len(df)
        df, self.precios_descartados = contrato.sanear_precios(df)
        if self._verificar:
            informe = contrato.verificar_precios(df, fuente.nombre)
            informe.incumplimientos += contrato.verificar_descartes(
                self.precios_descartados, total, fuente.nombre
            ).incumplimientos
            informe.exigir()
        return df

    def fundamentales(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        """Fundamentales, pidiendo a cada mercado su fuente.

        Es el unico tipo de dato que se reparte por mercado, y con motivo: las
        unicas fuentes gratuitas con fechas de publicacion reales son
        nacionales. La SEC solo cubre EE. UU. y la CVM solo Brasil, asi que
        elegir una sola para todo el universo seria elegir que mercado se queda
        sin point-in-time.

        Cada lote se verifica por separado, con las capacidades de SU fuente: lo
        que la SEC promete no dice nada de lo que promete la CVM.
        """
        por_fuente: dict[str, list[str]] = {}
        for ticker in tickers:
            mercado = self._cfg.universo.mercado_de_ticker.get(ticker)
            nombre = self._cfg.reglas.proveedor_datos.fuente_de("fundamentales", mercado)
            por_fuente.setdefault(nombre, []).append(ticker)

        lotes: list[pd.DataFrame] = []
        for nombre, del_lote in por_fuente.items():
            fuente = self._instancia(nombre)
            df = fuente.fundamentales(del_lote, inicio, fin)
            self._recoger_avisos(fuente)
            df = _estampar(df, fuente.nombre)
            df = _completar_opcionales(df)
            if self._verificar and not df.empty:
                contrato.verificar_fundamentales(
                    df, fuente.nombre, fuente.capacidades.magnitudes
                ).exigir()
            if not df.empty:
                lotes.append(df)

        if not lotes:
            return pd.DataFrame()
        return pd.concat(lotes, ignore_index=True)

    def calidad_fundamental(self, mercado: str) -> CalidadFundamental:
        """Con que calidad tiene fundamentales un mercado.

        No es una pregunta de si o no, y tratarla como tal es el error que
        importa. yfinance devuelve fundamentales de los cinco mercados, asi que
        "disponible" diria que si en todos; lo que cambia es que en EE. UU. y
        Brasil son las cifras de su momento con la fecha en que se publicaron, y
        en el resto son cuatro ejercicios reexpresados a hoy con la fecha
        estimada por un retraso fijo. Sobre lo segundo no se puede construir un
        backtest creible.

        Se DEDUCE del reparto y de lo que cada fuente declara, en lugar de
        configurarse aparte. Una lista de "mercados sin fundamentales" escrita a
        mano acabaria contradiciendo al reparto en cuanto uno de los dos
        cambiara, y esa contradiccion no la notaria nadie.
        """
        try:
            nombre = self._cfg.reglas.proveedor_datos.fuente_de("fundamentales", mercado)
        except ValueError as exc:
            return CalidadFundamental("no_disponible", "", str(exc))

        fuente = self._instancia(nombre)
        cap = fuente.capacidades
        if cap.mercados is not None and mercado not in cap.mercados:
            return CalidadFundamental(
                "no_disponible", nombre, f"'{nombre}' no cubre el mercado '{mercado}'"
            )

        if cap.fechas_publicacion_reales and not cap.cifras_reexpresadas:
            return CalidadFundamental(
                "completa",
                nombre,
                "fechas de publicacion reales y cifras de su momento",
                anios=cap.anios_fundamentales,
            )

        motivos = []
        if not cap.fechas_publicacion_reales:
            motivos.append("fechas estimadas por retraso fijo")
        if cap.cifras_reexpresadas:
            motivos.append("cifras reexpresadas a hoy")
        return CalidadFundamental(
            "degradada", nombre, "; ".join(motivos), anios=cap.anios_fundamentales
        )

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        fuente = self.fuente("divisas")
        df = fuente.fx(divisas, inicio, fin)
        self._recoger_avisos(fuente)
        df = _estampar(df, fuente.nombre)
        df, limpieza = contrato.limpiar_fx(df, self._hoy)
        self.avisos += limpieza.avisos(fuente.nombre, "divisas")
        limite = self._cfg.reglas.datos.fx_antiguedad_maxima_dias
        self.avisos += contrato.huecos_fx(df, limite)
        if self._verificar:
            base = self._cfg.reglas.cartera.divisa_base
            contrato.verificar_fx(
                df,
                fuente.nombre,
                esperadas=[d for d in divisas if d != base],
                # El ultimo cambio posible es el de la vispera de `hoy`: el de
                # `hoy` se aparta.
                hasta=min(fin, self._hoy - timedelta(days=1)),
                antiguedad_maxima_dias=limite,
            ).exigir()
        return df

    def sectores(self, tickers: list[str]) -> dict[str, str | None]:
        fuente = self.fuente("sectores")
        salida = fuente.sectores(tickers)
        self._recoger_avisos(fuente)
        return salida

    def _recoger_avisos(self, fuente: Fuente) -> None:
        """Pasa a `self.avisos` lo que la fuente haya anotado, sin repetirlo."""
        pendientes = getattr(fuente, "avisos", None)
        if pendientes:
            self.avisos += pendientes
            pendientes.clear()


def _completar_opcionales(df: pd.DataFrame) -> pd.DataFrame:
    """Anade a nulo las magnitudes opcionales que la fuente no haya traido.

    Se hace aqui y no en cada adaptador por lo mismo que el contrato: es el
    unico sitio por el que pasan todos los datos, asi que ampliar el contrato no
    obliga a tocar las cinco fuentes ni a que sus autores se acuerden.

    **Solo las opcionales.** Las obligatorias siguen teniendo que venir de la
    fuente: si se rellenaran tambien aqui, una errata en el nombre de una
    columna pasaria de error ruidoso a columna vacia, que es justo el fallo que
    el contrato existe para cazar.
    """
    if df.empty:
        return df
    faltan = [c for c in MAGNITUDES_OPCIONALES if c not in df.columns]
    if faltan:
        df = df.assign(**dict.fromkeys(faltan, None))
    return df


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
