"""Infraestructura de ML (FASE 8), con D-7 sin cumplir.

Lo que hay aqui es la maquinaria, no un modelo: D-7 no se cumple —138 valores de
1.000 y 8 anios de 15— y la propia infraestructura se niega a entrenar. Estos
tests comprueban justo eso: que la puerta cierra, y que la particion no deja
pasar informacion del futuro.
"""

from __future__ import annotations

import datetime as dt

import pytest

from ml import condiciones, seleccion
from ml.particion import ParticionImposible, hay_fuga, walk_forward

HORIZONTE = 90


def _semanal(n: int = 60) -> list[dt.date]:
    return [dt.date(2020, 1, 1) + dt.timedelta(days=7 * i) for i in range(n)]


# --- La particion: que no se cuele el futuro -------------------------------


def test_ningun_pliegue_entrena_con_etiquetas_que_se_resuelven_en_la_prueba():
    """La propiedad central. Si falla, cualquier metrica que salga es mentira."""
    inicios = _semanal()
    for pliegue in walk_forward(inicios, HORIZONTE, n_pliegues=5):
        assert not hay_fuga(pliegue, inicios, HORIZONTE), (
            f"el pliegue {pliegue.indice} entrena con observaciones cuya etiqueta "
            f"se resuelve dentro del periodo de prueba"
        )


def test_sin_purgar_SI_habria_fuga():
    """El test que le da sentido al anterior.

    Se construye a mano la particion ingenua —todo lo anterior al inicio de la
    prueba entrena— y se comprueba que SI filtra. Sin esto, el test de arriba
    podria estar pasando porque no hay solape posible, no porque se purgue.
    """
    inicios = _semanal()
    pliegues = walk_forward(inicios, HORIZONTE, n_pliegues=5)
    objetivo = pliegues[2]

    import numpy as np

    ingenuo = np.array([i for i, f in enumerate(inicios) if f < objetivo.inicio_prueba], dtype=int)
    from dataclasses import replace

    assert hay_fuga(replace(objetivo, entrenamiento=ingenuo), inicios, HORIZONTE), (
        "la particion ingenua tendria que filtrar; si no, este escenario no prueba nada"
    )
    assert objetivo.purgadas > 0, "y la purga tiene que haber quitado algo"


def test_un_horizonte_mas_largo_purga_mas():
    """Cuanto mas dura la etiqueta, mas se solapa y mas hay que tirar.

    Si el numero de purgadas no dependiera del horizonte, la purga estaria
    mirando otra cosa.
    """
    inicios = _semanal()
    corto = walk_forward(inicios, 30, n_pliegues=5)[3].purgadas
    largo = walk_forward(inicios, 180, n_pliegues=5)[3].purgadas

    assert largo > corto


def test_el_walk_forward_no_entrena_con_el_futuro():
    """Entrenar con lo posterior mide capacidad, no simula una decision.

    Por defecto se entrena solo con el pasado, que es lo unico que se podria
    haber hecho aquel dia.
    """
    inicios = _semanal()
    for pliegue in walk_forward(inicios, HORIZONTE, n_pliegues=4):
        for i in pliegue.entrenamiento:
            assert inicios[i] < pliegue.inicio_prueba


def test_el_embargo_solo_muerde_cuando_se_permite_entrenar_con_lo_posterior():
    """Aviso honesto hecho test.

    En walk-forward estricto el embargo NO quita nada, porque no hay
    entrenamiento despues de la prueba. Decir "protegido por embargo" ahi seria
    una tranquilidad falsa. Donde si hace falta es en la variante que permite
    datos posteriores.
    """
    inicios = _semanal()

    estricto = walk_forward(inicios, HORIZONTE, n_pliegues=4, embargo_dias=30)
    assert all(p.embargadas == 0 for p in estricto), "en estricto no puede morder"

    con_futuro = walk_forward(
        inicios, HORIZONTE, n_pliegues=4, embargo_dias=60, permitir_futuro=True
    )
    assert any(p.embargadas > 0 for p in con_futuro), "aqui si tiene que morder"


def test_el_periodo_de_prueba_llega_hasta_que_se_resuelve_su_ultima_etiqueta():
    """Usar la ultima fecha de DECISION dejaria fuera justo el tramo que solapa."""
    inicios = _semanal()
    pliegue = walk_forward(inicios, HORIZONTE, n_pliegues=4)[1]
    ultima_decision = max(inicios[i] for i in pliegue.prueba)

    assert pliegue.fin_prueba == ultima_decision + dt.timedelta(days=HORIZONTE)


def test_pedir_mas_pliegues_que_observaciones_falla_en_voz_alta():
    with pytest.raises(ParticionImposible):
        walk_forward(_semanal(3), HORIZONTE, n_pliegues=10)


# --- D-7: la puerta que impide entrenar sin muestra ------------------------


def test_el_estado_real_del_proyecto_no_cumple_d7():
    """Documenta el porque en forma ejecutable.

    138 valores de 1.000 y 8 anios de 15. Cuando algun dia cambie, este test
    fallara y sera la senal de que toca revisar la decision, no de que el test
    este mal.
    """
    v = condiciones.evaluar(138, {"us": 8.0, "br": 8.0, "es": 8.0})

    assert not v.cumple
    assert len(v.motivos) == 2, "fallan las dos condiciones, no una"
    assert "138" in v.motivos[0]


def test_cumplir_solo_una_condicion_no_basta():
    """Universo de sobra pero historico corto: sigue siendo que no."""
    assert not condiciones.evaluar(5000, {"us": 8.0, "br": 8.0}).cumple
    assert not condiciones.evaluar(138, {"us": 30.0, "br": 30.0}).cumple


def test_un_solo_mercado_con_historico_no_basta():
    """D-7 pide DOS. Un solo mercado largo es un solo regimen economico."""
    v = condiciones.evaluar(5000, {"us": 30.0, "br": 8.0})
    assert not v.cumple
    assert "mercado" in v.motivos[0]


def test_cumpliendo_las_dos_condiciones_se_puede_entrenar():
    v = condiciones.evaluar(1200, {"us": 20.0, "br": 18.0, "es": 5.0})
    assert v.cumple
    assert v.mercados_con_historico == 2


def test_entrenar_sin_d7_revienta_en_vez_de_avisar():
    """Un aviso en el log se lee una vez y se ignora la siguiente."""
    with pytest.raises(condiciones.D7NoCumplida, match="138"):
        condiciones.exigir(condiciones.evaluar(138, {"us": 8.0}))


# --- La puerta de aceptacion de modelos ------------------------------------


def test_un_modelo_que_no_bate_al_baseline_se_rechaza():
    r = seleccion.decidir([0.55, 0.54, 0.56], [0.55, 0.55, 0.55])
    assert not r.acepta
    assert "margen" in r.motivo


def test_ganar_por_un_pelo_no_cuenta():
    """Batir por 0,001 es ruido muestral, no una mejora."""
    r = seleccion.decidir([0.551, 0.551, 0.551], [0.550, 0.550, 0.550])
    assert not r.acepta


def test_ganar_de_media_gracias_a_un_solo_pliegue_se_rechaza():
    """El caso que mas enganya: la media sube y el modelo pierde casi siempre.

    Sin la comprobacion por pliegues, un unico periodo afortunado basta para
    sustituir al baseline.
    """
    r = seleccion.decidir([0.40, 0.40, 0.40, 0.40, 1.00], [0.50, 0.50, 0.50, 0.50, 0.50])
    assert r.media_candidato > r.media_baseline, "de media gana, que es la trampa"
    assert not r.acepta
    assert "pliegue" in r.motivo


def test_un_modelo_que_gana_de_verdad_se_acepta():
    r = seleccion.decidir([0.60, 0.61, 0.59, 0.62], [0.55, 0.55, 0.54, 0.56])
    assert r.acepta
    assert r.pliegues_ganados == 4


def test_sin_metricas_comparables_no_se_acepta_nada():
    assert not seleccion.decidir([], []).acepta
    assert not seleccion.decidir([0.6], [0.5, 0.5]).acepta
