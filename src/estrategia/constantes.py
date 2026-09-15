"""Constantes estructurales, no parametros de estrategia.

El documento pide que el codigo no contenga numeros sueltos. Eso se refiere a
los parametros de la estrategia, que viven todos en `config/reglas.yaml`. Lo
que hay aqui son constantes del dominio o de los datos, que no se optimizan ni
se mueven en el analisis de sensibilidad; cada una lleva su justificacion.
"""

from __future__ import annotations

# Sesiones y semanas de un ano, para anualizar. El numero real de sesiones se
# mide sobre el propio histórico cuando se puede; esto es el respaldo.
SEMANAS_POR_ANO = 52
DIAS_POR_ANO = 365.25

# Meses del ano, para pasar `momentum_meses` a un desplazamiento de fechas.
MESES_POR_ANO = 12

# Categoria a la que va a parar un sector que el mapeo no reconoce. No es un
# valor por defecto benigno: un sector sin traducir rompe a la vez la exclusion
# de financieras y el limite por sector, asi que se trata como rechazo.
SECTOR_DESCONOCIDO = "desconocido"

# Tolerancia para comparar importes en divisa base. Por debajo de un centimo no
# hay diferencia economica y si ruido de coma flotante.
EPSILON_MONETARIO = 1e-9
