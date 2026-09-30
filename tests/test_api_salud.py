"""`/health/data` vigila tambien scores, senales y divisas (tarea S1).

El 22/09/2026 los rankings ensenaban scores viejos y nada aviso: `/health/data`
solo miraba precios y fundamentales. Estos tests fijan lo que tiene que pasar:

1. Un mercado sin scores del ultimo dia que tuvo que haberlos sale rancio,
   aunque solo haya pasado un dia.
2. Un festivo en que no puntua nadie (Viernes Santo) no es un fallo.
3. Un dato posterior al dia de la comprobacion no cuenta.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from backend.api.v1 import health
from backend.db.models import ModelVersion, Score, Security, Signal
from backend.db.models.enums import AssetType, Cohort, ModelKind, SignalType
from backend.db.models.market_data import FxRate
from backend.db.session import sesion as dependencia_sesion
from backend.main import crear_app

CALENDARIOS = (("br", "BVMF"), ("de", "XETR"), ("es", "XMAD"), ("in", "XBOM"), ("us", "XNYS"))

#: Martes despues de Pascua de 2025. El lunes negocio Nueva York, asi que tenia
#: que haber scores del lunes; el BCE no publico ni el viernes ni el lunes, asi
#: que el ultimo tipo esperado es el del jueves.
HOY = dt.date(2025, 4, 22)
LUNES = dt.date(2025, 4, 21)
JUEVES = dt.date(2025, 4, 17)
VERSION = "0.0.9-salud"
FUENTE = "prueba-salud"


# --- el dia esperado, sin base de datos ------------------------------------


@pytest.mark.parametrize(
    ("hoy", "esperado"),
    [
        (dt.date(2026, 9, 30), dt.date(2026, 9, 29)),  # miercoles: el martes
        (dt.date(2026, 9, 28), dt.date(2026, 9, 25)),  # lunes: el viernes
        (dt.date(2025, 4, 19), JUEVES),  # sabado de Pascua: el Viernes Santo no puntua
        (dt.date(2025, 4, 21), JUEVES),  # Lunes de Pascua, antes de puntuar
        (HOY, LUNES),  # Nueva York abrio el Lunes de Pascua
        (dt.date(2025, 12, 26), dt.date(2025, 12, 24)),  # el 25 no negocia nadie
    ],
)
def test_el_dia_esperado_de_scores_salta_los_dias_sin_ningun_mercado(hoy, esperado):
    assert health.dia_esperado_scores(CALENDARIOS, hoy) == esperado


@pytest.mark.parametrize(
    ("hoy", "esperado"),
    [
        (dt.date(2026, 9, 30), dt.date(2026, 9, 29)),
        (dt.date(2026, 9, 28), dt.date(2026, 9, 25)),
        (HOY, JUEVES),  # ni Viernes Santo ni Lunes de Pascua
        (dt.date(2025, 12, 29), dt.date(2025, 12, 24)),  # ni el 25 ni el 26
        (dt.date(2026, 1, 2), dt.date(2025, 12, 31)),  # ni el 1 de enero
        (dt.date(2026, 5, 4), dt.date(2026, 4, 30)),  # ni el 1 de mayo
    ],
)
def test_el_dia_esperado_de_divisas_sigue_el_calendario_del_bce(hoy, esperado):
    assert health.dia_esperado_divisas(hoy) == esperado


# --- el endpoint, con base de datos ----------------------------------------


def _analizables(s, mercado):
    return s.scalars(
        sa.select(Security).where(
            Security.market_id == mercado,
            Security.active.is_(True),
            Security.asset_type != AssetType.INDEX.value,
        )
    ).all()


def _puntuar(s, valores, mv, fecha):
    for v in valores:
        s.add(
            Score(
                security_id=v.id,
                date=fecha,
                model_version_id=mv.id,
                overall=50,
                cohort_used=Cohort.MARKET.value,
                n_cohort=10,
            )
        )


def _senalar(s, valores, mv, fecha):
    for v in valores:
        s.add(
            Signal(
                security_id=v.id,
                date=fecha,
                model_version_id=mv.id,
                signal=SignalType.HOLD.value,
                reason="prueba",
            )
        )


def _tipo(s, divisa, fecha):
    s.add(FxRate(base_currency="EUR", quote_currency=divisa, date=fecha, rate=1, source=FUENTE))


@pytest.fixture
def salud(bd_con_referencia, monkeypatch):
    """Espana al dia; EE. UU. con los scores del jueves; divisas a medias.

    Devuelve los conjuntos de `/health/data` indexados por (dataset, clave).
    """
    monkeypatch.setattr(health, "_hoy", lambda: HOY)
    with sa.orm.Session(bd_con_referencia) as s:
        mv = ModelVersion(name="equilibrado", version=VERSION, kind=ModelKind.RULES.value)
        s.add(mv)
        s.flush()
        es, us = _analizables(s, "es"), _analizables(s, "us")
        _puntuar(s, es, mv, LUNES)
        _senalar(s, es, mv, LUNES)
        _puntuar(s, us, mv, JUEVES)
        # Posterior al dia de la comprobacion: no puede hacer fresco a EE. UU.
        _puntuar(s, us, mv, HOY + dt.timedelta(days=1))
        _tipo(s, "USD", JUEVES)
        _tipo(s, "INR", JUEVES - dt.timedelta(days=1))
        _tipo(s, "BRL", HOY + dt.timedelta(days=1))
        s.commit()

    app = crear_app()

    def sesion_de_prueba():
        with sa.orm.Session(bd_con_referencia) as s:
            yield s

    app.dependency_overrides[dependencia_sesion] = sesion_de_prueba
    cuerpo = TestClient(app).get("/api/v1/health/data").json()
    yield cuerpo, {(d["dataset"], d["market_id"] or d["currency"]): d for d in cuerpo["datasets"]}

    with sa.orm.Session(bd_con_referencia) as s:
        for tabla in ("score", "signal"):
            s.execute(
                sa.text(
                    f"DELETE FROM {tabla} WHERE model_version_id IN "
                    "(SELECT id FROM model_version WHERE version = :v)"
                ),
                {"v": VERSION},
            )
        s.execute(sa.text("DELETE FROM model_version WHERE version = :v"), {"v": VERSION})
        s.execute(sa.text("DELETE FROM fx_rate WHERE source = :f"), {"f": FUENTE})
        s.commit()


def test_un_mercado_con_los_scores_del_ultimo_dia_esta_al_dia(salud):
    _, d = salud
    for conjunto in ("scores", "senales"):
        es = d[(conjunto, "es")]
        assert es["is_stale"] is False, conjunto
        assert es["last_data_date"] == LUNES.isoformat()
        assert es["coverage"] == 1.0


def test_un_dia_sin_puntuar_basta_para_que_salga_rancio(salud):
    """Lo del 22/09: los rankings con scores viejos y nadie avisado."""
    cuerpo, d = salud
    us = d[("scores", "us")]
    assert us["is_stale"] is True
    assert us["last_data_date"] == JUEVES.isoformat(), "el del miercoles que viene no cuenta"
    assert us["days_behind"] == 5
    assert "scores/us" in cuerpo["stale"]
    assert cuerpo["estado"] != "ok"


def test_un_mercado_sin_ningun_score_sale_rancio_y_sin_fecha(salud):
    """Es lo que paso con Espana, Alemania e India: datos, y ni un score."""
    _, d = salud
    de = d[("scores", "de")]
    assert de["is_stale"] is True
    assert de["last_data_date"] is None
    assert de["securities_covered"] == 0
    assert de["securities_expected"] > 0


def test_senales_se_vigilan_aparte_de_los_scores(salud):
    """R1: la tarea puntuaba y no guardaba las senales. Con scores al dia."""
    _, d = salud
    assert d[("senales", "us")]["is_stale"] is True


def test_las_divisas_se_vigilan_por_moneda(salud):
    cuerpo, d = salud
    assert d[("divisas", "USD")]["is_stale"] is False, "el BCE no publico ni viernes ni lunes"
    assert d[("divisas", "USD")]["market_id"] is None
    assert d[("divisas", "INR")]["is_stale"] is True
    assert d[("divisas", "BRL")]["is_stale"] is True, "un tipo posterior a hoy no cuenta"
    assert d[("divisas", "BRL")]["last_data_date"] is None
    assert "divisas/INR" in cuerpo["stale"]
    assert ("divisas", "EUR") not in d, "la divisa base no tiene tipo"
