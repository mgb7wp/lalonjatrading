"""Plataforma SaaS: API, persistencia y servicios.

Este paquete puede importar `estrategia` (el nucleo cuantitativo). El nucleo no
puede importar este. La direccion unica es lo que permite correr un backtest sin
levantar base de datos, y esta comprobada en `tests/test_arquitectura.py`.
"""
