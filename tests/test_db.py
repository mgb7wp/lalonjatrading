"""Tests del esquema (FASE 2).

Los que necesitan Postgres se saltan si no hay uno accesible, para que la suite
siga corriendo en un portatil sin Docker. Los estructurales —los que solo miran
los metadatos de SQLAlchemy— corren siempre.

La base de datos de pruebas se recrea entera en cada sesion, asi que el test
comprueba de verdad lo que pide el criterio de aceptacion de la FASE 2:
**la migracion se aplica desde cero sobre una base de datos limpia**.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from backend.db.models import Base, FundamentalSnapshot, Market, ModelVersion, Score, Security
from backend.db.models.enums import Cohort, ModelKind, Period, PitOrigin

#: Postgres trunca los identificadores a 63 caracteres.
MAX_IDENTIFICADOR = 63

# ---------------------------------------------------------------------------
# Estructurales: sin base de datos
# ---------------------------------------------------------------------------


def _identificadores():
    for tabla in Base.metadata.tables.values():
        yield tabla.name, tabla.name
        for col in tabla.columns:
            yield tabla.name, col.name
        for con in tabla.constraints:
            if isinstance(con.name, str):
                yield tabla.name, con.name
        for idx in tabla.indexes:
            if isinstance(idx.name, str):
                yield tabla.name, idx.name


def test_ningun_identificador_pasa_de_63_caracteres():
    """Postgres los trunca, y dos nombres truncados iguales chocan.

    El fallo no aparece al escribir el modelo sino al generar la migracion, y el
    mensaje no dice que constraint es. Mejor cazarlo aqui.
    """
    largos = [
        (tabla, nombre, len(nombre))
        for tabla, nombre in _identificadores()
        if len(nombre) > MAX_IDENTIFICADOR
    ]
    assert not largos, f"identificadores demasiado largos: {largos}"


def test_toda_serie_tiene_clave_natural_unica():
    """Sin clave natural no hay UPSERT, y sin UPSERT no hay idempotencia (D-9)."""
    esperadas = {
        "price": {"security_id", "date"},
        "fundamental_snapshot": {"security_id", "period_end", "period"},
        "technical_indicator": {"security_id", "date"},
        "fx_rate": {"base_currency", "quote_currency", "date"},
        "score": {"security_id", "date", "model_version_id"},
        "signal": {"security_id", "date", "model_version_id"},
    }
    for tabla, columnas in esperadas.items():
        t = Base.metadata.tables[tabla]
        claves = [set(t.primary_key.columns.keys())]
        claves += [
            set(c.columns.keys()) for c in t.constraints if isinstance(c, sa.UniqueConstraint)
        ]
        assert columnas in claves, f"{tabla} no tiene clave unica sobre {columnas}"


def test_un_score_exige_version_de_modelo():
    """Comprobado en el modelo, no solo en la migracion."""
    columna = Base.metadata.tables["score"].c.model_version_id
    assert not columna.nullable
    assert columna.foreign_keys, "model_version_id debe ser clave ajena"


def test_un_fundamental_exige_fecha_de_publicacion():
    """Sin ella no se puede saber que se sabia cuando."""
    assert not Base.metadata.tables["fundamental_snapshot"].c.publication_date.nullable


def test_price_esta_particionada_por_fecha():
    opciones = Base.metadata.tables["price"].dialect_options["postgresql"]
    assert opciones["partition_by"] == "RANGE (date)"


# ---------------------------------------------------------------------------
# Integracion: con Postgres
# ---------------------------------------------------------------------------


def test_la_migracion_crea_las_29_tablas(engine):
    with engine.connect() as c:
        reales = set(
            c.scalars(
                sa.text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                    "AND tablename NOT LIKE 'price_p%'"
                )
            )
        )
    esperadas = set(Base.metadata.tables) | {"alembic_version"}
    assert esperadas == reales


def test_price_se_crea_particionada_y_con_sus_particiones(engine):
    with engine.connect() as c:
        tipo = c.scalar(sa.text("SELECT relkind FROM pg_class WHERE relname='price'"))
        particiones = c.scalar(
            sa.text("SELECT count(*) FROM pg_class WHERE relname LIKE 'price_p%' AND relkind='r'")
        )
    assert tipo == "p", "price deberia ser una tabla particionada"
    assert particiones >= 30


def test_la_carga_de_referencia_es_idempotente(sesion):
    """Ejecutarla dos veces no duplica ni cambia nada (decision D-9)."""
    from backend.db.seed import cargar

    primera = cargar(sesion)
    sesion.flush()
    tras_primera = sesion.scalar(sa.select(sa.func.count()).select_from(Security))

    segunda = cargar(sesion)
    sesion.flush()
    tras_segunda = sesion.scalar(sa.select(sa.func.count()).select_from(Security))

    assert primera.mercados == segunda.mercados == 5
    assert tras_primera == tras_segunda, "recargar no puede duplicar"
    # La tabla guarda el universo y ademas los indices de referencia, que son
    # valores de tipo `index`: se cuentan aparte porque no compiten en rankings.
    assert tras_primera == primera.valores + primera.indices
    assert primera.indices == 5, "un indice por mercado"
    sesion.commit()


def test_los_cinco_mercados_quedan_cargados_con_su_calendario(sesion):
    from backend.db.seed import cargar

    cargar(sesion)
    sesion.flush()

    mercados = {m.id: m for m in sesion.scalars(sa.select(Market))}
    assert {"us", "es", "br", "in"} <= set(mercados)
    assert mercados["in"].trading_calendar == "XBOM"
    assert mercados["in"].timezone == "Asia/Kolkata"
    assert mercados["br"].currency_code == "BRL"
    # El huso sale del calendario, no de un YAML donde poder equivocarse.
    assert mercados["es"].timezone == "Europe/Madrid"


def test_un_mercado_sin_metadatos_falla_al_cargar(sesion):
    """Dar de alta un mercado a medias tiene que doler al cargar, no despues."""
    from estrategia import config as core_config

    from backend.db.seed import ReferenciaIncompleta, cargar

    cfg = core_config.cargar(core_config.DIR_CONFIG_POR_DEFECTO)
    referencia = {"paises": {}, "divisas": {}, "mercados": {"es": {}}, "bolsas": []}
    with pytest.raises(ReferenciaIncompleta) as exc:
        cargar(sesion, cfg=cfg, referencia=referencia)
    assert "us" in str(exc.value)


def _valor(sesion) -> Security:
    from backend.db.seed import cargar

    cargar(sesion)
    sesion.flush()
    return sesion.scalars(sa.select(Security).limit(1)).one()


def _modelo(sesion) -> ModelVersion:
    mv = ModelVersion(name="equilibrado", version="0.1.0", kind=ModelKind.RULES.value)
    sesion.add(mv)
    sesion.flush()
    return mv


def test_no_se_puede_guardar_un_score_sin_version_de_modelo(sesion):
    """El criterio de aceptacion de la FASE 2, y la defensa contra el model drift.

    Si esto se pudiera, dentro de seis meses habria puntuaciones de las que
    nadie sabria decir como salieron, que es exactamente lo que §8 del encargo
    quiere evitar.
    """
    valor = _valor(sesion)
    sesion.add(
        Score(
            security_id=valor.id,
            date=dt.date(2024, 6, 3),
            model_version_id=None,
            overall=Decimal("87.00"),
            cohort_used=Cohort.MARKET_SECTOR.value,
            n_cohort=24,
        )
    )
    with pytest.raises(IntegrityError):
        sesion.flush()


def test_un_score_fuera_de_0_100_no_entra(sesion):
    valor, modelo = _valor(sesion), _modelo(sesion)
    sesion.add(
        Score(
            security_id=valor.id,
            date=dt.date(2024, 6, 3),
            model_version_id=modelo.id,
            overall=Decimal("140.00"),
            cohort_used=Cohort.MARKET.value,
            n_cohort=24,
        )
    )
    with pytest.raises(IntegrityError):
        sesion.flush()


def test_un_pilar_no_disponible_se_guarda_como_nulo(sesion):
    """Un pilar sin datos es NULL, nunca un 50 'neutro' (decision D-8).

    Imputar un valor medio no es conservador: mueve el ranking con un dato que
    nadie ha medido.
    """
    valor, modelo = _valor(sesion), _modelo(sesion)
    score = Score(
        security_id=valor.id,
        date=dt.date(2024, 6, 3),
        model_version_id=modelo.id,
        overall=Decimal("72.50"),
        fundamental=Decimal("80.00"),
        technical=Decimal("65.00"),
        sentiment=None,
        risk=Decimal("55.00"),
        cohort_used=Cohort.MARKET_SECTOR.value,
        n_cohort=24,
        available_pillars=["fundamental", "technical", "risk"],
    )
    sesion.add(score)
    sesion.flush()
    assert score.sentiment is None
    assert "sentiment" not in score.available_pillars


def test_un_fundamental_publicado_antes_de_cerrar_el_periodo_no_entra(sesion):
    """Publicar antes de cerrar el trimestre es imposible: es un mapeo roto.

    Y de los que no se notan: el dato parece razonable y solo adelanta la
    informacion unos meses, que es justo lo que infla un backtest.
    """
    valor = _valor(sesion)
    sesion.add(
        FundamentalSnapshot(
            security_id=valor.id,
            period_end=dt.date(2024, 12, 31),
            period=Period.ANNUAL.value,
            publication_date=dt.date(2024, 6, 1),
            publication_date_origin="real",
            pit_origin=PitOrigin.CAPTURED.value,
            source="test",
            downloaded_at=dt.date(2025, 1, 1),
        )
    )
    with pytest.raises(IntegrityError):
        sesion.flush()


def test_dos_precios_del_mismo_dia_chocan(sesion):
    """La clave natural que hace posible el UPSERT del pipeline."""
    valor = _valor(sesion)
    fila = {
        "security_id": valor.id,
        "date": dt.date(2024, 6, 3),
        "close": Decimal("10.5"),
        "source": "test",
        "downloaded_at": dt.date(2024, 6, 4),
    }
    sesion.execute(sa.insert(Base.metadata.tables["price"]).values(fila))
    sesion.flush()
    with pytest.raises(IntegrityError):
        sesion.execute(sa.insert(Base.metadata.tables["price"]).values(fila))
        sesion.flush()


def test_un_precio_va_a_la_particion_de_su_ano(sesion):
    valor = _valor(sesion)
    sesion.execute(
        sa.insert(Base.metadata.tables["price"]).values(
            security_id=valor.id,
            date=dt.date(2021, 3, 15),
            close=Decimal("10.5"),
            source="test",
            downloaded_at=dt.date(2021, 3, 16),
        )
    )
    sesion.flush()
    n = sesion.scalar(sa.text("SELECT count(*) FROM price_p2021"))
    assert n == 1


def test_una_fecha_fuera_del_rango_de_particiones_falla_en_voz_alta(sesion):
    """Sin particion por defecto a proposito.

    Una fecha de 1899 es un error de mapeo del proveedor. Un cajon de sastre la
    aceptaria y nadie volveria a mirarla.
    """
    valor = _valor(sesion)
    with pytest.raises(sa.exc.DatabaseError):
        sesion.execute(
            sa.insert(Base.metadata.tables["price"]).values(
                security_id=valor.id,
                date=dt.date(1899, 1, 2),
                close=Decimal("1"),
                source="test",
                downloaded_at=dt.date(2024, 1, 1),
            )
        )
        sesion.flush()


def test_el_correo_es_unico_sin_distinguir_mayusculas(sesion):
    """Si no, Ana@x.com y ana@x.com son dos cuentas y la segunda no recupera."""
    from backend.db.models import User

    sesion.add(User(email="Ana@Ejemplo.com", password_hash="x"))
    sesion.flush()
    sesion.add(User(email="ana@ejemplo.com", password_hash="y"))
    with pytest.raises(IntegrityError):
        sesion.flush()
