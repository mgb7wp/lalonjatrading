"""Carga y validacion de la configuracion.

El documento pide que todos los parametros vivan en `config/reglas.yaml` y que
el codigo no contenga numeros sueltos. Este modulo es el unico sitio que lee
YAML: el resto de la app recibe objetos ya validados, de modo que una clave mal
escrita o un peso que no suma falla al arrancar y no a mitad de un backtest.

`reglas.yaml` es una copia literal del bloque del documento y no se modifica.
Las tablas que hacen falta para llevarlo a la practica (calendarios, ETF de
referencia, mapeo de sectores, pares de divisas) viven aparte, en
`implementacion.yaml`, para que el bloque del documento siga siendo auditable
linea a linea contra su original.
"""

from __future__ import annotations

from functools import cached_property
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Clasificacion = Literal["desarrollado", "emergente"]
Lado = Literal["compra", "venta"]

RAIZ = Path(__file__).resolve().parents[2]
DIR_CONFIG_POR_DEFECTO = RAIZ / "config"


class _Base(BaseModel):
    """Base comun: prohibe claves desconocidas, para que una errata no pase."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------
# reglas.yaml
# --------------------------------------------------------------------------


class ProveedorDatosCfg(_Base):
    """De donde sale cada tipo de dato.

    Admite dos formas. La corta, `nombre: yfinance`, que es la del documento y
    significa "esta fuente para todo". Y el reparto por especialidad, una clave
    por tipo de dato, que es lo que permite quedarse con los precios gratuitos de
    una fuente y traer los fundamentales de otra con historico largo y fechas de
    publicacion reales.

    Se aceptan las dos para que la configuracion del documento siga cargando tal
    cual; lo especifico gana sobre el atajo.
    """

    nombre: str | None = None
    precios: str | None = None
    fundamentales: str | None = None
    divisas: str | None = None
    sectores: str | None = None
    fundamentales_anos_disponibles: int
    ampliacion_futura: str | None = None

    def fuente_de(self, tipo: str) -> str:
        """Que fuente sirve ese tipo de dato."""
        especifica = getattr(self, tipo, None)
        if especifica:
            return especifica
        if self.nombre:
            return self.nombre
        raise ValueError(
            f"no hay fuente para '{tipo}': define proveedor_datos.{tipo} o "
            f"proveedor_datos.nombre"
        )

    @model_validator(mode="after")
    def _hay_alguna_fuente(self) -> "ProveedorDatosCfg":
        if not self.nombre and not any(
            (self.precios, self.fundamentales, self.divisas, self.sectores)
        ):
            raise ValueError(
                "proveedor_datos necesita al menos `nombre` o una fuente por tipo"
            )
        return self


class CarteraCfg(_Base):
    divisa_base: str
    capital_inicial_eur: float
    max_posiciones: int = Field(gt=0)
    max_por_sector: int = Field(gt=0)
    max_por_mercado: int = Field(gt=0)
    peso_maximo: float = Field(gt=0, le=1)


class MercadoCfg(_Base):
    id: str
    sufijo: str
    divisa: str
    clasificacion: Clasificacion


class UniversoCfg(_Base):
    mercados: list[MercadoCfg]
    volumen_minimo_desarrollado: float = Field(ge=0)
    volumen_minimo_emergente: float = Field(ge=0)
    excluir_sectores: list[str]
    sesiones_volumen: int = Field(gt=0)
    lote_por_mercado: dict[str, int] = Field(default_factory=dict)

    def lote(self, mercado_id: str) -> int:
        """Unidad minima de contratacion del mercado."""
        return self.lote_por_mercado.get(mercado_id, 1)

    def volumen_minimo(self, clasificacion: Clasificacion) -> float:
        """Minimo de volumen negociado segun el bloque del mercado."""
        if clasificacion == "emergente":
            return self.volumen_minimo_emergente
        return self.volumen_minimo_desarrollado


class DatosCfg(_Base):
    precios_ajustados: bool
    retraso_trimestral_dias: int = Field(ge=0)
    retraso_anual_dias: int = Field(ge=0)
    retraso_por_mercado: dict[str, int] = Field(default_factory=dict)
    guardar_foto_fundamentales: str
    guardar_foto_fx: str
    sesiones_sin_datos_cierre_forzoso: int = Field(gt=0)
    fx_decision_dia_anterior: bool

    def retraso(self, mercado: str, periodo: Literal["trimestral", "anual"]) -> int:
        """Dias que se suponen entre el cierre del periodo y su publicacion.

        El valor especifico del mercado manda sobre el general, porque algunos
        mercados emergentes publican con mas retraso que el europeo medio.
        """
        especifico = self.retraso_por_mercado.get(mercado)
        if especifico is not None:
            return especifico
        return self.retraso_trimestral_dias if periodo == "trimestral" else self.retraso_anual_dias


class MinimosCfg(_Base):
    roe: float
    margen_operativo: float
    crecimiento_ventas_3a: float
    flujo_caja_libre_positivo: bool
    deuda_neta_ebitda_max: float


class PuntuacionCfg(_Base):
    peso_calidad: float = Field(ge=0)
    peso_valoracion: float = Field(ge=0)

    @model_validator(mode="after")
    def _pesos_suman_uno(self) -> "PuntuacionCfg":
        total = self.peso_calidad + self.peso_valoracion
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"peso_calidad + peso_valoracion debe sumar 1, suma {total}")
        return self


class FundamentalCfg(_Base):
    minimos: MinimosCfg
    excepciones_sector: dict[str, dict[str, float]] = Field(default_factory=dict)
    percentiles: str
    cohorte_percentiles: Literal["universo_elegible", "solo_aprobadas"]
    min_empresas_percentil: int = Field(gt=0)
    antiguedad_maxima_dias: int = Field(gt=0)
    activo: bool
    puntuacion: PuntuacionCfg

    def minimos_para(self, sector: str) -> MinimosCfg:
        """Minimos aplicables a un sector, con sus excepciones ya aplicadas.

        Las electricas son el caso que recoge el documento: soportan mas deuda
        que la media porque su flujo de caja es mas estable y regulado.
        """
        excepcion = self.excepciones_sector.get(sector)
        if not excepcion:
            return self.minimos
        return self.minimos.model_copy(update=dict(excepcion))


class TecnicoCfg(_Base):
    revision: str
    calculo_medias_momentum: str
    indices_regimen: dict[str, str]
    regimen_mercado_media: int = Field(gt=0)
    media_corta: int = Field(gt=0)
    media_larga: int = Field(gt=0)
    momentum_meses: int = Field(gt=0)
    momentum_excluir_meses: int = Field(ge=0)
    atr_periodo: int = Field(gt=0)

    @model_validator(mode="after")
    def _corta_menor_que_larga(self) -> "TecnicoCfg":
        if self.media_corta >= self.media_larga:
            raise ValueError("media_corta debe ser menor que media_larga")
        if self.momentum_excluir_meses >= self.momentum_meses:
            raise ValueError("momentum_excluir_meses debe ser menor que momentum_meses")
        return self


class PesosSeleccionCfg(_Base):
    fundamental: float = Field(ge=0)
    momentum: float = Field(ge=0)

    @model_validator(mode="after")
    def _pesos_suman_uno(self) -> "PesosSeleccionCfg":
        total = self.fundamental + self.momentum
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"seleccion.pesos debe sumar 1, suma {total}")
        return self


class SeleccionCfg(_Base):
    pesos: PesosSeleccionCfg


class SalidasCfg(_Base):
    stop_inicial_atr: float = Field(gt=0)
    stop_dinamico_atr: float = Field(gt=0)
    salir_bajo_media_larga: bool
    salir_si_falla_fundamental: bool


class RiesgoCfg(_Base):
    por_operacion: float = Field(gt=0, le=1)


class CostesCfg(_Base):
    comision_fija_eur: float = Field(ge=0)
    comision_pct: float = Field(ge=0)
    deslizamiento_pct_por_mercado: dict[str, float]
    impuestos_transaccion: str

    def deslizamiento(self, mercado_id: str, clasificacion: Clasificacion) -> float:
        """Deslizamiento del mercado.

        El documento pide poder afinar por mercado concreto ademas de por
        bloque, asi que un `id` de mercado en la tabla gana al bloque.
        """
        especifico = self.deslizamiento_pct_por_mercado.get(mercado_id)
        if especifico is not None:
            return especifico
        try:
            return self.deslizamiento_pct_por_mercado[clasificacion]
        except KeyError as exc:  # pragma: no cover - configuracion invalida
            raise KeyError(
                f"no hay deslizamiento para el mercado '{mercado_id}' ni para el "
                f"bloque '{clasificacion}' en costes.deslizamiento_pct_por_mercado"
            ) from exc


class PanelCfg(_Base):
    """Ajustes del panel interactivo.

    `modo_publico` existe porque el panel se sirve desde la maquina de casa a
    traves de un tunel y sin autenticacion: cualquiera que de con la URL puede
    pulsar lo que haya. Lo caro se desactiva y las rutas locales no se ensenan.
    """

    modo_publico: bool = False


class MetricasCfg(_Base):
    tasa_libre_riesgo_anual: float
    periodicidad_sharpe: Literal["diaria", "semanal"]


class ValidacionCfg(_Base):
    fraccion_diseno: float = Field(gt=0, lt=1)
    sensibilidad_pct: float = Field(gt=0)
    min_operaciones: int = Field(ge=0)
    min_operaciones_por_mercado: int = Field(ge=0)


class Reglas(_Base):
    """El bloque de configuracion del documento, ya validado."""

    proveedor_datos: ProveedorDatosCfg
    cartera: CarteraCfg
    universo: UniversoCfg
    datos: DatosCfg
    fundamental: FundamentalCfg
    tecnico: TecnicoCfg
    seleccion: SeleccionCfg
    salidas: SalidasCfg
    riesgo: RiesgoCfg
    costes: CostesCfg
    referencias_informe: list[str]
    panel: PanelCfg = Field(default_factory=PanelCfg)
    metricas: MetricasCfg
    validacion: ValidacionCfg

    @cached_property
    def mercados_por_id(self) -> dict[str, MercadoCfg]:
        return {m.id: m for m in self.universo.mercados}

    def mercado(self, mercado_id: str) -> MercadoCfg:
        try:
            return self.mercados_por_id[mercado_id]
        except KeyError as exc:
            raise KeyError(f"mercado desconocido: {mercado_id!r}") from exc

    @model_validator(mode="after")
    def _coherencia(self) -> "Reglas":
        ids = [m.id for m in self.universo.mercados]
        if len(ids) != len(set(ids)):
            raise ValueError("hay ids de mercado repetidos en universo.mercados")
        faltan = set(ids) - set(self.tecnico.indices_regimen)
        if faltan:
            raise ValueError(
                "todo mercado necesita su indice de regimen en tecnico.indices_regimen; "
                f"faltan: {sorted(faltan)}"
            )
        # max_por_mercado por encima de max_posiciones no es un error, pero si
        # una senal de que uno de los dos no dice lo que se cree.
        if self.cartera.max_por_mercado > self.cartera.max_posiciones:
            raise ValueError("max_por_mercado no puede superar max_posiciones")
        if self.cartera.max_por_sector > self.cartera.max_posiciones:
            raise ValueError("max_por_sector no puede superar max_posiciones")
        return self


# --------------------------------------------------------------------------
# implementacion.yaml
# --------------------------------------------------------------------------


class ReferenciaCfg(_Base):
    ticker: str
    nombre: str
    divisa: str


class Implementacion(_Base):
    calendarios: dict[str, str]
    codigos_eodhd: dict[str, str] = Field(default_factory=dict)
    referencias: dict[str, ReferenciaCfg]
    divisas: dict[str, str | None]
    sectores: dict[str, str]
    equivalencias_excepciones: dict[str, str]

    def sector(self, sector_proveedor: str | None) -> str:
        """Traduce el sector del proveedor a la categoria del documento.

        Lo que no esta en la tabla vuelve como `desconocido` en lugar de
        colarse: el documento avisa de que la clasificacion no coincide entre
        mercados, y un sector mal traducido rompe a la vez la exclusion de
        financieras, la excepcion de las electricas y `max_por_sector`.
        """
        if not sector_proveedor:
            return "desconocido"
        return self.sectores.get(sector_proveedor.strip(), "desconocido")


# --------------------------------------------------------------------------
# universo.yaml
# --------------------------------------------------------------------------


class ValorUniverso(_Base):
    ticker: str
    nombre: str
    sector_declarado: str


class Universo(_Base):
    mercados: dict[str, list[ValorUniverso]]

    def tickers(self, mercado_id: str | None = None) -> list[str]:
        if mercado_id is not None:
            return [v.ticker for v in self.mercados.get(mercado_id, [])]
        return [v.ticker for valores in self.mercados.values() for v in valores]

    @cached_property
    def mercado_de_ticker(self) -> dict[str, str]:
        return {
            v.ticker: mercado_id
            for mercado_id, valores in self.mercados.items()
            for v in valores
        }

    @cached_property
    def valores_por_ticker(self) -> dict[str, ValorUniverso]:
        return {v.ticker: v for valores in self.mercados.values() for v in valores}


# --------------------------------------------------------------------------
# impuestos_transaccion.yaml
# --------------------------------------------------------------------------


class ImpuestoPais(_Base):
    impuesto: str
    pct: float = Field(ge=0)
    aplica_en: list[Lado]
    solo_lista_anual: bool = False
    vigente_desde: date | None = None
    vigente_hasta: date | None = None
    lista_anual: dict[int, list[str]] = Field(default_factory=dict)

    def vigente_en(self, fecha: date) -> bool:
        """Si el impuesto existia en esa fecha.

        El ITF espanol es de 2021: aplicarlo hacia atras sobreestima costes.
        """
        if self.vigente_desde is not None and fecha < self.vigente_desde:
            return False
        if self.vigente_hasta is not None and fecha > self.vigente_hasta:
            return False
        return True

    def grava(self, ticker: str, lado: Lado, fecha: date) -> bool:
        """Si esta operacion concreta devenga el impuesto."""
        if lado not in self.aplica_en or not self.vigente_en(fecha):
            return False
        if not self.solo_lista_anual:
            return True
        if not self.lista_anual:
            return False
        # Si no hay lista del ano de la operacion se usa la mas reciente
        # anterior; quien consuma esto deja constancia de la extrapolacion.
        anos = sorted(a for a in self.lista_anual if a <= fecha.year)
        ano = anos[-1] if anos else min(self.lista_anual)
        return ticker in self.lista_anual[ano]


class Impuestos(_Base):
    paises: dict[str, ImpuestoPais]


# --------------------------------------------------------------------------
# Conjunto completo
# --------------------------------------------------------------------------


class Config(_Base):
    """Toda la configuracion de la app, ya validada y coherente entre ficheros."""

    reglas: Reglas
    implementacion: Implementacion
    universo: Universo
    impuestos: Impuestos
    dir_config: Path

    def con_fuente_unica(self, nombre: str) -> "Config":
        """Copia con una sola fuente sirviendo todos los tipos de dato.

        Es lo que hay detras de `--proveedor`: util para los tests y para
        trabajar sin red, pero el reparto de verdad vive en `reglas.yaml`.
        """
        reglas = self.reglas.model_copy(
            update={
                "proveedor_datos": self.reglas.proveedor_datos.model_copy(
                    update={
                        "nombre": nombre,
                        "precios": None,
                        "fundamentales": None,
                        "divisas": None,
                        "sectores": None,
                    }
                )
            }
        )
        return self.model_copy(update={"reglas": reglas})

    @model_validator(mode="after")
    def _coherencia_entre_ficheros(self) -> "Config":
        ids_reglas = set(self.reglas.mercados_por_id)

        desconocidos = set(self.universo.mercados) - ids_reglas
        if desconocidos:
            raise ValueError(
                f"universo.yaml define mercados que no estan en reglas.yaml: {sorted(desconocidos)}"
            )
        faltan_cal = ids_reglas - set(self.implementacion.calendarios)
        if faltan_cal:
            raise ValueError(f"faltan calendarios en implementacion.yaml: {sorted(faltan_cal)}")

        faltan_ref = set(self.reglas.referencias_informe) - set(self.implementacion.referencias)
        if faltan_ref:
            raise ValueError(
                f"faltan referencias en implementacion.yaml: {sorted(faltan_ref)}"
            )

        divisas_necesarias = {m.divisa for m in self.reglas.universo.mercados}
        divisas_necesarias |= {r.divisa for r in self.implementacion.referencias.values()}
        faltan_div = divisas_necesarias - set(self.implementacion.divisas)
        if faltan_div:
            raise ValueError(
                f"faltan pares de divisa en implementacion.yaml: {sorted(faltan_div)}"
            )
        return self


def _leer_yaml(ruta: Path) -> dict:
    if not ruta.is_file():
        raise FileNotFoundError(f"no existe el fichero de configuracion: {ruta}")
    with ruta.open(encoding="utf-8") as fh:
        contenido = yaml.safe_load(fh)
    if not isinstance(contenido, dict):
        raise ValueError(f"{ruta} no contiene un mapa YAML en la raiz")
    return contenido


def cargar(dir_config: Path | str | None = None) -> Config:
    """Carga los cuatro ficheros de configuracion y los valida en conjunto."""
    directorio = Path(dir_config) if dir_config is not None else DIR_CONFIG_POR_DEFECTO
    reglas = Reglas.model_validate(_leer_yaml(directorio / "reglas.yaml"))

    # La ruta del fichero de impuestos la marca reglas.yaml, no el codigo.
    ruta_impuestos = Path(reglas.costes.impuestos_transaccion)
    if not ruta_impuestos.is_absolute():
        # En reglas.yaml se escribe relativa a la raiz del proyecto.
        candidata = RAIZ / ruta_impuestos
        ruta_impuestos = candidata if candidata.is_file() else directorio / ruta_impuestos.name

    return Config(
        reglas=reglas,
        implementacion=Implementacion.model_validate(_leer_yaml(directorio / "implementacion.yaml")),
        universo=Universo.model_validate(_leer_yaml(directorio / "universo.yaml")),
        impuestos=Impuestos.model_validate(_leer_yaml(ruta_impuestos)),
        dir_config=directorio,
    )
