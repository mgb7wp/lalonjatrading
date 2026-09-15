"""Feature store, entrenamiento y registro de modelos.

Vacio a proposito. La decision D-7 de docs/PROJECT_PLAN.md pospone el ML hasta
que haya muestra suficiente (universo >= 1.000 valores y >= 15 anos de
historico en dos mercados). Con ~140 valores y ventanas solapadas a 3 meses hay
decenas de observaciones independientes, no miles: un modelo entrenado ahi
memoriza el periodo, no aprende nada transferible.

Hasta entonces el sistema funciona con el motor determinista, que ademas es
explicable, que es lo que pide §28.
"""
