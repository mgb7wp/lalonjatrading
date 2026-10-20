"""Respaldo de precios (tarea M5): lo que la fuente principal no da.

El enrutador pide a `proveedor_datos.precios_respaldo`, en orden, los valores
que la fuente de precios no ha devuelto. Lo que se comprueba aqui:

- sin respaldo configurado, todo sigue igual que antes;
- cada valor se pide ENTERO a una sola fuente, nunca a trozos;
- cada fila dice de que fuente salio;
- una fuente de respaldo sin clave, o que falla, se salta y se anota;
- una fuente sin precios ajustados no puede ser respaldo.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest
from estrategia.datos import registro
from estrategia.datos.enrutador import Enrutador
from estrategia.datos.proveedor import Capacidades, ProveedorPrecios
from estrategia.errores import ErrorConfiguracion, ErrorDatos
from pydantic import ValidationError

FIN = dt.date(2024, 6, 14)
INICIO = FIN - dt.timedelta(days=14)
HOY = FIN + dt.timedelta(days=1)


def _serie(ticker: str, cierre: float = 10.0) -> pd.DataFrame:
    fechas = pd.bdate_range(INICIO, FIN).date
    n = len(fechas)
    return pd.DataFrame(
        {
            "fecha": fechas,
            "ticker": [ticker] * n,
            "apertura": [cierre] * n,
            "maximo": [cierre * 1.01] * n,
            "minimo": [cierre * 0.99] * n,
            "cierre": [cierre] * n,
            "cierre_bruto": [cierre] * n,
            "volumen": [1000.0] * n,
        }
    )


class _Fuente(ProveedorPrecios):
    """Fuente falsa: sirve los valores que se le dicen y anota que le piden."""

    def __init__(
        self,
        nombre: str,
        sirve: set[str],
        mercados: tuple[str, ...] | None = None,
        falla: bool = False,
        disponible: bool = True,
        ajustados: bool = True,
        cierre: float = 10.0,
    ) -> None:
        self.nombre = nombre
        self._sirve = sirve
        self._mercados = mercados
        self._falla = falla
        self._disponible = disponible
        self._ajustados = ajustados
        self._cierre = cierre
        self.pedidos: list[list[str]] = []
        self.avisos: list[str] = []

    @property
    def capacidades(self) -> Capacidades:
        return Capacidades(
            tipos=("precios",), mercados=self._mercados, precios_ajustados=self._ajustados
        )

    def disponible(self) -> tuple[bool, str]:
        return (True, "") if self._disponible else (False, "sin clave")

    def precios(self, tickers, inicio, fin):
        self.pedidos.append(list(tickers))
        if self._falla:
            raise ErrorDatos(f"{self.nombre} caida")
        lotes = [_serie(t, self._cierre) for t in tickers if t in self._sirve]
        return pd.concat(lotes, ignore_index=True) if lotes else pd.DataFrame()

    def fx(self, divisas, inicio, fin):
        raise ErrorDatos("no")

    def sectores(self, tickers):
        return dict.fromkeys(tickers)


@pytest.fixture()
def fuentes(monkeypatch):
    """Registra fuentes falsas y devuelve el diccionario para configurarlas."""
    creadas: dict[str, _Fuente] = {}

    def dar_de_alta(fuente: _Fuente) -> _Fuente:
        creadas[fuente.nombre] = fuente
        monkeypatch.setitem(registro._FUENTES, fuente.nombre, lambda cfg, f=fuente: f)
        return fuente

    return dar_de_alta


def _cfg(cfg, principal: str, respaldo: list[str]):
    datos = cfg.reglas.proveedor_datos.model_copy(
        update={"nombre": principal, "precios": None, "precios_respaldo": respaldo}
    )
    reglas = cfg.reglas.model_copy(update={"proveedor_datos": datos})
    return cfg.model_copy(update={"reglas": reglas})


def test_sin_respaldo_un_fallo_de_la_principal_sube_como_siempre(cfg, fuentes):
    fuentes(_Fuente("principal", set(), falla=True))
    e = Enrutador(_cfg(cfg, "principal", []), hoy=HOY)
    with pytest.raises(ErrorDatos, match="principal caida"):
        e.precios(["AAPL"], INICIO, FIN)


def test_sin_respaldo_lo_que_falta_se_queda_fuera(cfg, fuentes):
    fuentes(_Fuente("principal", {"AAPL"}))
    df = Enrutador(_cfg(cfg, "principal", []), hoy=HOY).precios(["AAPL", "MSFT"], INICIO, FIN)
    assert set(df["ticker"]) == {"AAPL"}


def test_el_respaldo_sirve_entero_lo_que_falta_y_lo_firma(cfg, fuentes):
    principal = fuentes(_Fuente("principal", {"AAPL"}))
    respaldo = fuentes(_Fuente("respaldo", {"AAPL", "MSFT"}, cierre=20.0))
    e = Enrutador(_cfg(cfg, "principal", ["respaldo"]), hoy=HOY)

    df = e.precios(["AAPL", "MSFT"], INICIO, FIN)

    assert principal.pedidos == [["AAPL", "MSFT"]]
    assert respaldo.pedidos == [["MSFT"]], "al respaldo solo se le pide lo que falta"
    assert set(df.loc[df["ticker"] == "AAPL", "fuente"]) == {"principal"}
    assert set(df.loc[df["ticker"] == "MSFT", "fuente"]) == {"respaldo"}
    # Entero: todas las sesiones, del respaldo y solo del respaldo.
    msft = df[df["ticker"] == "MSFT"]
    assert len(msft) == len(pd.bdate_range(INICIO, FIN))
    assert (msft["cierre"] == 20.0).all()
    assert any("servidos por 'respaldo'" in a for a in e.avisos)


def test_un_valor_que_la_principal_da_a_medias_no_se_cose_con_otra(cfg, fuentes):
    """Si la principal trae algo del valor, el respaldo no lo toca: dos fuentes
    no ajustan igual por dividendos y la costura seria un escalon falso."""

    class _AMedias(_Fuente):
        def precios(self, tickers, inicio, fin):
            self.pedidos.append(list(tickers))
            return _serie("AAPL").head(3)

    fuentes(_AMedias("principal", {"AAPL"}))
    respaldo = fuentes(_Fuente("respaldo", {"AAPL"}))
    df = Enrutador(_cfg(cfg, "principal", ["respaldo"]), hoy=HOY).precios(["AAPL"], INICIO, FIN)
    assert respaldo.pedidos == []
    assert set(df["fuente"]) == {"principal"}


def test_si_la_principal_cae_entera_el_respaldo_la_sustituye(cfg, fuentes):
    fuentes(_Fuente("principal", set(), falla=True))
    fuentes(_Fuente("respaldo", {"AAPL", "MSFT"}))
    e = Enrutador(_cfg(cfg, "principal", ["respaldo"]), hoy=HOY)

    df = e.precios(["AAPL", "MSFT"], INICIO, FIN)

    assert set(df["ticker"]) == {"AAPL", "MSFT"}
    assert set(df["fuente"]) == {"respaldo"}
    assert any("principal caida" in a for a in e.avisos)


def test_si_nadie_da_nada_es_un_error_y_no_una_descarga_vacia(cfg, fuentes):
    fuentes(_Fuente("principal", set(), falla=True))
    fuentes(_Fuente("respaldo", set()))
    with pytest.raises(ErrorDatos, match="ni 'principal' ni el respaldo"):
        Enrutador(_cfg(cfg, "principal", ["respaldo"]), hoy=HOY).precios(["AAPL"], INICIO, FIN)


def test_los_respaldos_se_prueban_en_orden(cfg, fuentes):
    fuentes(_Fuente("principal", set()))
    primero = fuentes(_Fuente("primero", {"AAPL"}))
    segundo = fuentes(_Fuente("segundo", {"AAPL", "MSFT"}))
    df = Enrutador(_cfg(cfg, "principal", ["primero", "segundo"]), hoy=HOY).precios(
        ["AAPL", "MSFT"], INICIO, FIN
    )
    assert primero.pedidos == [["AAPL", "MSFT"]]
    assert segundo.pedidos == [["MSFT"]]
    assert set(df.loc[df["ticker"] == "AAPL", "fuente"]) == {"primero"}
    assert set(df.loc[df["ticker"] == "MSFT", "fuente"]) == {"segundo"}


def test_a_cada_respaldo_solo_se_le_pide_su_mercado(cfg, fuentes):
    """Tiingo solo cubre EE. UU.: no se le pregunta por Inditex. El indice de
    regimen tiene mercado aunque no este en el universo; la referencia del
    informe no lo tiene y solo la pide una fuente sin restriccion."""
    fuentes(_Fuente("principal", set()))
    de_eeuu = fuentes(_Fuente("de_eeuu", {"AAPL", "^GSPC"}, mercados=("us",)))
    global_ = fuentes(_Fuente("global", {"ITX.MC", "EUNL.DE"}))
    indice = cfg.reglas.tecnico.indices_regimen["us"]

    Enrutador(_cfg(cfg, "principal", ["de_eeuu", "global"]), hoy=HOY).precios(
        ["AAPL", "ITX.MC", indice, "EUNL.DE"], INICIO, FIN
    )

    assert de_eeuu.pedidos == [["AAPL", indice]]
    assert global_.pedidos == [["ITX.MC", "EUNL.DE"]]


def test_un_respaldo_sin_clave_se_salta_y_se_anota(cfg, fuentes):
    fuentes(_Fuente("principal", set()))
    sin_clave = fuentes(_Fuente("sin_clave", {"AAPL"}, disponible=False))
    fuentes(_Fuente("otro", {"AAPL"}))
    e = Enrutador(_cfg(cfg, "principal", ["sin_clave", "otro"]), hoy=HOY)

    df = e.precios(["AAPL"], INICIO, FIN)

    assert sin_clave.pedidos == []
    assert set(df["fuente"]) == {"otro"}
    assert any("sin_clave] no disponible" in a for a in e.avisos)


def test_un_respaldo_que_falla_no_tumba_la_descarga(cfg, fuentes):
    fuentes(_Fuente("principal", {"AAPL"}))
    fuentes(_Fuente("caido", set(), falla=True))
    e = Enrutador(_cfg(cfg, "principal", ["caido"]), hoy=HOY)

    df = e.precios(["AAPL", "MSFT"], INICIO, FIN)

    assert set(df["ticker"]) == {"AAPL"}
    assert any("caido] ha fallado" in a for a in e.avisos)
    assert any("sin precios en ninguna fuente: MSFT" in a for a in e.avisos)


def test_una_fuente_sin_precios_ajustados_no_puede_ser_respaldo(cfg, fuentes):
    fuentes(_Fuente("principal", set()))
    fuentes(_Fuente("bruta", {"AAPL"}, ajustados=False))
    with pytest.raises(ErrorConfiguracion, match="no da precios ajustados"):
        Enrutador(_cfg(cfg, "principal", ["bruta"]), hoy=HOY).precios(["AAPL"], INICIO, FIN)


def test_la_b3_declara_que_no_ajusta(cfg):
    assert not registro.crear("b3", cfg).capacidades.precios_ajustados


def test_lo_que_trae_el_respaldo_pasa_la_misma_limpieza(cfg, fuentes):
    """La sesion en curso se aparta tambien de lo que llega por el respaldo:
    su "cierre" seria el ultimo precio del momento."""
    fuentes(_Fuente("principal", set()))
    fuentes(_Fuente("respaldo", {"AAPL"}))
    df = Enrutador(_cfg(cfg, "principal", ["respaldo"]), hoy=FIN).precios(["AAPL"], INICIO, FIN)
    assert FIN not in set(df["fecha"])
    assert not df.empty


def test_forzar_una_fuente_apaga_el_respaldo(cfg):
    """`--proveedor sintetico` no puede salir a la red por el respaldo."""
    forzada = _cfg(cfg, "yfinance", ["tiingo"]).con_fuente_unica("sintetico")
    assert forzada.reglas.proveedor_datos.precios_respaldo == []


@pytest.mark.parametrize(
    ("respaldo", "motivo"),
    [
        (["tiingo", "tiingo"], "repite"),
        (["yfinance"], "su propio respaldo"),
        (["sintetico"], "sintetico no puede"),
    ],
)
def test_configuraciones_de_respaldo_que_no_valen(cfg, respaldo, motivo):
    datos = cfg.reglas.proveedor_datos.model_dump()
    datos["precios_respaldo"] = respaldo
    with pytest.raises(ValidationError, match=motivo):
        type(cfg.reglas.proveedor_datos).model_validate(datos)


def test_el_respaldo_de_la_configuracion_real_es_utilizable(cfg_real):
    """Cada fuente de respaldo de `config/` existe, sirve precios y los ajusta.

    Hoy la lista esta vacia hasta verificar las fuentes en el servidor; el test
    sigue valiendo cuando se llene.
    """
    for nombre in cfg_real.reglas.proveedor_datos.precios_respaldo:
        cap = registro.crear(nombre, cfg_real).capacidades
        assert cap.sirve("precios"), nombre
        assert cap.precios_ajustados, nombre
