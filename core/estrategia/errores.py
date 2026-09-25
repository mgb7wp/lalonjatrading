"""Errores propios de la app.

Existen para que el CLI pueda dar un mensaje accionable en espanol en lugar de
una traza, que es lo unico que se puede hacer con un YAML mal escrito o con un
proveedor que no responde.
"""

from __future__ import annotations


class ErrorEstrategia(Exception):
    """Raiz de todos los errores propios."""


class ErrorConfiguracion(ErrorEstrategia):
    """La configuracion no es valida o es incoherente entre ficheros."""


class ErrorDatos(ErrorEstrategia):
    """Faltan datos, o los que hay no sirven para decidir."""


class ErrorCalendario(ErrorEstrategia):
    """Se ha pedido algo imposible sobre el calendario de un mercado."""


class ErrorAnticipacion(ErrorEstrategia):
    """Se ha intentado leer un dato posterior a la fecha de corte.

    No es un error de usuario: es la red de seguridad del almacen puntual. Que
    salte significa que hay un fallo en el codigo que habria contaminado el
    backtest con informacion del futuro.
    """
