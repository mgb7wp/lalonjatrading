"""Analisis de un valor: el endpoint vertebral de §27.

Devuelve de una vez security, precio, fundamentales, tecnico, score con sus
pilares, senal y explicacion, **cada bloque con su disponibilidad y su
frescura**.

## Por que cada bloque se envuelve

El criterio de aceptacion de la fase dice que un pilar no disponible se declara
como tal y **no** se rellena. Un `null` suelto no distingue "no lo sabemos" de
"vale cero", y esa diferencia es justo la que decide si alguien puede fiarse del
numero. Por eso cada bloque viaja con `disponible`, `motivo` cuando no lo esta y
`frescura` cuando si: la respuesta dice lo que sabe y admite lo que no.

Es la misma regla que gobierna la capa LLM ("Informacion no disponible" en lugar
de inventar), aplicada un piso mas abajo, donde de verdad se decide.

## El corte temporal

El parametro `fecha` existe para poder preguntar "que se sabia aquel dia", y es
el sitio exacto donde RT-2 advierte que el sesgo de anticipacion se cuela otra
vez al anadir la capa SaaS: un endpoint que lee la tabla de precios sin corte
devuelve el futuro sin que nadie lo note. **Todas** las consultas de aqui
filtran por esa fecha, y hay un test que lo comprueba bloque a bloque.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Generic, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...db.models import (
    FundamentalSnapshot,
    ModelVersion,
    Price,
    Score,
    Security,
    Signal,
    TechnicalIndicator,
)
from ...db.models.enums import AssetType
from ...db.session import sesion

router = APIRouter(prefix="/stocks", tags=["stocks"])

BD = Annotated[Session, Depends(sesion)]

T = TypeVar("T")

#: Percentiles a partir de los cuales un pilar o sub-score se considera digno de
#: mencion en la explicacion (§28). No son umbrales de decision —de eso se
#: encarga el motor de senales— sino de redaccion: que sale en la lista.
DESTACA_A_FAVOR = 70.0
DESTACA_EN_CONTRA = 30.0

#: Dias hacia atras para "que ha cambiado", igual que en el motor de senales.
DIAS_CAMBIO = 30

#: Nombres de pilar y sub-score tal y como los guarda el esquema.
PILARES = ("fundamental", "technical", "sentiment", "risk")
SUBSCORES = (
    "growth",
    "profitability",
    "financial_health",
    "quality",
    "valuation",
    "momentum",
    "trend",
    "volatility",
    "volume",
)


class Encontrado(BaseModel):
    """Una linea de resultado de busqueda. Lo justo para elegir y navegar."""

    ticker: str
    nombre: str
    mercado: str
    divisa: str
    sector: str | None
    #: Se publica porque importa al elegir: entre la accion local y su ADR de la
    #: misma empresa, la principal es la que de verdad se puede operar (D-12).
    linea_principal: bool


#: Tope de resultados. Una busqueda que devuelve el universo entero no es una
#: busqueda, es un volcado, y ademas tarda.
TOPE_BUSQUEDA = 50


@router.get("", response_model=list[Encontrado], summary="Buscar un valor por ticker o nombre")
def buscar(
    bd: BD,
    q: Annotated[str, Query(min_length=1, max_length=64, description="Ticker o parte del nombre")],
    mercado: Annotated[str | None, Query(description="Acota a un mercado")] = None,
    n: Annotated[int, Query(ge=1, le=TOPE_BUSQUEDA, description="Cuantos resultados")] = 20,
) -> list[Encontrado]:
    """Busca por ticker, nombre o ISIN, sin distinguir mayusculas.

    **Los acentos SI cuentan**: `ilike` no los normaliza. Hacerlo pide la
    extension `unaccent` de Postgres y un indice aparte, y con un universo de
    138 valores no compensa todavia. Se dice aqui en lugar de prometerlo.

    **Se buscan tambien los valores dados de baja.** Alguien puede tener en
    cartera algo que ya no cotiza, y no encontrarlo seria justo el sesgo de
    supervivencia (D-13) trasladado a la interfaz: la busqueda ensenaria solo las
    empresas que sobrevivieron. Lo que si se excluyen son los indices, que no se
    compran.

    El patron va parametrizado y con los comodines escapados: sin eso, un `%` en
    la busqueda del usuario convierte cualquier consulta en un recorrido de la
    tabla entera.
    """
    aguja = q.strip()
    if not aguja:
        return []
    # `\` escapa los comodines de LIKE para que un `%` escrito por el usuario se
    # busque como caracter y no como "todo".
    patron = "%" + aguja.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

    consulta = select(Security).where(
        Security.asset_type != AssetType.INDEX.value,
        or_(
            Security.ticker.ilike(patron, escape="\\"),
            Security.name.ilike(patron, escape="\\"),
            Security.isin.ilike(patron, escape="\\"),
        ),
    )
    if mercado:
        consulta = consulta.where(Security.market_id == mercado)

    # El que empieza por lo buscado va antes que el que solo lo contiene: quien
    # escribe "ACS" quiere ACS.MC y no la tercera empresa cuyo nombre lo lleva
    # dentro. Despues, la linea principal antes que el ADR, y luego alfabetico.
    empieza = func.upper(Security.ticker).startswith(aguja.upper())
    filas = bd.scalars(
        consulta.order_by(
            empieza.desc(),
            Security.is_primary_listing.desc(),
            Security.active.desc(),
            Security.ticker,
        ).limit(n)
    ).all()

    return [
        Encontrado(
            ticker=v.ticker,
            nombre=v.name,
            mercado=v.market_id,
            divisa=v.currency_code,
            sector=v.sector,
            linea_principal=v.is_primary_listing,
        )
        for v in filas
    ]


class Frescura(BaseModel):
    """De cuando es el dato y cuanto ha llovido desde entonces."""

    as_of: dt.date
    dias: int


class Bloque(BaseModel, Generic[T]):
    """Un bloque de la respuesta, que sabe decir que no sabe."""

    disponible: bool
    motivo: str | None = None
    frescura: Frescura | None = None
    datos: T | None = None

    @classmethod
    def falta(cls, motivo: str) -> Bloque[T]:
        return cls(disponible=False, motivo=motivo)

    @classmethod
    def con(cls, datos: T, as_of: dt.date, corte: dt.date) -> Bloque[T]:
        return cls(
            disponible=True,
            datos=datos,
            frescura=Frescura(as_of=as_of, dias=(corte - as_of).days),
        )


class Valor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    name: str
    market_id: str
    currency_code: str
    sector: str | None = None
    active: bool
    #: Se publica para que quien consuma la API pueda excluir del ranking las
    #: lineas secundarias de una misma empresa (D-12) sin pedir otra cosa.
    is_primary_listing: bool


class Precio(BaseModel):
    fecha: dt.date
    cierre: float
    apertura: float | None = None
    maximo: float | None = None
    minimo: float | None = None
    volumen: int | None = None
    fuente: str | None = None


class Fundamental(BaseModel):
    fin_periodo: dt.date
    fecha_publicacion: dt.date
    origen_pit: str
    periodo: str
    ventas: float | None = None
    ebit: float | None = None
    beneficio_neto: float | None = None
    patrimonio_neto: float | None = None
    deuda_neta: float | None = None
    flujo_caja_libre: float | None = None
    roe: float | None = None
    margen_operativo: float | None = None
    divisa_reporte: str | None = None


class Tecnico(BaseModel):
    fecha: dt.date
    rsi_14: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    atr_14: float | None = None
    beta: float | None = None
    fuerza_relativa: float | None = None


class Puntuacion(BaseModel):
    fecha: dt.date
    modelo: str
    overall: float
    cohorte: str
    n_cohorte: int
    pilares: dict[str, float | None]
    #: Por que falta cada pilar ausente. Sin esto, un `null` en `pilares` no
    #: distingue "no hay datos" de un fallo de calculo.
    pilares_no_disponibles: dict[str, str]
    subscores: dict[str, float | None]


class SenalPublicada(BaseModel):
    fecha: dt.date
    senal: str
    motivo: str
    detalle: dict | None = None
    regimen: str | None = None
    confianza: float | None = None
    horizonte_dias: int | None = None
    #: Obligatorios para publicar una recomendacion general en la UE.
    autor: str
    metodologia: str | None = None


class Factor(BaseModel):
    nombre: str
    valor: float
    nivel: str


class Explicacion(BaseModel):
    """§28: que sostiene el score y que lo lastra, y que ha cambiado."""

    a_favor: list[Factor]
    en_contra: list[Factor]
    cambio_30d: dict[str, float]
    #: Los pilares que no se pueden comparar porque falta uno de los dos
    #: extremos. Declararlos evita leer su ausencia como "no cambio".
    cambio_no_comparable: list[str]


class Analisis(BaseModel):
    ticker: str
    fecha_corte: dt.date
    valor: Valor
    precio: Bloque[Precio]
    fundamental: Bloque[Fundamental]
    tecnico: Bloque[Tecnico]
    score: Bloque[Puntuacion]
    senal: Bloque[SenalPublicada]
    explicacion: Bloque[Explicacion]
    prediccion: Bloque[dict]


def _f(valor) -> float | None:
    return None if valor is None else float(valor)


def _bloque_precio(bd: Session, valor: Security, corte: dt.date) -> Bloque[Precio]:
    fila = bd.scalars(
        select(Price)
        .where(Price.security_id == valor.id, Price.date <= corte)
        .order_by(Price.date.desc())
        .limit(1)
    ).first()
    if fila is None:
        return Bloque.falta("no hay precios cargados para este valor")
    return Bloque.con(
        Precio(
            fecha=fila.date,
            cierre=float(fila.close),
            apertura=_f(fila.open),
            maximo=_f(fila.high),
            minimo=_f(fila.low),
            volumen=fila.volume,
            fuente=fila.source,
        ),
        fila.date,
        corte,
    )


def _bloque_fundamental(bd: Session, valor: Security, corte: dt.date) -> Bloque[Fundamental]:
    # Por `publication_date` y no por `period_end`: lo que importa es cuando se
    # supo, no a que ejercicio se refiere. Un cierre de diciembre publicado en
    # marzo no se conocia en enero.
    fila = bd.scalars(
        select(FundamentalSnapshot)
        .where(
            FundamentalSnapshot.security_id == valor.id,
            FundamentalSnapshot.publication_date <= corte,
        )
        .order_by(FundamentalSnapshot.publication_date.desc())
        .limit(1)
    ).first()
    if fila is None:
        return Bloque.falta("no hay cuentas publicadas antes de la fecha de corte")
    return Bloque.con(
        Fundamental(
            fin_periodo=fila.period_end,
            fecha_publicacion=fila.publication_date,
            origen_pit=fila.pit_origin,
            periodo=fila.period,
            ventas=_f(fila.revenue),
            ebit=_f(fila.ebit),
            beneficio_neto=_f(fila.net_income),
            patrimonio_neto=_f(fila.equity),
            deuda_neta=_f(fila.net_debt),
            flujo_caja_libre=_f(fila.free_cash_flow),
            roe=_f(fila.roe),
            margen_operativo=_f(fila.operating_margin),
            divisa_reporte=fila.reporting_currency,
        ),
        fila.publication_date,
        corte,
    )


def _bloque_tecnico(bd: Session, valor: Security, corte: dt.date) -> Bloque[Tecnico]:
    fila = bd.scalars(
        select(TechnicalIndicator)
        .where(TechnicalIndicator.security_id == valor.id, TechnicalIndicator.date <= corte)
        .order_by(TechnicalIndicator.date.desc())
        .limit(1)
    ).first()
    if fila is None:
        return Bloque.falta("no hay indicadores calculados para este valor")
    return Bloque.con(
        Tecnico(
            fecha=fila.date,
            rsi_14=_f(fila.rsi_14),
            sma_50=_f(fila.sma_50),
            sma_200=_f(fila.sma_200),
            atr_14=_f(fila.atr_14),
            beta=_f(fila.beta),
            fuerza_relativa=_f(fila.relative_strength),
        ),
        fila.date,
        corte,
    )


def _score_en(bd: Session, valor: Security, modelo: str, corte: dt.date) -> Score | None:
    return bd.scalars(
        select(Score)
        .join(ModelVersion, ModelVersion.id == Score.model_version_id)
        .where(Score.security_id == valor.id, Score.date <= corte, ModelVersion.name == modelo)
        .order_by(Score.date.desc())
        .limit(1)
    ).first()


def _bloque_score(fila: Score | None, modelo: str, corte: dt.date) -> Bloque[Puntuacion]:
    if fila is None or fila.overall is None:
        return Bloque.falta(f"el valor no está puntuado por el modelo '{modelo}'")

    disponibles = set(fila.available_pillars or [])
    pilares = {p: _f(getattr(fila, p)) for p in PILARES}
    # Un pilar ausente se DECLARA; no se rellena con 50 ni con 0. Imputar la
    # media convierte "no lo sabemos" en "es del monton", que es una afirmacion
    # distinta y ademas falsa.
    no_disponibles = {
        p: ("sin datos suficientes en la cohorte" if p not in disponibles else "sin calcular")
        for p, v in pilares.items()
        if v is None
    }
    return Bloque.con(
        Puntuacion(
            fecha=fila.date,
            modelo=modelo,
            overall=float(fila.overall),
            cohorte=fila.cohort_used,
            n_cohorte=fila.n_cohort,
            pilares=pilares,
            pilares_no_disponibles=no_disponibles,
            subscores={s: _f(getattr(fila, s)) for s in SUBSCORES},
        ),
        fila.date,
        corte,
    )


def _bloque_senal(
    bd: Session, valor: Security, modelo: str, corte: dt.date
) -> Bloque[SenalPublicada]:
    fila = bd.scalars(
        select(Signal)
        .join(ModelVersion, ModelVersion.id == Signal.model_version_id)
        .where(Signal.security_id == valor.id, Signal.date <= corte, ModelVersion.name == modelo)
        .order_by(Signal.date.desc())
        .limit(1)
    ).first()
    if fila is None:
        return Bloque.falta("no se ha emitido ninguna señal para este valor")
    return Bloque.con(
        SenalPublicada(
            fecha=fila.date,
            senal=fila.signal,
            motivo=fila.reason,
            detalle=fila.reason_detail,
            regimen=fila.market_regime,
            confianza=_f(fila.confidence),
            horizonte_dias=fila.horizon_days,
            autor=fila.author,
            metodologia=fila.methodology_ref,
        ),
        fila.date,
        corte,
    )


def _bloque_explicacion(
    bd: Session, valor: Security, actual: Score | None, modelo: str, corte: dt.date
) -> Bloque[Explicacion]:
    if actual is None:
        return Bloque.falta("sin score no hay nada que explicar")

    a_favor: list[Factor] = []
    en_contra: list[Factor] = []
    for nombre in PILARES + SUBSCORES:
        v = _f(getattr(actual, nombre, None))
        if v is None:
            continue
        nivel = "pilar" if nombre in PILARES else "subscore"
        if v >= DESTACA_A_FAVOR:
            a_favor.append(Factor(nombre=nombre, valor=v, nivel=nivel))
        elif v <= DESTACA_EN_CONTRA:
            en_contra.append(Factor(nombre=nombre, valor=v, nivel=nivel))
    a_favor.sort(key=lambda f: -f.valor)
    en_contra.sort(key=lambda f: f.valor)

    previo = _score_en(bd, valor, modelo, actual.date - dt.timedelta(days=DIAS_CAMBIO))
    cambio: dict[str, float] = {}
    no_comparable: list[str] = []
    for nombre in ("overall", *PILARES):
        ahora = _f(getattr(actual, nombre, None))
        antes = _f(getattr(previo, nombre, None)) if previo is not None else None
        if ahora is None or antes is None:
            no_comparable.append(nombre)
        else:
            cambio[nombre] = round(ahora - antes, 2)

    return Bloque.con(
        Explicacion(
            a_favor=a_favor,
            en_contra=en_contra,
            cambio_30d=cambio,
            cambio_no_comparable=no_comparable,
        ),
        actual.date,
        corte,
    )


@router.get(
    "/{ticker}/analysis",
    response_model=Analisis,
    summary="Analisis completo de un valor (§27)",
)
def analisis(
    ticker: str,
    bd: BD,
    fecha: Annotated[
        dt.date | None,
        Query(description="Corte temporal: nada posterior a esta fecha entra en la respuesta"),
    ] = None,
    modelo: Annotated[str, Query(description="Perfil de pesos de §18")] = "equilibrado",
) -> Analisis:
    corte = fecha or dt.date.today()

    valor = bd.scalars(select(Security).where(Security.ticker == ticker.upper())).first()
    if valor is None:
        raise HTTPException(status_code=404, detail=f"no existe el valor {ticker}")

    puntuacion = _score_en(bd, valor, modelo, corte)

    return Analisis(
        ticker=valor.ticker,
        fecha_corte=corte,
        valor=Valor.model_validate(valor),
        precio=_bloque_precio(bd, valor, corte),
        fundamental=_bloque_fundamental(bd, valor, corte),
        tecnico=_bloque_tecnico(bd, valor, corte),
        score=_bloque_score(puntuacion, modelo, corte),
        senal=_bloque_senal(bd, valor, modelo, corte),
        explicacion=_bloque_explicacion(bd, valor, puntuacion, modelo, corte),
        # D-7 aplaza el modelo estadistico hasta tener universo e historico
        # suficientes. Se declara ausente en lugar de omitir el bloque: quien
        # consume la API tiene que poder ver que existe y por que esta vacio.
        prediccion=Bloque.falta(
            "sin modelo estadístico: aplazado por D-7 hasta tener un universo de "
            "1.000 valores y 15 años de histórico"
        ),
    )
