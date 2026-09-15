"""Estado de la cartera.

Contenedor puro: guarda efectivo y posiciones, aplica ejecuciones y sabe
valorarse. No decide nada. Toda la logica de que comprar esta en `ordenes.py` y
la de cuando vender en `salidas.py`; separarlo es lo que evita el enredo
circular clasico entre cartera, riesgo y seleccion.

La valoracion es lo unico de la app que trabaja en divisa base, junto con el
dimensionado. El precio se queda en divisa local hasta aqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .tipos import MotivoSalida, Operacion, Posicion


@dataclass
class Cartera:
    """Efectivo y posiciones abiertas, en divisa base."""

    efectivo: float
    posiciones: dict[str, Posicion] = field(default_factory=dict)
    operaciones: list[Operacion] = field(default_factory=list)

    # -- consultas ---------------------------------------------------------

    @property
    def n_posiciones(self) -> int:
        return len(self.posiciones)

    def tiene(self, ticker: str) -> bool:
        return ticker in self.posiciones

    def n_en_sector(self, sector: str) -> int:
        return sum(1 for p in self.posiciones.values() if p.sector == sector)

    def n_en_mercado(self, mercado: str) -> int:
        return sum(1 for p in self.posiciones.values() if p.mercado == mercado)

    def valor(self, precios_base: dict[str, float]) -> float:
        """Patrimonio total: efectivo mas posiciones a precio de mercado.

        Un valor cuyo mercado esta cerrado hoy se valora con su ultimo cierre
        local pero con el cambio de HOY: la divisa se mueve aunque la bolsa este
        de fiesta, y la cartera de un inversor en euros lo nota.
        """
        total = self.efectivo
        for ticker, pos in self.posiciones.items():
            total += pos.acciones * precios_base.get(ticker, pos.precio_entrada_base)
        return total

    # -- mutaciones --------------------------------------------------------

    def abrir(self, posicion: Posicion, desembolso_base: float) -> None:
        self.efectivo -= desembolso_base
        self.posiciones[posicion.ticker] = posicion

    def cerrar(
        self,
        ticker: str,
        fecha: date,
        precio_salida_local: float,
        fx_salida: float,
        ingreso_base: float,
        costes_salida_base: float,
        motivo: MotivoSalida,
    ) -> Operacion:
        pos = self.posiciones.pop(ticker)
        self.efectivo += ingreso_base

        precio_salida_base = precio_salida_local * fx_salida
        costes = pos.coste_entrada_base + costes_salida_base
        bruto = pos.acciones * (precio_salida_base - pos.precio_entrada_base)

        operacion = Operacion(
            ticker=pos.ticker,
            mercado=pos.mercado,
            sector=pos.sector,
            divisa=pos.divisa,
            acciones=pos.acciones,
            fecha_entrada=pos.fecha_entrada,
            fecha_salida=fecha,
            precio_entrada_local=pos.precio_entrada_local,
            precio_salida_local=precio_salida_local,
            precio_entrada_base=pos.precio_entrada_base,
            precio_salida_base=precio_salida_base,
            fx_entrada=pos.fx_entrada,
            fx_salida=fx_salida,
            motivo_salida=motivo,
            costes_base=costes,
            resultado_base=bruto - costes,
            riesgo_teorico_pct=pos.riesgo_teorico_pct,
            riesgo_efectivo_pct=pos.riesgo_efectivo_pct,
        )
        self.operaciones.append(operacion)
        return operacion

    def actualizar(self, posicion: Posicion) -> None:
        self.posiciones[posicion.ticker] = posicion
