"""Etapa de scoring: de los datos a `score`, con su version de modelo.

Idempotente como el resto del pipeline: recalcular sobre la misma instantanea
da exactamente los mismos numeros, porque el percentil de una cohorte es una
funcion determinista de sus datos y de nada mas.

Los cinco perfiles de §18 se recalculan todos en la misma pasada. Comparten los
factores en bruto —que es el trabajo caro— y solo difieren en los pesos, asi que
producir los cinco cuesta practicamente lo mismo que producir uno.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

import pandas as pd
import yaml
from estrategia import grupos, scoring
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.db.models import ModelVersion, Score, Security
from backend.db.models.enums import AssetType, ModelKind

log = logging.getLogger("pipeline.scores")

#: Del nombre interno del sub-score a la columna de `score`.
COLUMNAS_SUBSCORE = {
    "crecimiento": "growth",
    "rentabilidad": "profitability",
    "salud_financiera": "financial_health",
    "calidad": "quality",
    "valoracion": "valuation",
    "momentum": "momentum",
    "tendencia": "trend",
    "volatilidad": "volatility",
    "volumen": "volume",
}
#: Del vocabulario de cohortes del motor al del esquema.
COHORTES = {
    "mercado": "market_sector",
    "bloque": "block",
    "insuficiente": "insufficient",
}

COLUMNAS_PILAR = {
    "fundamental": "fundamental",
    "tecnico": "technical",
    "sentimiento": "sentiment",
    "riesgo": "risk",
}


def cargar_modelos(sesion: Session, ruta) -> dict[str, ModelVersion]:
    """Da de alta los perfiles de `modelos.yaml` en `model_version`.

    Un score no se puede guardar sin version de modelo: la clave ajena es NOT
    NULL a proposito. Asi que los perfiles tienen que existir en la tabla antes
    de puntuar, y se cargan desde la configuracion en lugar de escribirse a mano.
    """
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))["modelos"]
    salida: dict[str, ModelVersion] = {}
    for clave, cfg in datos.items():
        sentencia = insert(ModelVersion).values(
            name=clave,
            version=cfg["version"],
            kind=ModelKind.RULES.value,
            description=cfg.get("descripcion"),
            parameters={"pilares": cfg["pilares"], "grupos": cfg["grupos"]},
            is_active=True,
        )
        sesion.execute(
            sentencia.on_conflict_do_update(
                index_elements=["name", "version"],
                set_={
                    "description": sentencia.excluded.description,
                    "parameters": sentencia.excluded.parameters,
                    "is_active": sentencia.excluded.is_active,
                },
            )
        )
    sesion.flush()
    for clave, cfg in datos.items():
        salida[clave] = sesion.scalars(
            select(ModelVersion).where(
                ModelVersion.name == clave, ModelVersion.version == cfg["version"]
            )
        ).one()
    return salida


def _fundamentales(sesion: Session, ids: list[int]) -> dict[int, pd.DataFrame]:
    filas = (
        sesion.execute(
            text(
                "SELECT security_id, period_end, period, revenue, ebit, ebitda, "
                "       net_income, gross_profit, equity, total_assets, total_debt, "
                "       free_cash_flow, eps, shares_outstanding, current_assets, "
                "       current_liabilities, "
                "       interest_expense, operating_margin "
                "FROM fundamental_snapshot WHERE security_id = ANY(:ids) "
                "ORDER BY security_id, period_end"
            ),
            {"ids": ids},
        )
        .mappings()
        .all()
    )
    if not filas:
        return {}
    marco = pd.DataFrame(filas).rename(
        columns={
            "period_end": "fin_periodo",
            "period": "periodo",
            "revenue": "ventas",
            "net_income": "beneficio_neto",
            "gross_profit": "beneficio_bruto",
            "equity": "patrimonio_neto",
            "total_assets": "activos_totales",
            "total_debt": "deuda_total",
            "free_cash_flow": "flujo_caja_libre",
            "eps": "bpa",
            "shares_outstanding": "acciones_en_circulacion",
            "current_assets": "activo_corriente",
            "current_liabilities": "pasivo_corriente",
            "interest_expense": "gastos_financieros",
            "operating_margin": "margen_operativo",
        }
    )
    marco["periodo"] = marco["periodo"].replace({"annual": "anual"})
    return {int(i): g for i, g in marco.groupby("security_id")}


def _indicadores(sesion: Session, ids: list[int], fecha: dt.date) -> dict[int, dict]:
    """La ultima lectura de indicadores en o antes de la fecha.

    En o antes, no exacta: un valor puede no haber cotizado ese dia. Buscar la
    fecha exacta lo dejaria fuera del ranking por un festivo.
    """
    filas = (
        sesion.execute(
            text(
                "SELECT DISTINCT ON (security_id) * FROM technical_indicator "
                "WHERE security_id = ANY(:ids) AND date <= :fecha "
                "ORDER BY security_id, date DESC"
            ),
            {"ids": ids, "fecha": fecha},
        )
        .mappings()
        .all()
    )
    salida = {}
    for f in filas:
        d = dict(f)
        extra = d.pop("extra", None) or {}
        salida[int(d["security_id"])] = {**d, **extra}
    return salida


def _precios(sesion: Session, ids: list[int], fecha: dt.date) -> dict[int, dict]:
    filas = (
        sesion.execute(
            text(
                "SELECT DISTINCT ON (security_id) security_id, date, close, close_raw, volume "
                "FROM price WHERE security_id = ANY(:ids) AND date <= :fecha "
                "ORDER BY security_id, date DESC"
            ),
            {"ids": ids, "fecha": fecha},
        )
        .mappings()
        .all()
    )
    return {int(f["security_id"]): dict(f) for f in filas}


def _decimal(valor) -> Decimal | None:
    return None if valor is None or pd.isna(valor) else Decimal(f"{float(valor):.2f}")


def ejecutar(
    sesion: Session,
    cfg,
    fecha: dt.date | None = None,
    mercados: list[str] | None = None,
) -> dict[str, int]:
    """Calcula y persiste los scores de todos los modelos."""
    fecha = fecha or dt.date.today()
    modelos = cargar_modelos(sesion, cfg.dir_config / "modelos.yaml")
    definiciones = yaml.safe_load((cfg.dir_config / "modelos.yaml").read_text(encoding="utf-8"))[
        "modelos"
    ]

    consulta = select(Security).where(
        Security.active.is_(True), Security.asset_type != AssetType.INDEX.value
    )
    if mercados:
        consulta = consulta.where(Security.market_id.in_(mercados))
    valores = sesion.scalars(consulta).all()
    if not valores:
        return {}

    ids = [v.id for v in valores]
    por_id = {v.id: v for v in valores}
    fund = _fundamentales(sesion, ids)
    ind = _indicadores(sesion, ids, fecha)
    pre = _precios(sesion, ids, fecha)

    # La cohorte es mercado x sector. Un ROE del 18 % no significa lo mismo en
    # la banca que en el software, y §14 prohibe expresamente compararlos.
    cohortes = {v.ticker: f"{v.market_id}|{v.sector or 'desconocido'}" for v in valores}

    magnitudes: dict[str, dict] = {}
    factores: dict[str, dict] = {}
    for vid, valor in por_id.items():
        precio = pre.get(vid)
        cierre = float(precio["close"]) if precio and precio["close"] else None
        historico = fund.get(vid)

        capitalizacion = ev = None
        if historico is not None and not historico.empty and cierre:
            ultimo = historico.iloc[-1]
            acciones = ultimo.get("acciones_en_circulacion")
            if acciones is None:
                acciones = None
            if acciones and not pd.isna(acciones):
                capitalizacion = float(acciones) * cierre
                deuda = ultimo.get("deuda_total")
                if deuda is not None and not pd.isna(deuda):
                    ev = capitalizacion + float(deuda)

        magnitudes[valor.ticker] = (
            grupos.magnitudes_de(historico, capitalizacion, ev)
            if historico is not None and not historico.empty
            else dict.fromkeys(grupos.DIRECCION)
        )

        lectura = ind.get(vid, {})
        tec = scoring.factores_tecnicos(lectura, cierre)
        # La liquidez se mide en divisa local con precio y volumen brutos: el
        # volumen no se ajusta por dividendos, y mezclarlo con el precio
        # ajustado subestima la liquidez historica.
        bruto = float(precio["close_raw"]) if precio and precio.get("close_raw") else cierre
        volumen = float(precio["volume"]) if precio and precio.get("volume") else None
        tec["liquidez"] = bruto * volumen if bruto and volumen else None
        # Dos factores de riesgo salen de los fundamentales, no del precio.
        tec["deuda_patrimonio"] = magnitudes[valor.ticker].get("deuda_patrimonio")
        tec["variacion_beneficios"] = magnitudes[valor.ticker].get("variacion_beneficios")
        tec["drawdown_maximo_1a"] = lectura.get("max_drawdown_1y")
        tec["beta_252"] = lectura.get("beta")
        tec["volatilidad_60"] = lectura.get("volatility_annualized")
        factores[valor.ticker] = tec

    escritos: dict[str, int] = {}
    id_por_ticker = {v.ticker: v.id for v in valores}

    for clave, modelo in modelos.items():
        pesos_grupo = definiciones[clave]["grupos"]
        pesos_pilar = definiciones[clave]["pilares"]
        notas_fund = grupos.puntuar(
            magnitudes,
            cohortes,
            min_cohorte=cfg.reglas.fundamental.min_empresas_percentil,
            pesos=pesos_grupo,
        )
        puntuaciones = scoring.puntuar(
            factores,
            cohortes,
            notas_fund,
            pesos_pilar,
            min_cohorte=cfg.reglas.fundamental.min_empresas_percentil,
        )

        filas = []
        for ticker, p in puntuaciones.items():
            if p.overall is None:
                continue
            fila = {
                "security_id": id_por_ticker[ticker],
                "date": fecha,
                "model_version_id": modelo.id,
                "overall": _decimal(p.overall),
                # El motor nombra las cohortes en espanol y el esquema en
                # ingles; la traduccion vive en el adaptador, no aqui suelta.
                "cohort_used": COHORTES[p.cohorte_usada.value],
                "n_cohort": p.n_cohorte,
                "available_pillars": p.pilares_disponibles,
            }
            for interno, columna in COLUMNAS_PILAR.items():
                fila[columna] = _decimal(p.pilares.get(interno))
            for interno, columna in COLUMNAS_SUBSCORE.items():
                fila[columna] = _decimal(p.subscores.get(interno))
            filas.append(fila)

        if filas:
            sentencia = insert(Score).values(filas)
            actualizables = {
                c: sentencia.excluded[c]
                for c in filas[0]
                if c not in ("security_id", "date", "model_version_id")
            }
            sesion.execute(
                sentencia.on_conflict_do_update(
                    index_elements=["security_id", "date", "model_version_id"],
                    set_=actualizables,
                )
            )
        escritos[clave] = len(filas)
        sesion.commit()

    return escritos
