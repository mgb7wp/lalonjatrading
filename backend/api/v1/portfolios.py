"""Carteras (FASE 13): transacciones dentro, todo lo demas derivado.

## La unica cosa que se escribe es la transaccion

No hay endpoint para "poner la cantidad de AAPL a 30". Las posiciones, el coste
medio, el P&L, los pesos y la exposicion salen de recorrer las transacciones en
cada consulta (`backend.carteras.derivar`). Eso es lo que hace que el criterio de
aceptacion de la fase se cumpla por construccion: **corregir una transaccion de
hace ocho meses corrige todo lo que cuelga de ella**, porque no hay nada que
colgar que no se vuelva a calcular.

`portfolio_position` sigue existiendo, pero aqui solo se usa para `target_weight`
—la asignacion OBJETIVO, que si es un dato que alguien decide y no una
consecuencia—. Sus columnas `quantity` y `average_price` no se leen ni se
escriben desde esta API: son la denormalizacion que la fase prohibe.

## El corte temporal tambien vale para una cartera

`GET /portfolios/{id}?fecha=` valora con lo conocido en esa fecha y nada
posterior: ni precios, ni scores, ni transacciones. Sin el corte, "como iba mi
cartera en marzo" se contesta con precios de hoy, que es la misma anticipacion
que RT-2 avisa que la capa SaaS reintroduce.

## La divisa se congela al escribir

El tipo de cambio de una operacion es el del dia en que se ejecuto, y se guarda
con ella. Si quien la registra lo aporta, manda el suyo: lo que de verdad se
pago es lo que puso el broker en el extracto, no el tipo de referencia del BCE.
Si no lo aporta, se busca el del dia en `fx_rate` y se congela. Si no hay
ninguno, la transaccion se RECHAZA en lugar de guardarse con un 1 implicito:
un 1 inventado entre USD y EUR no falla, solo da un P&L equivocado.

## Cartera de otro: 404, no 403

Un 403 sobre la cartera 41 confirma que la cartera 41 existe. Se responde 404
igual que si no existiera, que es lo unico que quien pregunta tiene derecho a
saber.

## Limitacion conocida

`portfolio_transaction.security_id` es obligatorio, asi que una comision de
custodia que no pertenece a ningun valor no se puede registrar todavia: hay que
imputarla al valor al que corresponda. El motor si sabe tratarla
(`Cartera.gastos`); lo que falta es hacer la columna anulable, y eso es una
migracion que no toca esta fase.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...carteras import CERO, Transaccion, derivar, exposicion
from ...db.models import (
    Market,
    ModelVersion,
    Portfolio,
    PortfolioPosition,
    Price,
    Score,
    Security,
    Transaction,
    User,
)
from ...db.models.enums import TransactionType
from ...db.models.market_data import FxRate
from ..deps import BD, Actual, MisLimites, comprobar_cupo

router = APIRouter(prefix="/portfolios", tags=["carteras"])

MODELO_POR_DEFECTO = "equilibrado"


# ---------------------------------------------------------------------------
# Entrada y salida
# ---------------------------------------------------------------------------


class CarteraNueva(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = Field(default=None, max_length=2000)
    divisa_base: str = Field(default="EUR", min_length=3, max_length=3)


class CarteraCambio(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    descripcion: str | None = Field(default=None, max_length=2000)


class CarteraResumen(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    divisa_base: str
    transacciones: int


class TransaccionNueva(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    tipo: TransactionType
    cantidad: Decimal = Field(ge=0)
    precio: Decimal = Field(ge=0)
    comisiones: Decimal = Field(default=Decimal("0"), ge=0)
    impuestos: Decimal = Field(default=Decimal("0"), ge=0)
    fecha: dt.date
    #: Divisa de la operacion. Si falta, la de cotizacion del valor.
    divisa: str | None = Field(default=None, min_length=3, max_length=3)
    #: Tipo de cambio divisa -> divisa base el dia de la operacion. Si falta se
    #: busca en `fx_rate` y se congela.
    fx: Decimal | None = Field(default=None, gt=0)
    nota: str | None = Field(default=None, max_length=2000)


class TransaccionFila(BaseModel):
    id: int
    ticker: str
    tipo: str
    cantidad: Decimal
    precio: Decimal
    comisiones: Decimal
    impuestos: Decimal
    divisa: str
    fx: Decimal | None
    fecha: dt.date
    nota: str | None


class PosicionFila(BaseModel):
    ticker: str
    nombre: str
    sector: str | None
    pais: str | None
    cantidad: Decimal
    coste: Decimal
    coste_medio: Decimal | None
    precio: Decimal | None
    fecha_precio: dt.date | None
    valor: Decimal | None
    no_realizado: Decimal | None
    realizado: Decimal
    dividendos: Decimal
    peso: float | None
    objetivo: float | None = None
    desviacion: float | None = None
    score: float | None = None


class Totales(BaseModel):
    valor: Decimal
    coste: Decimal
    no_realizado: Decimal
    realizado: Decimal
    dividendos: Decimal
    gastos: Decimal
    #: Realizado + no realizado + dividendos - gastos.
    total: Decimal


class Diversificacion(BaseModel):
    """Concentracion medida, no adjetivada.

    `hhi` es la suma de los pesos al cuadrado y `posiciones_efectivas` su
    inverso: una cartera de cuatro posiciones al 25 % da 4, y una de cuatro con
    el 85 % en una da 1,35. Ese segundo numero es el que dice la verdad, y por
    eso se publica en lugar de contar posiciones.
    """

    posiciones: int
    hhi: float | None
    posiciones_efectivas: float | None
    mayor_peso: float | None


class ScoreMedio(BaseModel):
    """Score medio ponderado por peso, con su cobertura al lado.

    `cobertura` es la fraccion del valor de la cartera que si tiene score. Sin
    ella, una cartera con score solo en el 20 % de su valor publica una media
    que parece la de toda la cartera. Los que no tienen score NO se imputan a 50
    (D-8): se quedan fuera y se declara cuanto se han quedado fuera.
    """

    valor: float | None
    cobertura: float
    fecha_datos: dt.date | None


class Valoracion(BaseModel):
    id: int
    nombre: str
    divisa_base: str
    fecha: dt.date
    posiciones: list[PosicionFila]
    totales: Totales
    exposicion_sector: dict[str, float]
    exposicion_pais: dict[str, float]
    diversificacion: Diversificacion
    score_medio: ScoreMedio
    #: Valores en cartera sin precio conocido en la fecha. No se valoran a coste
    #: —eso fingiria que no se han movido—: se declaran y quedan fuera de los
    #: totales de mercado.
    sin_valorar: list[str]


class Objetivo(BaseModel):
    """Asignacion objetivo: ticker -> peso entre 0 y 1."""

    pesos: dict[str, float]


# ---------------------------------------------------------------------------
# Piezas compartidas
# ---------------------------------------------------------------------------


def _mia(bd: Session, usuario: User, cartera_id: int) -> Portfolio:
    """La cartera, si es de quien pregunta. Si no, 404."""
    cartera = bd.scalars(
        select(Portfolio).where(Portfolio.id == cartera_id, Portfolio.user_id == usuario.id)
    ).first()
    if cartera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cartera no encontrada")
    return cartera


def _valor_por_ticker(bd: Session, ticker: str) -> Security:
    valor = bd.scalars(
        select(Security).where(func.upper(Security.ticker) == ticker.upper()).limit(1)
    ).first()
    if valor is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"no conozco el valor {ticker!r}",
        )
    return valor


def _fx_del_dia(bd: Session, divisa: str, base: str, fecha: dt.date) -> Decimal | None:
    """Cambio `divisa -> base` en esa fecha, arrastrando el ultimo conocido.

    `fx_rate` guarda un solo sentido, base -> divisa, y se invierte al leer. Dos
    convenios circulando por el codigo dan carteras mal valoradas que nadie
    detecta porque el numero parece razonable.
    """
    if divisa == base:
        return Decimal("1")
    tasa = bd.scalars(
        select(FxRate.rate)
        .where(
            FxRate.base_currency == base,
            FxRate.quote_currency == divisa,
            FxRate.date <= fecha,
        )
        .order_by(FxRate.date.desc())
        .limit(1)
    ).first()
    if tasa is None or Decimal(tasa) == CERO:
        return None
    return Decimal("1") / Decimal(tasa)


def _ultimos_precios(
    bd: Session, ids: list[int], corte: dt.date
) -> dict[int, tuple[Decimal, dt.date]]:
    """Ultimo cierre de cada valor en o antes del corte. Nunca posterior."""
    if not ids:
        return {}
    ultimo = (
        select(Price.security_id, func.max(Price.date).label("fecha"))
        .where(Price.security_id.in_(ids), Price.date <= corte)
        .group_by(Price.security_id)
        .subquery()
    )
    filas = bd.execute(
        select(Price.security_id, Price.close, Price.date).join(
            ultimo,
            and_(Price.security_id == ultimo.c.security_id, Price.date == ultimo.c.fecha),
        )
    ).all()
    return {sid: (Decimal(cierre), fecha) for sid, cierre, fecha in filas}


def _ultimos_scores(
    bd: Session, ids: list[int], corte: dt.date, modelo: str
) -> tuple[dict[int, float], dt.date | None]:
    """Scores de la ultima fecha puntuada en o antes del corte."""
    if not ids:
        return {}, None
    version = bd.scalars(
        select(ModelVersion.id)
        .where(ModelVersion.name == modelo)
        .order_by(ModelVersion.id.desc())
        .limit(1)
    ).first()
    if version is None:
        return {}, None
    fecha = bd.scalars(
        select(Score.date)
        .where(Score.model_version_id == version, Score.date <= corte)
        .order_by(Score.date.desc())
        .limit(1)
    ).first()
    if fecha is None:
        return {}, None
    filas = bd.execute(
        select(Score.security_id, Score.overall).where(
            Score.model_version_id == version,
            Score.date == fecha,
            Score.security_id.in_(ids),
        )
    ).all()
    return {sid: float(overall) for sid, overall in filas}, fecha


def _a_transaccion(fila: Transaction, ticker: str) -> Transaccion:
    return Transaccion(
        ticker=ticker,
        tipo=fila.transaction_type,
        cantidad=Decimal(fila.quantity),
        precio=Decimal(fila.price),
        comisiones=Decimal(fila.fees or 0),
        impuestos=Decimal(fila.taxes or 0),
        divisa=fila.currency_code,
        fx=Decimal(fila.fx_rate_to_base if fila.fx_rate_to_base is not None else 1),
        fecha=fila.executed_on,
    )


def _resolver(
    bd: Session, cartera: Portfolio, cuerpo: TransaccionNueva
) -> tuple[Security, str, Decimal]:
    """Valor, divisa y cambio congelado de una transaccion que entra."""
    valor = _valor_por_ticker(bd, cuerpo.ticker)
    divisa = (cuerpo.divisa or valor.currency_code).upper()
    if cuerpo.fx is not None:
        return valor, divisa, cuerpo.fx
    fx = _fx_del_dia(bd, divisa, cartera.base_currency, cuerpo.fecha)
    if fx is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"no hay tipo de cambio {divisa} → {cartera.base_currency} en o antes de "
                f"{cuerpo.fecha}; pasa el tuyo en `fx` (el del extracto del bróker)"
            ),
        )
    return valor, divisa, fx


def _fila(t: Transaction, ticker: str) -> TransaccionFila:
    return TransaccionFila(
        id=t.id,
        ticker=ticker,
        tipo=t.transaction_type,
        cantidad=Decimal(t.quantity),
        precio=Decimal(t.price),
        comisiones=Decimal(t.fees or 0),
        impuestos=Decimal(t.taxes or 0),
        divisa=t.currency_code,
        fx=None if t.fx_rate_to_base is None else Decimal(t.fx_rate_to_base),
        fecha=t.executed_on,
        nota=t.note,
    )


# ---------------------------------------------------------------------------
# Carteras
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CarteraResumen,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una cartera",
)
def crear(bd: BD, usuario: Actual, limites: MisLimites, cuerpo: CarteraNueva) -> CarteraResumen:
    # La puerta de plan, por la unica dependencia que existe (FASE 12).
    cuantas = bd.scalar(
        select(func.count()).select_from(Portfolio).where(Portfolio.user_id == usuario.id)
    )
    comprobar_cupo(int(cuantas or 0), limites.carteras, "carteras", "cartera")

    cartera = Portfolio(
        user_id=usuario.id,
        name=cuerpo.nombre,
        description=cuerpo.descripcion,
        base_currency=cuerpo.divisa_base.upper(),
    )
    bd.add(cartera)
    try:
        bd.commit()
    except IntegrityError as exc:
        bd.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ya tienes una cartera con ese nombre",
        ) from exc
    bd.refresh(cartera)
    return CarteraResumen(
        id=cartera.id,
        nombre=cartera.name,
        descripcion=cartera.description,
        divisa_base=cartera.base_currency,
        transacciones=0,
    )


@router.get("", response_model=list[CarteraResumen], summary="Mis carteras")
def listar(bd: BD, usuario: Actual) -> list[CarteraResumen]:
    cuentas = dict(
        bd.execute(
            select(Transaction.portfolio_id, func.count())
            .join(Portfolio, Portfolio.id == Transaction.portfolio_id)
            .where(Portfolio.user_id == usuario.id)
            .group_by(Transaction.portfolio_id)
        ).all()
    )
    carteras = bd.scalars(
        select(Portfolio).where(Portfolio.user_id == usuario.id).order_by(Portfolio.id)
    ).all()
    return [
        CarteraResumen(
            id=c.id,
            nombre=c.name,
            descripcion=c.description,
            divisa_base=c.base_currency,
            transacciones=int(cuentas.get(c.id, 0)),
        )
        for c in carteras
    ]


@router.patch("/{cartera_id}", response_model=CarteraResumen, summary="Renombrar una cartera")
def modificar(
    bd: BD, usuario: Actual, cartera_id: Annotated[int, Path()], cuerpo: CarteraCambio
) -> CarteraResumen:
    cartera = _mia(bd, usuario, cartera_id)
    if cuerpo.nombre is not None:
        cartera.name = cuerpo.nombre
    if cuerpo.descripcion is not None:
        cartera.description = cuerpo.descripcion
    bd.commit()
    bd.refresh(cartera)
    return CarteraResumen(
        id=cartera.id,
        nombre=cartera.name,
        descripcion=cartera.description,
        divisa_base=cartera.base_currency,
        transacciones=int(
            bd.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.portfolio_id == cartera.id)
            )
            or 0
        ),
    )


@router.delete(
    "/{cartera_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Borrar una cartera"
)
def borrar(bd: BD, usuario: Actual, cartera_id: Annotated[int, Path()]) -> None:
    cartera = _mia(bd, usuario, cartera_id)
    bd.delete(cartera)
    bd.commit()


# ---------------------------------------------------------------------------
# Transacciones: lo unico que se escribe
# ---------------------------------------------------------------------------


@router.post(
    "/{cartera_id}/transactions",
    response_model=TransaccionFila,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una transaccion",
)
def anadir(
    bd: BD, usuario: Actual, cartera_id: Annotated[int, Path()], cuerpo: TransaccionNueva
) -> TransaccionFila:
    cartera = _mia(bd, usuario, cartera_id)
    valor, divisa, fx = _resolver(bd, cartera, cuerpo)

    fila = Transaction(
        portfolio_id=cartera.id,
        security_id=valor.id,
        transaction_type=cuerpo.tipo.value,
        quantity=cuerpo.cantidad,
        price=cuerpo.precio,
        fees=cuerpo.comisiones,
        taxes=cuerpo.impuestos,
        currency_code=divisa,
        fx_rate_to_base=fx,
        executed_on=cuerpo.fecha,
        note=cuerpo.nota,
    )
    bd.add(fila)
    bd.commit()
    bd.refresh(fila)
    return _fila(fila, valor.ticker)


@router.get(
    "/{cartera_id}/transactions",
    response_model=list[TransaccionFila],
    summary="Las transacciones de una cartera",
)
def transacciones(
    bd: BD, usuario: Actual, cartera_id: Annotated[int, Path()]
) -> list[TransaccionFila]:
    cartera = _mia(bd, usuario, cartera_id)
    filas = bd.execute(
        select(Transaction, Security.ticker)
        .join(Security, Security.id == Transaction.security_id)
        .where(Transaction.portfolio_id == cartera.id)
        .order_by(Transaction.executed_on, Transaction.id)
    ).all()
    return [_fila(t, ticker) for t, ticker in filas]


@router.put(
    "/{cartera_id}/transactions/{transaccion_id}",
    response_model=TransaccionFila,
    summary="Corregir una transaccion",
)
def corregir(
    bd: BD,
    usuario: Actual,
    cartera_id: Annotated[int, Path()],
    transaccion_id: Annotated[int, Path()],
    cuerpo: TransaccionNueva,
) -> TransaccionFila:
    """Corrige una transaccion, por antigua que sea.

    No hay nada que recalcular despues: la cartera se deriva entera en cada
    consulta, asi que corregir la compra de marzo corrige el coste medio, el P&L
    realizado de todas las ventas posteriores y los pesos de hoy, de una vez.
    """
    cartera = _mia(bd, usuario, cartera_id)
    fila = bd.scalars(
        select(Transaction).where(
            Transaction.id == transaccion_id, Transaction.portfolio_id == cartera.id
        )
    ).first()
    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="transacción no encontrada"
        )

    valor, divisa, fx = _resolver(bd, cartera, cuerpo)
    fila.security_id = valor.id
    fila.transaction_type = cuerpo.tipo.value
    fila.quantity = cuerpo.cantidad
    fila.price = cuerpo.precio
    fila.fees = cuerpo.comisiones
    fila.taxes = cuerpo.impuestos
    fila.currency_code = divisa
    fila.fx_rate_to_base = fx
    fila.executed_on = cuerpo.fecha
    fila.note = cuerpo.nota
    bd.commit()
    bd.refresh(fila)
    return _fila(fila, valor.ticker)


@router.delete(
    "/{cartera_id}/transactions/{transaccion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar una transaccion",
)
def borrar_transaccion(
    bd: BD,
    usuario: Actual,
    cartera_id: Annotated[int, Path()],
    transaccion_id: Annotated[int, Path()],
) -> None:
    cartera = _mia(bd, usuario, cartera_id)
    fila = bd.scalars(
        select(Transaction).where(
            Transaction.id == transaccion_id, Transaction.portfolio_id == cartera.id
        )
    ).first()
    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="transacción no encontrada"
        )
    bd.delete(fila)
    bd.commit()


# ---------------------------------------------------------------------------
# Asignacion objetivo: lo unico que se guarda ademas de las transacciones
# ---------------------------------------------------------------------------


@router.put("/{cartera_id}/objetivo", response_model=Objetivo, summary="Asignacion objetivo")
def fijar_objetivo(
    bd: BD, usuario: Actual, cartera_id: Annotated[int, Path()], cuerpo: Objetivo
) -> Objetivo:
    """Fija el peso objetivo de cada valor.

    Se guarda porque es una DECISION, no una consecuencia: nadie puede derivar de
    las transacciones cuanto querias tener en tecnologia. Es lo unico de
    `portfolio_position` que esta API toca.
    """
    cartera = _mia(bd, usuario, cartera_id)
    suma = sum(cuerpo.pesos.values())
    if cuerpo.pesos and not (0.99 <= suma <= 1.01):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"los pesos objetivo suman {suma:.4f} y tienen que sumar 1",
        )

    bd.execute(
        PortfolioPosition.__table__.delete().where(PortfolioPosition.portfolio_id == cartera.id)
    )
    for ticker, peso in cuerpo.pesos.items():
        if not 0 <= peso <= 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"el peso objetivo de {ticker} está fuera de [0, 1]",
            )
        valor = _valor_por_ticker(bd, ticker)
        bd.add(
            PortfolioPosition(
                portfolio_id=cartera.id,
                security_id=valor.id,
                # `quantity` es NOT NULL y es justo la denormalizacion que esta
                # fase prohibe. Se deja en cero y NO se lee en ningun sitio: la
                # cantidad de verdad sale siempre de las transacciones.
                quantity=Decimal("0"),
                target_weight=Decimal(str(peso)),
            )
        )
    bd.commit()
    return cuerpo


# ---------------------------------------------------------------------------
# La valoracion, que es toda derivada
# ---------------------------------------------------------------------------


@router.get("/{cartera_id}", response_model=Valoracion, summary="Valor, P&L y exposicion")
def valorar(
    bd: BD,
    usuario: Actual,
    cartera_id: Annotated[int, Path()],
    fecha: Annotated[dt.date | None, Query(description="Corte temporal")] = None,
    modelo: Annotated[str, Query(description="Perfil de pesos de §18")] = MODELO_POR_DEFECTO,
) -> Valoracion:
    cartera = _mia(bd, usuario, cartera_id)
    corte = fecha or dt.date.today()

    # El corte manda tambien sobre las transacciones: una cartera a fecha de
    # marzo no incluye la compra de abril, por mas que ya este registrada.
    filas = bd.execute(
        select(Transaction, Security)
        .join(Security, Security.id == Transaction.security_id)
        .where(Transaction.portfolio_id == cartera.id, Transaction.executed_on <= corte)
        .order_by(Transaction.executed_on, Transaction.id)
    ).all()

    valores: dict[str, Security] = {v.ticker: v for _, v in filas}
    ids = sorted({v.id for v in valores.values()})

    precios_bd = _ultimos_precios(bd, ids, corte)
    scores, fecha_scores = _ultimos_scores(bd, ids, corte, modelo)

    precios: dict[str, Decimal] = {}
    fechas_precio: dict[str, dt.date] = {}
    fx_actual: dict[str, Decimal] = {}
    for ticker, v in valores.items():
        par = precios_bd.get(v.id)
        if par is None:
            continue
        cambio = _fx_del_dia(bd, v.currency_code, cartera.base_currency, corte)
        if cambio is None:
            # Sin cambio de hoy no se valora: valorar al cambio de la compra
            # inventaria una ganancia por divisa que no ha ocurrido.
            continue
        precios[ticker], fechas_precio[ticker] = par
        fx_actual[ticker] = cambio

    derivada = derivar(
        [_a_transaccion(t, v.ticker) for t, v in filas],
        precios=precios,
        fx_actual=fx_actual,
    )

    objetivos = dict(
        bd.execute(
            select(Security.ticker, PortfolioPosition.target_weight)
            .join(Security, Security.id == PortfolioPosition.security_id)
            .where(
                PortfolioPosition.portfolio_id == cartera.id,
                PortfolioPosition.target_weight.is_not(None),
            )
        ).all()
    )
    paises = dict(bd.execute(select(Market.id, Market.country_code)).all())
    pesos = derivada.pesos()

    posiciones: list[PosicionFila] = []
    for pos in sorted(derivada.abiertas, key=lambda p: -(p.valor or CERO)):
        v = valores[pos.ticker]
        peso = pesos.get(pos.ticker)
        objetivo = objetivos.get(pos.ticker)
        posiciones.append(
            PosicionFila(
                ticker=pos.ticker,
                nombre=v.name,
                sector=v.sector,
                pais=paises.get(v.market_id),
                cantidad=pos.cantidad,
                coste=pos.coste,
                coste_medio=pos.coste_medio,
                precio=pos.precio_actual,
                fecha_precio=fechas_precio.get(pos.ticker),
                valor=pos.valor,
                no_realizado=pos.no_realizado,
                realizado=pos.realizado,
                dividendos=pos.dividendos,
                peso=None if peso is None else float(peso),
                objetivo=None if objetivo is None else float(objetivo),
                desviacion=(
                    None if objetivo is None or peso is None else float(peso) - float(objetivo)
                ),
                score=scores.get(v.id),
            )
        )

    dim_sector = {t: v.sector for t, v in valores.items()}
    dim_pais = {t: paises.get(v.market_id) for t, v in valores.items()}

    lista_pesos = [float(p) for p in pesos.values()]
    hhi = sum(p * p for p in lista_pesos) if lista_pesos else None

    # Score medio PONDERADO POR PESO, no la media aritmetica: una posicion del
    # 1 % no puede pesar lo mismo que una del 40 % en el score de la cartera.
    # Los que no tienen score se quedan fuera y se declara cuanto pesan.
    con_score = [(float(pesos[t]), scores[valores[t].id]) for t in pesos if valores[t].id in scores]
    cobertura = sum(p for p, _ in con_score)
    medio = (sum(p * s for p, s in con_score) / cobertura) if cobertura > 0 else None

    return Valoracion(
        id=cartera.id,
        nombre=cartera.name,
        divisa_base=cartera.base_currency,
        fecha=corte,
        posiciones=posiciones,
        totales=Totales(
            valor=derivada.valor,
            coste=derivada.coste,
            no_realizado=derivada.no_realizado,
            realizado=derivada.realizado,
            dividendos=derivada.dividendos,
            gastos=derivada.gastos,
            total=derivada.total,
        ),
        exposicion_sector={k: float(v) for k, v in exposicion(derivada, dim_sector).items()},
        exposicion_pais={k: float(v) for k, v in exposicion(derivada, dim_pais).items()},
        diversificacion=Diversificacion(
            posiciones=len(derivada.abiertas),
            hhi=None if hhi in (None, 0) else round(hhi, 6),
            posiciones_efectivas=None if not hhi else round(1.0 / hhi, 2),
            mayor_peso=max(lista_pesos) if lista_pesos else None,
        ),
        score_medio=ScoreMedio(
            valor=None if medio is None else round(medio, 2),
            cobertura=round(cobertura, 4),
            fecha_datos=fecha_scores,
        ),
        sin_valorar=sorted(derivada.sin_valorar),
    )
