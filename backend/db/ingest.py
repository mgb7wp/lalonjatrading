"""Escritura masiva e idempotente de series en Postgres.

Dos propiedades, y ninguna es opcional.

**Idempotencia.** Todo entra por `INSERT ... ON CONFLICT DO UPDATE` sobre la
clave natural de cada tabla. Reejecutar el pipeline de un dia no duplica nada ni
cambia nada (decision D-9). El criterio de aceptacion de la FASE 3 —"ejecutarlo
dos veces no cambia una sola fila"— se comprueba con `huella()`, que resume el
contenido de una tabla: si la huella es la misma antes y despues, no cambio
nada, y eso es una afirmacion verificable en lugar de una promesa.

**Velocidad.** Las filas entran por `COPY` a una tabla temporal y de ahi a la
definitiva de una sola sentencia. Insertar fila a fila con el ORM decenas de
millones de precios no es lento: es inviable. El ORM se queda para las entidades,
que son pocas y se manipulan de una en una.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..adapters.nucleo import (
    COLUMNAS_FUNDAMENTAL,
    COLUMNAS_FX,
    COLUMNAS_INDICADOR,
    COLUMNAS_PRECIO,
)
from .models import Security


@dataclass
class Escritura:
    """Que se escribio. `filas` son las enviadas, no las que cambiaron."""

    tabla: str
    filas: int = 0
    descartadas: int = 0

    def __str__(self) -> str:
        cola = f" ({self.descartadas} descartadas)" if self.descartadas else ""
        return f"{self.tabla}: {self.filas} filas{cola}"


def id_por_ticker(sesion: Session, mercado_id: str | None = None) -> dict[str, int]:
    """Mapa ticker -> id de valor, que es lo que traduce el motor al esquema."""
    consulta = select(Security.ticker, Security.id)
    if mercado_id:
        consulta = consulta.where(Security.market_id == mercado_id)
    return dict(sesion.execute(consulta).all())


def _copiar_y_fusionar(
    sesion: Session,
    tabla: str,
    columnas: list[str],
    filas: list[tuple],
    clave: list[str],
) -> int:
    """COPY a una temporal y UPSERT de ahi a la definitiva.

    La temporal se crea con `CREATE TABLE AS ... WITH NO DATA` sobre la lista de
    columnas que se van a copiar. Se probo antes con `LIKE ... EXCLUDING ALL` y
    no vale: `LIKE` copia SIEMPRE el `NOT NULL` de cada columna pero
    `EXCLUDING ALL` descarta su valor por defecto, asi que la temporal de una
    tabla con `id BIGSERIAL` exige un `id` que el COPY no envia y la carga muere.
    `price` no lo sufria —su clave es compuesta y no tiene `id`— y por eso el
    fallo solo aparecio en fundamentales, que es como aparecen estas cosas.

    `CREATE TABLE AS` sobre columnas concretas trae los tipos y nada mas: ni
    NOT NULL, ni defaults, ni CHECK. Que la fila se valide en la tabla
    definitiva y no en la temporal es justo lo que se quiere: el contrato decide
    en el UPSERT, no en una copia intermedia.

    El `DISTINCT ON` no es cosmetico: si un lote trae la misma clave dos veces
    —un proveedor que repite una fecha, dos tickers que resuelven al mismo
    valor—, Postgres rechaza el UPSERT entero con "ON CONFLICT DO UPDATE command
    cannot affect row a second time". Quedandose con la ultima aparicion, un lote
    sucio entra en lugar de tumbar la carga del mercado.
    """
    if not filas:
        return 0

    temporal = f"tmp_{tabla}"
    lista = ", ".join(columnas)
    sesion.execute(
        text(
            f"CREATE TEMP TABLE {temporal} ON COMMIT DROP AS "
            f"SELECT {lista} FROM {tabla} WITH NO DATA"
        )
    )

    crudo = sesion.connection().connection
    with crudo.cursor() as cur:
        with cur.copy(f"COPY {temporal} ({lista}) FROM STDIN") as copia:
            for fila in filas:
                copia.write_row(fila)

    actualizables = [c for c in columnas if c not in clave]
    asignaciones = ", ".join(f"{c} = EXCLUDED.{c}" for c in actualizables)
    orden_clave = ", ".join(clave)

    sesion.execute(
        text(
            f"INSERT INTO {tabla} ({lista}) "
            f"SELECT DISTINCT ON ({orden_clave}) {lista} FROM {temporal} "
            f"ORDER BY {orden_clave}, ctid DESC "
            f"ON CONFLICT ({orden_clave}) DO UPDATE SET {asignaciones}"
        )
    )
    # Se libera ya y no al final de la transaccion: el pipeline carga varios
    # mercados en la misma, y la segunda vuelta chocaria con la temporal anterior.
    sesion.execute(text(f"DROP TABLE {temporal}"))
    return len(filas)


def escribir_precios(sesion: Session, filas: list[tuple]) -> Escritura:
    n = _copiar_y_fusionar(sesion, "price", COLUMNAS_PRECIO, filas, ["security_id", "date"])
    return Escritura("price", n)


def escribir_fundamentales(sesion: Session, filas: list[tuple]) -> Escritura:
    n = _copiar_y_fusionar(
        sesion,
        "fundamental_snapshot",
        COLUMNAS_FUNDAMENTAL,
        filas,
        ["security_id", "period_end", "period"],
    )
    return Escritura("fundamental_snapshot", n)


def escribir_fx(sesion: Session, filas: list[tuple]) -> Escritura:
    n = _copiar_y_fusionar(
        sesion,
        "fx_rate",
        COLUMNAS_FX,
        filas,
        ["base_currency", "quote_currency", "date"],
    )
    return Escritura("fx_rate", n)


#: Columnas que registran CUANDO se hizo algo, no QUE se guardo. Se dejan fuera
#: de la huella por defecto: `computed_at` lleva microsegundos, asi que incluirla
#: haria que dos ejecuciones con datos identicos parecieran distintas y la
#: comprobacion de idempotencia no podria distinguir "los numeros han cambiado"
#: de "el reloj ha avanzado", que es lo unico que se quiere saber.
COLUMNAS_DE_AUDITORIA = ("computed_at", "created_at", "updated_at")


def columnas_de(sesion: Session, tabla: str) -> list[str]:
    return list(
        sesion.scalars(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :tabla "
                "ORDER BY ordinal_position"
            ),
            {"tabla": tabla},
        )
    )


def huella(sesion: Session, tabla: str, excluir: tuple[str, ...] | None = None) -> str:
    """Resumen del contenido de una tabla, para comprobar que no cambio nada.

    Es lo que convierte "el pipeline es idempotente" en algo que se comprueba en
    lugar de en algo que se promete. Se ordena por la fila entera en texto
    porque no todas las tablas tienen un orden natural util, y lo que interesa
    es el conjunto, no la secuencia.

    `downloaded_at` NO esta entre las excluidas por defecto, y es deliberado: no
    es auditoria, es la instantanea de la que salio el dato. Yahoo revisa el
    pasado hacia atras, asi que dos descargas distintas del mismo dia bursatil
    pueden traer numeros distintos, y eso SI tiene que salir en la huella.
    """
    excluidas = set(COLUMNAS_DE_AUDITORIA if excluir is None else excluir)
    columnas = [c for c in columnas_de(sesion, tabla) if c not in excluidas]
    if not columnas:
        raise ValueError(f"no quedan columnas que resumir en {tabla}")
    lista = ", ".join(f'"{c}"' for c in columnas)
    consulta = text(
        f"SELECT md5(string_agg(fila, '|' ORDER BY fila)) "  # noqa: S608 - tabla interna
        f"FROM (SELECT ROW({lista})::text AS fila FROM {tabla}) s"
    )
    return sesion.execute(consulta).scalar() or ""


def escribir_indicadores(sesion: Session, filas: list[tuple]) -> Escritura:
    n = _copiar_y_fusionar(
        sesion, "technical_indicator", COLUMNAS_INDICADOR, filas, ["security_id", "date"]
    )
    return Escritura("technical_indicator", n)
