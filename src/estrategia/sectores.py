"""Traduccion de los sectores del proveedor a las categorias del documento.

El documento avisa de que "los nombres de sector deben mapearse a la
clasificacion del proveedor de datos, que no siempre coincide entre mercados".
Merece modulo propio porque de esta traduccion dependen tres reglas distintas:
la exclusion de bancos, aseguradoras e inmobiliarias; la excepcion de deuda de
las electricas; y el limite `max_por_sector`.

La decision importante esta en `clasificar`: un sector que el mapeo no conoce
no se traduce a nada benigno, se marca como desconocido y la empresa se rechaza.
Fallar hacia el lado seguro importa aqui: un sector sin traducir podria colar un
banco en una cartera que, por diseno, no quiere bancos.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .constantes import SECTOR_DESCONOCIDO
from .tipos import MotivoRechazo


@dataclass(frozen=True, slots=True)
class Clasificacion:
    """Resultado de clasificar un valor."""

    sector: str
    admitido: bool
    motivo: MotivoRechazo | None = None


class MapaSectores:
    """Traduce sectores y lleva cuenta de los que no reconoce."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._excluidos = set(cfg.reglas.universo.excluir_sectores)
        self._sin_mapear: dict[str, set[str]] = {}

    def clasificar(self, ticker: str, sector_proveedor: str | None) -> Clasificacion:
        """Clasifica un valor a partir del sector que da el proveedor.

        Si el proveedor no devuelve sector se recurre al `sector_declarado` de
        `universo.yaml`, que existe justo para eso; si tampoco lo hay, el valor
        se rechaza en lugar de pasar sin clasificar.
        """
        sector = self._cfg.implementacion.sector(sector_proveedor)

        if sector == SECTOR_DESCONOCIDO:
            if sector_proveedor:
                self._sin_mapear.setdefault(sector_proveedor, set()).add(ticker)
            valor = self._cfg.universo.valores_por_ticker.get(ticker)
            if valor is not None:
                sector = valor.sector_declarado

        if sector == SECTOR_DESCONOCIDO:
            return Clasificacion(sector, False, MotivoRechazo.SECTOR_DESCONOCIDO)
        if sector in self._excluidos:
            return Clasificacion(sector, False, MotivoRechazo.SECTOR_EXCLUIDO)
        return Clasificacion(sector, True)

    @property
    def sin_mapear(self) -> dict[str, list[str]]:
        """Sectores que el proveedor devolvio y el mapeo no conoce.

        El informe los lista: son deuda de configuracion, y cada uno significa
        valores que se estan quedando fuera sin que nadie lo haya decidido.
        """
        return {s: sorted(t) for s, t in sorted(self._sin_mapear.items())}
