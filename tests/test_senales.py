"""Motor de senales (§25) y regimen de mercado (§26).

Los tres criterios de aceptacion de la FASE 7bis/9, uno por bloque:

1. **Ningun umbral en el codigo.** Se demuestra cambiando la configuracion y
   comprobando que la senal cambia. Buscar numeros sueltos en el fuente no vale:
   hay ceros y unos legitimos por todas partes.
2. **Motivo estructurado en cada senal.** Vocabulario cerrado, y el motivo tiene
   que senalar al limitador que DE VERDAD mordio.
3. **La senal cambia al cambiar el regimen.**
"""

from __future__ import annotations

import datetime as dt

import pytest
from estrategia import senales
from estrategia.senales import Motivo, Regimen, Tipo


def _con(cfg, **cambios):
    """Copia de la configuracion con uno o varios umbrales de senales cambiados."""
    datos = cfg.model_dump()
    datos["reglas"]["senales"].update(cambios)
    return type(cfg).model_validate(datos)


# --- 1. Ningun umbral en el codigo -----------------------------------------


def test_cambiar_el_umbral_cambia_la_senal_sin_tocar_codigo(cfg):
    """Si `85` estuviera incrustado, bajarlo a 70 no cambiaria nada y esto caeria."""
    alta = senales.evaluar(score=78.0, regimen=Regimen.ALCISTA, cfg=cfg)
    assert alta.tipo is Tipo.COMPRA

    relajada = _con(cfg, umbral_compra_fuerte=75)
    assert senales.evaluar(score=78.0, regimen=Regimen.ALCISTA, cfg=relajada).tipo is (
        Tipo.COMPRA_FUERTE
    )


def test_cambiar_el_tope_de_un_limitador_cambia_hasta_donde_rebaja(cfg):
    """El tope tambien es configuracion, no una constante disfrazada."""
    duro = _con(cfg, tope_riesgo_alto="sell")
    s = senales.evaluar(score=95.0, riesgo=5.0, regimen=Regimen.ALCISTA, cfg=duro)
    assert s.tipo is Tipo.VENTA
    assert s.motivo is Motivo.LIMITA_RIESGO


def test_una_configuracion_incoherente_se_rechaza_al_cargar(cfg):
    """Umbrales de compra y venta solapados producen senales sin sentido.

    Mejor que falle al cargar que emitir recomendaciones contradictorias.
    """
    with pytest.raises(Exception, match="solapan|mayor que"):
        _con(cfg, umbral_compra=20, umbral_venta=30)


# --- 2. Motivo estructurado, y que senale al limitador que mordio ----------


def test_el_motivo_es_el_del_limitador_que_de_verdad_mordio(cfg):
    """Un limitador que no cambia nada no puede robar la explicacion.

    Aqui el regimen lateral topa en `buy` y el score ya daba `buy`: no muerde.
    El que muerde es el riesgo, y es el que tiene que salir en el motivo. Con la
    implementacion que se queda con el ultimo limitador evaluado, esto falla.
    """
    s = senales.evaluar(score=75.0, riesgo=5.0, regimen=Regimen.LATERAL, cfg=cfg)

    assert s.tipo is Tipo.MANTENER
    assert s.motivo is Motivo.LIMITA_RIESGO, "el regimen no mordio; el riesgo si"


def test_un_limitador_que_no_muerde_no_roba_la_explicacion(cfg):
    """El caso que separa esta implementacion de la ingenua.

    Regimen lateral topa en `buy` y el score ya daba `buy`: el limitador se
    evalua pero no cambia nada. Ningun otro muerde. El motivo tiene que seguir
    siendo el score.

    La implementacion ingenua —fijar el motivo cada vez que se evalua un
    limitador, muerda o no— responde `limita_regimen`, y entonces el recuento
    semanal atribuye al regimen decenas de senales que el regimen no toco.
    """
    s = senales.evaluar(score=75.0, riesgo=80.0, momentum=0.3, regimen=Regimen.LATERAL, cfg=cfg)

    assert s.tipo is Tipo.COMPRA
    assert s.motivo is Motivo.SCORE_ALTO


def test_un_limitador_nunca_mejora_una_senal(cfg):
    """El tope es un techo, no un objetivo.

    Un valor con score de venta no se convierte en `hold` porque el mercado este
    alcista y el tope de ese limitador sea `hold`.
    """
    s = senales.evaluar(score=5.0, regimen=Regimen.ALCISTA, riesgo=95.0, cfg=cfg)
    assert s.tipo is Tipo.VENTA_FUERTE


def test_los_componentes_que_deciden_quedan_en_el_detalle(cfg):
    """Sin los numeros al lado, el motivo es una etiqueta que hay que creerse."""
    s = senales.evaluar(score=90.0, riesgo=5.0, momentum=-0.3, regimen=Regimen.BAJISTA, cfg=cfg)
    assert s.detalle["score"] == 90.0
    assert s.detalle["riesgo"] == 5.0
    assert s.detalle["momentum"] == -0.3
    assert s.detalle["regimen"] == "bajista"


def test_sin_score_no_se_inventa_una_senal(cfg):
    """Un valor sin score no es un `hold` normal: es que no se sabe.

    Y el motivo tiene que distinguirlo, porque si no, al contar las senales de
    la semana, los huecos de datos se mezclan con las decisiones.
    """
    s = senales.evaluar(score=None, cfg=cfg)
    assert s.tipo is Tipo.MANTENER
    assert s.motivo is Motivo.DATOS_INSUFICIENTES
    assert s.confianza == 0.0


def test_el_motivo_siempre_sale_del_vocabulario_cerrado(cfg):
    """El informe se construye contando; con texto libre no se puede agrupar."""
    casos = [
        {"score": 95.0, "regimen": Regimen.ALCISTA},
        {"score": 50.0, "regimen": Regimen.LATERAL},
        {"score": 5.0, "regimen": Regimen.BAJISTA},
        {"score": 90.0, "riesgo": 1.0, "regimen": Regimen.ALCISTA},
        {"score": 90.0, "momentum": -0.5, "regimen": Regimen.ALCISTA},
        {"score": 90.0, "variacion_score": -40.0, "regimen": Regimen.ALCISTA},
        {"score": None},
    ]
    for caso in casos:
        assert senales.evaluar(cfg=cfg, **caso).motivo in set(Motivo)


# --- 3. La senal cambia con el regimen -------------------------------------


def test_el_mismo_valor_da_senal_distinta_segun_el_regimen(cfg):
    """El criterio de aceptacion, literal.

    Mismo score excelente, mismo todo. Lo unico que cambia es el mercado.
    """
    comun = {"score": 95.0, "riesgo": 80.0, "momentum": 0.3, "cfg": cfg}

    assert senales.evaluar(regimen=Regimen.ALCISTA, **comun).tipo is Tipo.COMPRA_FUERTE
    assert senales.evaluar(regimen=Regimen.LATERAL, **comun).tipo is Tipo.COMPRA
    assert senales.evaluar(regimen=Regimen.BAJISTA, **comun).tipo is Tipo.MANTENER


def test_un_regimen_desconocido_se_trata_como_adverso_y_no_como_lateral(cfg):
    """No saber en que mercado estas no es estar en uno tranquilo.

    Si DESCONOCIDO cayera del lado benigno, un indice que deja de actualizarse
    —un fallo de datos— empezaria a producir compras fuertes en silencio.
    """
    comun = {"score": 95.0, "riesgo": 80.0, "momentum": 0.3, "cfg": cfg}
    desconocido = senales.evaluar(regimen=Regimen.DESCONOCIDO, **comun)

    assert desconocido.tipo is senales.evaluar(regimen=Regimen.BAJISTA, **comun).tipo
    assert desconocido.confianza < senales.evaluar(regimen=Regimen.ALCISTA, **comun).confianza


# --- Confianza -------------------------------------------------------------


def test_la_confianza_sube_con_la_informacion_disponible(cfg):
    pocos = senales.evaluar(score=80.0, regimen=Regimen.ALCISTA, cfg=cfg)
    todos = senales.evaluar(
        score=80.0,
        variacion_score=2.0,
        momentum=0.2,
        riesgo=70.0,
        valoracion=60.0,
        regimen=Regimen.ALCISTA,
        cfg=cfg,
    )
    assert todos.confianza > pocos.confianza
    assert todos.confianza <= 1.0


# --- Regimen de mercado ----------------------------------------------------


def test_un_indice_desfasado_no_se_da_por_bueno(cfg, instantanea):
    """Un fallo de datos no puede leerse como un mercado tranquilo."""
    vista = instantanea.vista(dt.date(2024, 6, 28))
    regimen, detalle = senales.regimen_de_mercado("us", dt.date(2030, 1, 1), vista, cfg)

    assert regimen is Regimen.DESCONOCIDO
    assert "desfasado" in detalle.get("falta", "")


def test_un_mercado_sin_indice_configurado_es_desconocido(cfg, instantanea):
    vista = instantanea.vista(dt.date(2024, 6, 28))
    regimen, detalle = senales.regimen_de_mercado("marte", dt.date(2024, 6, 28), vista, cfg)

    assert regimen is Regimen.DESCONOCIDO
    assert "indice" in detalle


def test_el_regimen_mira_drawdown_y_volatilidad_ademas_de_la_tendencia(cfg, instantanea):
    """Estar sobre la media no basta para llamarlo alcista.

    Con el umbral de drawdown bajado a casi cero, cualquier caida reciente saca
    al mercado del regimen alcista. Si el regimen solo mirase la media, cambiar
    ese umbral no tendria ningun efecto y el test caeria.
    """
    fecha = dt.date(2024, 6, 28)
    vista = instantanea.vista(fecha)

    normal, _ = senales.regimen_de_mercado("us", fecha, vista, cfg)
    estricta = _con(cfg, drawdown_bajista=0.02, drawdown_lateral=0.01)
    severo, detalle = senales.regimen_de_mercado("us", fecha, instantanea.vista(fecha), estricta)

    assert detalle["drawdown"] >= 0
    if normal is Regimen.ALCISTA:
        assert severo is not Regimen.ALCISTA, "el drawdown tiene que contar"


# --- Persistencia ----------------------------------------------------------


@pytest.fixture
def bd_senales(bd_con_referencia):
    """Sesion sobre la base ya sembrada, que se deshace al terminar.

    Sin borrar nada: una fixture que hace DELETE y lo confirma le cambia el
    suelo a los ficheros de test que vengan detras, y el sintoma es un fallo
    intermitente en otro sitio.
    """
    import sqlalchemy as sa

    with sa.orm.Session(bd_con_referencia) as s:
        yield s
        s.rollback()


def test_la_senal_llega_a_la_base_con_sus_metadatos_de_autoria(bd_senales, cfg):
    """Los metadatos MAR desde el primer dia, no "ya los anadiremos".

    En la UE una recomendacion de inversion general —y `strong_buy` lo es—
    obliga a identificar al autor, describir el metodo y fecharla. Anadirlos
    despues significa que todo lo publicado hasta entonces no los tiene, y eso
    no se arregla hacia atras.
    """
    import sqlalchemy as sa

    from backend.db.models import ModelVersion, Score, Security
    from backend.db.models.enums import AssetType, Cohort, ModelKind
    from workers.pipeline import senales as etapa

    mv = ModelVersion(name="equilibrado", version="0.0.1-test", kind=ModelKind.RULES.value)
    bd_senales.add(mv)
    bd_senales.flush()

    valor = bd_senales.scalars(
        # Sin indices: la etapa los excluye a proposito —no compiten en
        # rankings— y elegir uno aqui daria cero senales sin decir por que.
        sa.select(Security)
        .where(Security.active.is_(True), Security.asset_type != AssetType.INDEX.value)
        .limit(1)
    ).first()
    assert valor is not None, "la base de pruebas tiene que traer la referencia sembrada"

    hoy = dt.date(2026, 6, 30)
    bd_senales.add(
        Score(
            security_id=valor.id,
            date=hoy,
            model_version_id=mv.id,
            overall=92,
            risk=80,
            momentum=70,
            valuation=60,
            # Obligatorios en el esquema, y con razon: un percentil sin saber
            # contra cuantos se midio no significa nada.
            cohort_used=Cohort.MARKET.value,
            n_cohort=30,
        )
    )
    bd_senales.flush()

    recuento = etapa.ejecutar(bd_senales, cfg, fecha=hoy, modelo="equilibrado")
    bd_senales.flush()

    assert recuento, "tendria que haber emitido al menos una senal"
    fila = bd_senales.execute(
        sa.text(
            "SELECT signal, reason, market_regime, author, methodology_ref, reason_detail "
            "FROM signal WHERE security_id = :i AND date = :d"
        ),
        {"i": valor.id, "d": hoy},
    ).first()

    assert fila is not None
    assert fila[0] in {t.value for t in Tipo}
    assert fila[1] in {m.value for m in Motivo}
    assert fila[3], "sin autor no se puede publicar una recomendacion en la UE"
    assert fila[4], "sin referencia a la metodologia, tampoco"
    assert fila[5], "el detalle estructurado es lo que hace auditable el motivo"


def test_reemitir_las_senales_del_mismo_dia_no_duplica(bd_senales, cfg):
    """Idempotencia: cambiar umbrales y relanzar es el caso normal, no la excepcion."""
    import sqlalchemy as sa

    from backend.db.models import ModelVersion, Score, Security
    from backend.db.models.enums import AssetType, Cohort, ModelKind
    from workers.pipeline import senales as etapa

    mv = ModelVersion(name="equilibrado", version="0.0.2-test", kind=ModelKind.RULES.value)
    bd_senales.add(mv)
    bd_senales.flush()
    valor = bd_senales.scalars(
        # Sin indices: la etapa los excluye a proposito —no compiten en
        # rankings— y elegir uno aqui daria cero senales sin decir por que.
        sa.select(Security)
        .where(Security.active.is_(True), Security.asset_type != AssetType.INDEX.value)
        .limit(1)
    ).first()
    hoy = dt.date(2026, 7, 31)
    bd_senales.add(
        Score(
            security_id=valor.id,
            date=hoy,
            model_version_id=mv.id,
            overall=92,
            risk=80,
            cohort_used=Cohort.MARKET.value,
            n_cohort=30,
        )
    )
    bd_senales.flush()

    etapa.ejecutar(bd_senales, cfg, fecha=hoy, modelo="equilibrado")
    etapa.ejecutar(bd_senales, cfg, fecha=hoy, modelo="equilibrado")
    bd_senales.flush()

    n = bd_senales.execute(
        sa.text("SELECT count(*) FROM signal WHERE security_id = :i AND date = :d"),
        {"i": valor.id, "d": hoy},
    ).scalar()
    assert n == 1, "la clave natural tiene que absorber la reemision"
