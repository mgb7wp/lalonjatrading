"""Tests del motor de scoring (FASE 6)."""

from __future__ import annotations

import numpy as np
import pytest
import yaml
from estrategia.scoring import (
    DIRECCION,
    FACTORES_RIESGO,
    FACTORES_TECNICOS,
    PILARES,
    SUBSCORES_TECNICOS,
    factores_tecnicos,
    puntuar,
)


def _cohorte(n: int, **variando):
    factores, cohortes = {}, {}
    for i in range(n):
        t = f"T{i}"
        factores[t] = dict.fromkeys(DIRECCION)
        for nombre, valores in variando.items():
            factores[t][nombre] = valores[i]
        cohortes[t] = "x"
    return factores, cohortes


# ---------------------------------------------------------------------------
# Estructura
# ---------------------------------------------------------------------------


def test_los_pilares_son_ortogonales():
    """§18 suma momentum aparte de technical y calidad aparte de fundamental.

    Eso cuenta el momentum dos veces. La decision D-3 separa pilares —que
    agregan— de sub-scores —que descomponen uno y se publican sin sumar—.
    """
    assert set(PILARES) == {"fundamental", "tecnico", "sentimiento", "riesgo"}
    # Ningun factor tecnico puede pertenecer al pilar de riesgo y viceversa.
    assert {f.pilar for f in FACTORES_TECNICOS} == {"tecnico"}
    assert {f.pilar for f in FACTORES_RIESGO} == {"riesgo"}
    assert {f.subscore for f in FACTORES_TECNICOS} == set(SUBSCORES_TECNICOS)


def test_los_factores_de_riesgo_declaran_su_direccion():
    """§17: 100 es MENOS riesgo. Es el error mas facil de cometer aqui.

    Sin declararlo, una volatilidad alta puntuaria como seguridad y el ranking
    de "bajo riesgo" lo encabezarian los valores mas nerviosos del mercado.
    """
    por_nombre = {f.nombre: f.mejor for f in FACTORES_RIESGO}
    assert por_nombre["volatilidad_60"] == "bajo"
    assert por_nombre["beta_252"] == "bajo"
    assert por_nombre["deuda_patrimonio"] == "bajo"
    assert por_nombre["variacion_beneficios"] == "bajo"
    # El drawdown es negativo por convenio: mas cerca de cero es mejor.
    assert por_nombre["drawdown_maximo_1a"] == "alto"
    assert por_nombre["liquidez"] == "alto"


# ---------------------------------------------------------------------------
# Factores derivados
# ---------------------------------------------------------------------------


def test_las_medias_se_comparan_como_distancia_al_precio():
    """Una media de 200 vale 40 en un valor y 400 en otro.

    Comparar el nivel entre valores no significa nada; lo que compara es la
    distancia relativa del precio a su media.
    """
    f = factores_tecnicos({"sma_200": 100.0, "sma_50": 110.0}, cierre=120.0)
    assert f["distancia_sma_200"] == pytest.approx(0.20)
    assert f["pendiente_medias"] == pytest.approx(0.10)


def test_el_atr_y_el_macd_se_normalizan_por_el_precio():
    """Un MACD de 2 es enorme en un valor de 10 e irrelevante en uno de 400."""
    f = factores_tecnicos({"atr_14": 4.0, "macd": 3.0, "macd_signal": 1.0}, cierre=200.0)
    assert f["atr_relativo"] == pytest.approx(0.02)
    assert f["macd_histograma"] == pytest.approx(0.01)


def test_sin_precio_no_se_inventan_los_factores_relativos():
    f = factores_tecnicos({"sma_200": 100.0, "atr_14": 4.0}, cierre=None)
    assert f["distancia_sma_200"] is None
    assert f["atr_relativo"] is None


def test_un_indicador_infinito_no_se_propaga():
    f = factores_tecnicos({"rsi_14": float("inf"), "adx_14": float("nan")}, cierre=10.0)
    assert f["adx_14"] is None


# ---------------------------------------------------------------------------
# Agregacion
# ---------------------------------------------------------------------------


def test_menos_volatilidad_puntua_mas_en_riesgo():
    """La comprobacion que impide el ranking de bajo riesgo invertido."""
    factores, cohortes = _cohorte(10, volatilidad_60=[0.1 * i for i in range(1, 11)])
    p = puntuar(factores, cohortes, min_cohorte=5)
    assert p["T0"].pilares["riesgo"] > p["T9"].pilares["riesgo"]


def test_el_sentimiento_nunca_puntua_cincuenta():
    """No hay fuente, asi que el pilar va vacio y se declara (D-8).

    Imputarle un 50 neutro seria inventar un dato que mueve el ranking de todo
    el universo a la vez.
    """
    factores, cohortes = _cohorte(10, momentum_12_1=[float(i) for i in range(10)])
    p = puntuar(factores, cohortes, min_cohorte=5)["T5"]
    assert p.pilares["sentimiento"] is None
    assert "sentimiento" not in p.pilares_disponibles
    assert "sentimiento" in p.pilares_no_disponibles


def test_los_pesos_se_renormalizan_sobre_los_pilares_con_nota():
    """Un pilar ausente no puede arrastrar el total hacia abajo.

    Con solo el tecnico disponible, el total tiene que ser el tecnico, no el
    tecnico multiplicado por su peso.
    """
    factores, cohortes = _cohorte(10, momentum_12_1=[float(i) for i in range(10)])
    pesos = {"fundamental": 0.5, "tecnico": 0.35, "sentimiento": 0.1, "riesgo": 0.05}
    p = puntuar(factores, cohortes, pesos=pesos, min_cohorte=5)["T9"]
    assert p.pilares["fundamental"] is None
    assert p.overall == pytest.approx(p.pilares["tecnico"])


def test_cambiar_los_pesos_cambia_el_orden_sin_tocar_codigo():
    """El criterio de aceptacion de §18: los perfiles son datos, no codigo."""
    # Se usan factores EXCLUSIVOS de cada pilar. `volatilidad_60` no valdria:
    # pertenece a los dos a proposito —§17 la pide en riesgo y es tambien un
    # sub-score tecnico— asi que subirla compensa el momentum dentro del propio
    # pilar tecnico y los dos perfiles acaban empatados.
    #
    # El momentum solo cuenta en el tecnico y la beta solo en el riesgo, asi que
    # T9 gana con pesos tecnicos y T0 con pesos de riesgo.
    factores, cohortes = _cohorte(
        10,
        momentum_12_1=[float(i) for i in range(10)],
        beta_252=[float(i) for i in range(10)],
    )
    pro_tecnico = puntuar(factores, cohortes, pesos={"tecnico": 1.0, "riesgo": 0.0}, min_cohorte=5)
    pro_riesgo = puntuar(factores, cohortes, pesos={"tecnico": 0.0, "riesgo": 1.0}, min_cohorte=5)
    mejor_tecnico = max(pro_tecnico.values(), key=lambda p: p.overall).ticker
    mejor_riesgo = max(pro_riesgo.values(), key=lambda p: p.overall).ticker
    assert mejor_tecnico == "T9", "con pesos tecnicos gana el de mas momentum"
    assert mejor_riesgo == "T0", "con pesos de riesgo gana el menos volatil"


def test_el_score_declara_su_cohorte():
    """Un percentil sobre tres empresas no significa lo mismo que sobre cuarenta."""
    factores, cohortes = _cohorte(10, momentum_12_1=[float(i) for i in range(10)])
    p = puntuar(factores, cohortes, min_cohorte=8)["T0"]
    assert p.n_cohorte == 10
    assert p.cohorte_usada.value == "mercado"


def test_un_valor_sin_ningun_factor_no_recibe_score():
    """Mejor sin score que con uno calculado sobre nada."""
    factores = {"T0": dict.fromkeys(DIRECCION), "T1": dict.fromkeys(DIRECCION)}
    p = puntuar(factores, {"T0": "x", "T1": "x"}, min_cohorte=1)
    assert all(v.overall is None for v in p.values())


# ---------------------------------------------------------------------------
# Los cinco perfiles de §18
# ---------------------------------------------------------------------------


def test_los_cinco_perfiles_estan_en_configuracion(cfg):
    modelos = yaml.safe_load((cfg.dir_config / "modelos.yaml").read_text(encoding="utf-8"))[
        "modelos"
    ]
    assert set(modelos) == {"equilibrado", "crecimiento", "valor", "momentum", "bajo_riesgo"}


def test_los_pesos_de_cada_perfil_suman_uno(cfg):
    """Si no suman, el peso relativo de cada pilar deja de ser legible."""
    modelos = yaml.safe_load((cfg.dir_config / "modelos.yaml").read_text(encoding="utf-8"))[
        "modelos"
    ]
    for nombre, modelo in modelos.items():
        assert set(modelo["pilares"]) == set(PILARES), nombre
        assert np.isclose(sum(modelo["pilares"].values()), 1.0), f"{nombre}: pilares"
        assert np.isclose(sum(modelo["grupos"].values()), 1.0), f"{nombre}: grupos"


def test_cada_perfil_prima_lo_que_dice_su_nombre(cfg):
    """Un perfil que no se diferencia de los demas no es un perfil."""
    modelos = yaml.safe_load((cfg.dir_config / "modelos.yaml").read_text(encoding="utf-8"))[
        "modelos"
    ]
    grupos = {k: v["grupos"] for k, v in modelos.items()}
    pilares = {k: v["pilares"] for k, v in modelos.items()}

    assert max(grupos["crecimiento"], key=grupos["crecimiento"].get) == "crecimiento"
    assert max(grupos["valor"], key=grupos["valor"].get) == "valoracion"
    assert max(pilares["momentum"], key=pilares["momentum"].get) == "tecnico"
    assert max(pilares["bajo_riesgo"], key=pilares["bajo_riesgo"].get) == "riesgo"
