"""Frontera entre el nucleo (en espanol) y la plataforma (en ingles).

La decision D-14 de docs/PROJECT_PLAN.md: el motor no se traduce —reescribir
7.600 lineas probadas para cambiar nombres es riesgo sin beneficio— y el codigo
nuevo va en ingles, que es lo que espera cualquiera que se incorpore.

La costura es deliberada, y vive aqui para que este en un sitio y no repartida.
Todo lo que cruce de `estrategia.*` a un esquema de API o de base de datos pasa
por este paquete. El glosario esta en docs/GLOSARIO.md.
"""
