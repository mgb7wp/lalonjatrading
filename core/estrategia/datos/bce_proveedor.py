"""Fuente BCE: tipos de cambio de referencia del euro.

Oficial, gratuita, sin clave y estable. Para una cartera medida en euros es la
fuente correcta: es el mismo tipo que usan la contabilidad y la Agencia
Tributaria, y no depende de que un agregador siga funcionando la semana que
viene.

## El detalle que importa: cuando se publican

El BCE fija los tipos de referencia sobre las 14:15 CET y los publica poco
despues. Decidir una operacion con el tipo del mismo dia es usar un dato que, a
la hora de la decision, todavia no existia. La configuracion ya lo resuelve
(`datos.fx_decision_dia_anterior: true`): se decide y se dimensiona con el tipo
de D-1 y se valora con el de D. Esta fuente no tiene que hacer nada especial,
pero conviene que quede escrito aqui tambien, porque es el tipo de sesgo que se
reintroduce solo en cuanto alguien "simplifica".

## Huecos

El BCE no publica fines de semana ni festivos de TARGET. No se rellenan: el
motor busca el ultimo tipo conocido en o antes de la fecha, asi que un hueco se
resuelve solo y sin inventar una cotizacion que no existio.

## Lentitud, que no es un detalle

La API es oficial y gratuita, y se nota: ocho anios de una divisa son ~2.200
filas y tardan entre quince segundos y varios minutos segun el dia y desde
donde se pida. Con un solo intento y poco margen, la descarga falla en un
servidor con peor ruta hacia Frankfurt aunque funcione desde un portatil. Por
eso hay reintentos y una espera generosa, configurable con `BCE_TIMEOUT`.
"""

from __future__ import annotations

import csv
import io
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime

import pandas as pd

from ..config import Config
from ..errores import ErrorDatos
from .proveedor import Capacidades, Fuente

BASE = "https://data-api.ecb.europa.eu/service/data/EXR"

#: Segundos de espera por peticion. Generoso a proposito: 60 alcanzaba desde una
#: maquina con buena ruta y no desde el servidor, y el sintoma era una etapa
#: entera caida por un limite que nadie habia medido. Es configuracion de
#: despliegue —depende de la red, no de la estrategia— asi que va en el entorno.
VARIABLE_ESPERA = "BCE_TIMEOUT"
ESPERA_POR_DEFECTO = 180

#: Tres intentos con espera creciente. Una API publica y gratuita tiene malos
#: ratos, y rendirse al primero convierte un tropiezo de treinta segundos en un
#: dia sin tipos de cambio.
INTENTOS = 3
ESPERA_ENTRE_INTENTOS = (5, 20)

#: Clave de la serie: frecuencia diaria, divisa, contra EUR, tipo de referencia,
#: media. `D.USD.EUR.SP00.A` es "cuantos dolares vale un euro", que es justo el
#: sentido EUR -> divisa que usa el proyecto. Un solo convenio en todo el codigo.
PLANTILLA_SERIE = "D.{divisa}.EUR.SP00.A"


def parsear_csv(texto: str, divisa: str) -> list[dict]:
    """Convierte la respuesta CSV del BCE en filas `fecha/divisa/tasa`.

    Funcion pura y con tests. El CSV del Data Portal trae muchas columnas de
    metadatos y solo interesan dos, asi que se buscan por nombre: fiarse de la
    posicion es lo que rompe el dia que el BCE anade una columna.
    """
    filas: list[dict] = []
    lector = csv.DictReader(io.StringIO(texto))
    if lector.fieldnames is None:
        return filas
    if "TIME_PERIOD" not in lector.fieldnames or "OBS_VALUE" not in lector.fieldnames:
        raise ErrorDatos(
            "la respuesta del BCE no trae TIME_PERIOD y OBS_VALUE; "
            f"columnas recibidas: {lector.fieldnames}"
        )

    for fila in lector:
        crudo = (fila.get("OBS_VALUE") or "").strip()
        # El BCE marca los dias sin cotizacion con 'NaN' o con la celda vacia.
        # Se descartan en lugar de arrastrarse como ceros, que serian tipos de
        # cambio imposibles y el contrato los rechazaria con razon.
        if not crudo or crudo.upper() == "NAN":
            continue
        try:
            tasa = float(crudo)
            fecha = datetime.strptime(fila["TIME_PERIOD"][:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        if tasa <= 0:
            continue
        filas.append({"fecha": fecha, "divisa": divisa, "tasa": tasa})
    return filas


class ProveedorBCE(Fuente):
    """Tipos de cambio de referencia del euro."""

    nombre = "bce"

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("divisas",),
            necesita_clave=False,
            notas=(
                "Fuente oficial del tipo de referencia del euro.",
                "Se publica sobre las 14:15 CET: la decision del dia usa el de D-1.",
                "Sin datos en fines de semana ni festivos de TARGET.",
            ),
        )

    def _pedir(self, divisa: str, inicio: date, fin: date) -> str:
        serie = PLANTILLA_SERIE.format(divisa=divisa)
        url = (
            f"{BASE}/{serie}?format=csvdata"
            f"&startPeriod={inicio.isoformat()}&endPeriod={fin.isoformat()}"
        )
        espera = int(os.environ.get(VARIABLE_ESPERA, ESPERA_POR_DEFECTO))
        ultimo: Exception | None = None

        for intento in range(INTENTOS):
            try:
                with urllib.request.urlopen(url, timeout=espera) as respuesta:
                    return respuesta.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                # Un 404 no mejora reintentando: la serie no existe.
                if exc.code == 404:
                    raise ErrorDatos(
                        f"el BCE no publica la serie {serie}; revisa el codigo de divisa"
                    ) from exc
                raise ErrorDatos(f"el BCE ha respondido {exc.code} a {serie}") from exc
            # `TimeoutError` NO es subclase de `URLError`, asi que el `except` de
            # abajo no lo captura: un tiempo agotado al LEER se escapaba crudo y
            # el pipeline registraba "TimeoutError" en lugar del error del
            # contrato. Va primero y explicito para que no vuelva a colarse.
            except (TimeoutError, urllib.error.URLError) as exc:
                ultimo = exc
                if intento < INTENTOS - 1:
                    time.sleep(ESPERA_ENTRE_INTENTOS[intento])

        motivo = getattr(ultimo, "reason", ultimo)
        raise ErrorDatos(
            f"el BCE no ha respondido a {serie} en {INTENTOS} intentos de {espera}s "
            f"({motivo}). Si se repite, sube {VARIABLE_ESPERA}."
        ) from ultimo

    def fx(self, divisas: list[str], inicio: date, fin: date) -> pd.DataFrame:
        filas: list[dict] = []
        for divisa in divisas:
            # El euro contra si mismo no es una serie: es un 1 y el BCE no lo
            # publica. Pedirlo seria un 404 garantizado.
            if divisa.upper() == "EUR":
                continue
            filas.extend(parsear_csv(self._pedir(divisa.upper(), inicio, fin), divisa.upper()))
        return pd.DataFrame(filas)
