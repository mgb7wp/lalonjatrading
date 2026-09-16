"""Fuente CVM: fundamentales de Brasil con fecha de presentacion real.

La segunda fuente gratuita, oficial y point-in-time del proyecto, despues de la
SEC. Con ella Brasil pasa de cuatro ejercicios reexpresados a **dieciseis con
las cifras de su momento**.

## Como se consigue el point-in-time

La CVM publica un fichero por ano con las cuentas anuales (DFP) de todas las
sociedades cotizadas. Dentro, cada empresa declara dos columnas: `ULTIMO`, el
ejercicio que cierra, y `PENULTIMO`, el anterior repetido como comparativo.

Quedarse **solo con `ULTIMO`** es lo que da la cifra tal y como se publico
entonces: el comparativo del ano siguiente puede venir reexpresado, igual que
pasa en EE. UU. Es el mismo mecanismo que en la SEC, con otra forma.

La fecha viene del indice del propio fichero: `DT_RECEB`, el dia en que la CVM
recibio el documento. Es una fecha real, no una estimacion por retraso fijo.

## Lo que no tiene codigo fijo

El plan de cuentas de la CVM esta normalizado —`3.01` son ingresos en todas las
empresas— y eso cubre casi todo. Dos magnitudes se escapan:

- **Amortizaciones**, que hacen falta para el EBITDA.
- **Capex**, que hace falta para el flujo de caja libre.

Las dos aparecen como lineas de detalle con descripcion libre. Se localizan por
texto, y el patron esta afinado sobre los datos reales: buscar `amortiza` sin
mas captura «Amortizacao de custos de emprestimos», que es un gasto financiero y
**inflaria el EBITDA**. Exigir `deprecia` deja fuera esa familia entera y cubre
el 94 % de las empresas; el capex, filtrando ventas de inmovilizado, el 93 %.

En el 6 % restante el EBITDA y el flujo libre salen a nulo. Es lo correcto: el
contrato admite huecos sueltos, y una empresa sin EBITDA calculable se queda
fuera del filtro en lugar de entrar con un numero inventado.

## Enlace con los tickers

La CVM no publica el ticker. El mapeo vive en `config/cvm_empresas.yaml`,
escrito a mano porque emparejar por nombre se equivoca con aplomo, y lo
comprueba `scripts/verify_sources.py` contra los ingresos de yfinance.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml

from ..config import RAIZ, Config
from ..errores import ErrorDatos
from .proveedor import Capacidades, ProveedorFundamentales

BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS"

#: Primer ano publicado por la CVM en este formato.
PRIMER_ANO = 2010

#: Codigos del plan de cuentas normalizado. Iguales para todas las empresas: esa
#: es la ventaja de la CVM sobre el XBRL estadounidense, donde cada empresa
#: elige su etiqueta y hay que coser series.
CUENTAS_DRE = {
    "ventas": "3.01",
    "beneficio_bruto": "3.03",
    # 3.05 es el resultado antes del financiero y de impuestos: eso es el EBIT.
    "ebit": "3.05",
    "gastos_financieros": "3.06.02",
    "beneficio_neto": "3.11",
}
#: Si la empresa no consolida, el resultado del periodo va en 3.09.
CUENTA_BENEFICIO_ALTERNATIVA = "3.09"

CUENTAS_BPA = {
    "activos_totales": "1",
    "activo_corriente": "1.01",
    "efectivo": "1.01.01",
}
CUENTAS_BPP = {
    "pasivo_corriente": "2.01",
    "patrimonio_neto": "2.03",
    "deuda_corto": "2.01.04",
    "deuda_largo": "2.02.01",
}
CUENTA_FLUJO_OPERATIVO = "6.01"

#: Beneficio por accion, accion ordinaria. La CVM lo desglosa por clase y los
#: agregados (`3.99`, `3.99.02`) vienen a cero, asi que hay que ir a la hoja.
CUENTAS_BPA_ACCION = ("3.99.02.01", "3.99.01.01")

#: `deprecia` y no `amortiza`: ver el docstring del modulo. La diferencia entre
#: un EBITDA correcto y uno inflado con costes financieros.
PATRON_AMORTIZACION = re.compile(r"deprecia", re.I)
PATRON_CAPEX = re.compile(r"imobilizado|intang", re.I)
PATRON_NO_CAPEX = re.compile(r"venda|aliena|baixa|recebiment", re.I)

#: La CVM declara la escala de cada bloque de cuentas.
ESCALAS = {"UNIDADE": 1.0, "MIL": 1_000.0, "MILHAO": 1_000_000.0}

#: Cuentas que NO llevan escala: son reales por accion, no importes.
PREFIJO_POR_ACCION = "3.99"


def _texto(bruto: bytes) -> str:
    """Los CSV de la CVM van en latin-1, no en UTF-8."""
    return bruto.decode("latin-1")


def _numero(crudo: str | None) -> float | None:
    if crudo in (None, "", "nan"):
        return None
    try:
        return float(crudo)
    except ValueError:
        return None


def _fecha(crudo: str | None) -> date | None:
    if not crudo:
        return None
    try:
        return datetime.strptime(crudo[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _sin_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def parsear_indice(texto: str) -> dict[tuple[str, str, str], date]:
    """Del indice del fichero anual: cuando recibio la CVM cada documento.

    La clave incluye la version porque una empresa puede reenviar sus cuentas
    corregidas, y cada envio tiene su propia fecha de recepcion.
    """
    salida: dict[tuple[str, str, str], date] = {}
    for fila in csv.DictReader(io.StringIO(texto), delimiter=";"):
        recibido = _fecha(fila.get("DT_RECEB"))
        if recibido is None:
            continue
        salida[(fila["CNPJ_CIA"], fila["DT_REFER"], fila["VERSAO"])] = recibido
    return salida


def parsear_cuentas(texto: str) -> dict[tuple[str, str, str], dict[str, float]]:
    """Cuentas del ejercicio que cierra, por empresa, version y codigo.

    **Solo `ULTIMO`.** El `PENULTIMO` es el ejercicio anterior repetido como
    comparativo y puede venir reexpresado; usarlo destruiria la propiedad
    point-in-time que es la razon de ser de esta fuente.

    Las descripciones se guardan junto al valor porque amortizaciones y capex no
    tienen codigo fijo y hay que buscarlas por texto.
    """
    salida: dict[tuple[str, str, str], dict[str, float]] = {}
    for fila in csv.DictReader(io.StringIO(texto), delimiter=";"):
        if fila.get("ORDEM_EXERC") != "ÚLTIMO":
            continue
        valor = _numero(fila.get("VL_CONTA"))
        if valor is None:
            continue
        codigo_cuenta = fila["CD_CONTA"]
        # La escala declarada vale para los IMPORTES, no para las cifras por
        # accion. El grupo 3.99 es «Lucro por Acao - (Reais / Acao)»: ya viene en
        # reales por titulo. Aplicarle el MIL lo multiplica por mil, y como las
        # acciones en circulacion se derivan del BPA, el error se propaga al EV
        # y de ahi a toda la valoracion, sin que nada falle por el camino.
        escala = (
            1.0
            if codigo_cuenta.startswith(PREFIJO_POR_ACCION)
            else ESCALAS.get((fila.get("ESCALA_MOEDA") or "UNIDADE").upper(), 1.0)
        )
        clave = (fila["CNPJ_CIA"], fila["DT_REFER"], fila["VERSAO"])
        cuentas = salida.setdefault(clave, {})
        codigo = codigo_cuenta
        cuentas[codigo] = valor * escala
        cuentas[f"~{codigo}"] = fila.get("DS_CONTA", "")  # type: ignore[assignment]
    return salida


def _buscar_por_texto(
    cuentas: dict, prefijo: str, patron: re.Pattern, excluir: re.Pattern | None = None
) -> float | None:
    """Suma las cuentas bajo un prefijo cuya descripcion case con el patron."""
    total, encontrado = 0.0, False
    for clave, descripcion in cuentas.items():
        if not isinstance(clave, str) or not clave.startswith("~"):
            continue
        codigo = clave[1:]
        if not codigo.startswith(prefijo) or not isinstance(descripcion, str):
            continue
        limpia = _sin_acentos(descripcion)
        if not patron.search(limpia):
            continue
        if excluir is not None and excluir.search(limpia):
            continue
        valor = cuentas.get(codigo)
        if isinstance(valor, int | float):
            total += float(valor)
            encontrado = True
    return total if encontrado else None


def construir_fila(
    ticker: str,
    fin_periodo: date,
    publicacion: date,
    dre: dict,
    bpa: dict,
    bpp: dict,
    dfc: dict,
    descargado: date,
) -> dict:
    """Une los cuatro estados en una fila del esquema del proyecto."""

    def de(origen: dict, codigo: str) -> float | None:
        valor = origen.get(codigo)
        return float(valor) if isinstance(valor, int | float) else None

    ventas = de(dre, CUENTAS_DRE["ventas"])
    ebit = de(dre, CUENTAS_DRE["ebit"])
    beneficio = de(dre, CUENTAS_DRE["beneficio_neto"])
    if beneficio is None:
        beneficio = de(dre, CUENTA_BENEFICIO_ALTERNATIVA)

    patrimonio = de(bpp, CUENTAS_BPP["patrimonio_neto"])
    efectivo = de(bpa, CUENTAS_BPA["efectivo"])
    deuda_total = None
    corto, largo = de(bpp, CUENTAS_BPP["deuda_corto"]), de(bpp, CUENTAS_BPP["deuda_largo"])
    if corto is not None or largo is not None:
        deuda_total = (corto or 0.0) + (largo or 0.0)
    deuda_neta = None if deuda_total is None else deuda_total - (efectivo or 0.0)

    amortizacion = _buscar_por_texto(dfc, "6.01.", PATRON_AMORTIZACION)
    ebitda = None if ebit is None or amortizacion is None else ebit + abs(amortizacion)

    operativo = de(dfc, CUENTA_FLUJO_OPERATIVO)
    capex = _buscar_por_texto(dfc, "6.02.", PATRON_CAPEX, PATRON_NO_CAPEX)
    flujo_libre = None if operativo is None or capex is None else operativo - abs(capex)

    bpa_valor = next((de(dre, c) for c in CUENTAS_BPA_ACCION if de(dre, c)), None)
    gastos = de(dre, CUENTAS_DRE["gastos_financieros"])

    return {
        "ticker": ticker,
        "fin_periodo": fin_periodo,
        "periodo": "anual",
        "fecha_publicacion": publicacion,
        "origen_fecha_publicacion": "real_cvm",
        # Solo la columna `ULTIMO`: la cifra tal y como se publico entonces.
        "origen_pit": "capturado",
        "fecha_descarga": descargado,
        "roe": (beneficio / patrimonio if beneficio is not None and patrimonio else None),
        "margen_operativo": (ebit / ventas if ebit is not None and ventas else None),
        "ventas": ventas,
        "flujo_caja_libre": flujo_libre,
        "deuda_neta": deuda_neta,
        "ebitda": ebitda,
        "ebit": ebit,
        # La CVM publica cuentas, no cotizaciones: el motor calcula el EV en la
        # fecha de decision a partir de las acciones.
        "ev": None,
        "patrimonio_neto": patrimonio,
        # La CVM no publica el numero de acciones, asi que se deduce del
        # beneficio por accion. Son las acciones MEDIAS PONDERADAS del
        # ejercicio, que es sobre lo que se calcula el BPA, no las de cierre:
        # una ampliacion de capital a mitad de ano se refleja a medias. Es una
        # aproximacion buena para el EV y conviene saber que lo es.
        "acciones_en_circulacion": (
            abs(beneficio) / abs(bpa_valor)
            if beneficio not in (None, 0) and bpa_valor
            else None
        ),
        "divisa_reporte": "BRL",
        "divisa_cotizacion": "BRL",
        "beneficio_neto": beneficio,
        "beneficio_bruto": de(dre, CUENTAS_DRE["beneficio_bruto"]),
        "activos_totales": de(bpa, CUENTAS_BPA["activos_totales"]),
        "deuda_total": deuda_total,
        "efectivo": efectivo,
        "bpa": bpa_valor,
        "activo_corriente": de(bpa, CUENTAS_BPA["activo_corriente"]),
        "pasivo_corriente": de(bpp, CUENTAS_BPP["pasivo_corriente"]),
        # En positivo aunque en las cuentas reste: la cobertura de intereses es
        # EBIT partido por el gasto, y un signo negativo la volveria del reves.
        "gastos_financieros": None if gastos is None else abs(gastos),
    }


class ProveedorCVM(ProveedorFundamentales):
    """Fundamentales brasilenos desde los datos abiertos de la CVM."""

    nombre = "cvm"

    def __init__(self, cfg: Config, dir_cache: Path | None = None) -> None:
        self._cfg = cfg
        self._dir = dir_cache or (RAIZ / "datos" / "cache" / "cvm")
        self._empresas = self._cargar_mapeo()
        self._anos: dict[int, dict] = {}

    def _cargar_mapeo(self) -> dict[str, str]:
        ruta = self._cfg.dir_config / "cvm_empresas.yaml"
        if not ruta.is_file():
            raise ErrorDatos(f"falta el mapeo de empresas de la CVM: {ruta}")
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        return {t: v["cnpj"] for t, v in (datos.get("empresas") or {}).items()}

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("fundamentales",),
            anios_fundamentales=date.today().year - PRIMER_ANO,
            fechas_publicacion_reales=True,
            # Quedandose con la columna `ULTIMO`, las cifras son las de su
            # momento y no las reexpresadas despues.
            cifras_reexpresadas=False,
            incluye_deslistadas=False,
            mercados=("br",),
            necesita_clave=False,
            magnitudes=(
                "beneficio_neto",
                "beneficio_bruto",
                "activos_totales",
                "deuda_total",
                "efectivo",
                "bpa",
                "activo_corriente",
                "pasivo_corriente",
                "gastos_financieros",
            ),
            notas=(
                "Solo Brasil y solo ejercicios anuales (DFP).",
                "Emite origen_pit: capturado, como la SEC.",
                "EBITDA y flujo libre dependen de lineas con descripcion libre: "
                "cubren ~94 % de las empresas y el resto sale a nulo.",
                "No da EV: la CVM publica cuentas, no cotizaciones.",
            ),
        )

    def _descargar_ano(self, ano: int) -> dict[str, str]:
        """Ficheros del ano, descomprimidos en memoria y cacheados en disco.

        Se cachea el ZIP porque son 13 MB por ano y dieciseis anos son 200 MB de
        descarga que no cambia: los ejercicios cerrados no se reescriben.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        destino = self._dir / f"dfp_{ano}.zip"
        if not destino.is_file():
            url = f"{BASE}/dfp_cia_aberta_{ano}.zip"
            try:
                with urllib.request.urlopen(url, timeout=180) as respuesta:
                    destino.write_bytes(respuesta.read())
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise ErrorDatos(f"la CVM no publica el ano {ano}") from exc
                raise ErrorDatos(f"la CVM ha respondido {exc.code} para {ano}") from exc
            except urllib.error.URLError as exc:
                raise ErrorDatos(f"no se ha podido conectar con la CVM: {exc.reason}") from exc

        with zipfile.ZipFile(destino) as z:
            return {n: _texto(z.read(n)) for n in z.namelist() if n.endswith(".csv")}

    def _cargar_ano(self, ano: int) -> dict:
        if ano in self._anos:
            return self._anos[ano]
        ficheros = self._descargar_ano(ano)

        def leer(clave: str, sufijo: str) -> dict:
            nombre = f"dfp_cia_aberta_{clave}_{sufijo}_{ano}.csv"
            return parsear_cuentas(ficheros[nombre]) if nombre in ficheros else {}

        indice = parsear_indice(ficheros.get(f"dfp_cia_aberta_{ano}.csv", ""))
        # Se guardan las dos bases por separado —consolidada e individual— y la
        # eleccion se hace POR EMPRESA, no por fichero. Ver `_base_de`.
        #
        # El flujo de caja se publica por el metodo indirecto o el directo segun
        # la empresa; se fusionan porque el codigo 6.01 es el mismo en ambos.
        self._anos[ano] = {
            "indice": indice,
            "con": {
                "DRE": leer("DRE", "con"),
                "BPA": leer("BPA", "con"),
                "BPP": leer("BPP", "con"),
                "DFC": {**leer("DFC_MD", "con"), **leer("DFC_MI", "con")},
            },
            "ind": {
                "DRE": leer("DRE", "ind"),
                "BPA": leer("BPA", "ind"),
                "BPP": leer("BPP", "ind"),
                "DFC": {**leer("DFC_MD", "ind"), **leer("DFC_MI", "ind")},
            },
        }
        return self._anos[ano]

    @staticmethod
    def _base_de(datos: dict, cnpj: str) -> tuple[dict, tuple[str, str, str]] | None:
        """Elige consolidada o individual PARA ESTA EMPRESA, y su version.

        Preferir el fichero consolidado sin mirar lo que trae dentro tiene una
        trampa que costo encontrar: TIM S.A. presenta una consolidada **entera a
        cero** y las cifras de verdad en la individual. Con la regla ingenua,
        TIM salia con ingresos de cero —no ausentes, cero— y habria aparecido
        como una empresa en ruina en lugar de como un dato que hay que ir a
        buscar a otro sitio.

        Asi que la consolidada se usa solo si de verdad trae ingresos. La
        deteccion es la misma idea que la del contrato: una columna entera a
        nulo, o a cero, es un mapeo roto y no un dato.
        """
        for base in ("con", "ind"):
            dre = datos[base]["DRE"]
            claves = [k for k in dre if k[0] == cnpj]
            if not claves:
                continue
            # La version mas baja es el envio original. Una correccion posterior
            # es justamente lo que no se quiere ver.
            clave = min(claves, key=lambda k: int(k[2]))
            ventas = dre[clave].get(CUENTAS_DRE["ventas"])
            if isinstance(ventas, int | float) and ventas:
                return datos[base], clave
        return None

    def fundamentales(self, tickers: list[str], inicio: date, fin: date) -> pd.DataFrame:
        hoy = date.today()
        filas: list[dict] = []
        interesan = {t: c for t, c in self._empresas.items() if t in tickers}
        if not interesan:
            return pd.DataFrame()

        for ano in range(max(inicio.year, PRIMER_ANO), fin.year + 1):
            try:
                datos = self._cargar_ano(ano)
            except ErrorDatos:
                # Un ano que la CVM aun no ha publicado no puede tumbar los
                # quince anteriores.
                continue

            for ticker, cnpj in interesan.items():
                elegida = self._base_de(datos, cnpj)
                if elegida is None:
                    continue
                base, clave = elegida
                publicacion = datos["indice"].get(clave)
                fin_periodo = _fecha(clave[1])
                if publicacion is None or fin_periodo is None or publicacion > fin:
                    continue
                filas.append(
                    construir_fila(
                        ticker,
                        fin_periodo,
                        publicacion,
                        base["DRE"].get(clave, {}),
                        base["BPA"].get(clave, {}),
                        base["BPP"].get(clave, {}),
                        base["DFC"].get(clave, {}),
                        hoy,
                    )
                )
        return pd.DataFrame(filas)
