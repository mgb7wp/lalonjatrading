"""Sectores desconocidos (tarea B8).

El fallo: un sector que el proveedor devolvia y el mapeo no conocia acababa
usando el `sector_declarado` de universo.yaml. Contradice SUPUESTOS.md ("un
sector que el mapeo no reconoce rechaza el valor"): una etiqueta nueva del
proveedor —que podria ser la de un banco— quedaba tapada por lo que alguien
escribio a mano, sin que nadie revisara la traduccion.

La regla que queda:

- el proveedor no da sector -> se usa el `sector_declarado` (para eso esta);
- el proveedor da un sector que el mapeo no conoce -> el valor se rechaza y el
  diagnostico imprime la linea de YAML que hay que pegar.
"""

from __future__ import annotations

import datetime as dt

import yaml
from estrategia import universo as universo_mod
from estrategia.diagnostico import FilaDiagnostico, a_texto, yaml_sectores
from estrategia.sectores import MapaSectores
from estrategia.tipos import MotivoRechazo


def _declarado(cfg, ticker):
    return cfg.universo.valores_por_ticker[ticker].sector_declarado


def test_un_sector_desconocido_rechaza_aunque_el_valor_este_en_el_universo(cfg):
    """El caso que el test antiguo no cubria: ITX.MC tiene `sector_declarado`,
    y antes ese respaldo lo dejaba pasar."""
    mapa = MapaSectores(cfg)
    c = mapa.clasificar("ITX.MC", "Conglomerates")
    assert not c.admitido
    assert c.motivo == MotivoRechazo.SECTOR_DESCONOCIDO
    assert mapa.sin_mapear == {"Conglomerates": ["ITX.MC"]}


def test_un_banco_con_etiqueta_nueva_no_se_cuela(cfg):
    """Un valor declarado como industrial al que el proveedor llama con una
    etiqueta bancaria que el mapeo no conoce: fuera, no industrial."""
    ticker = next(t for t in cfg.universo.tickers() if _declarado(cfg, t) == "industrial")
    c = MapaSectores(cfg).clasificar(ticker, "Regional Banking Group")
    assert not c.admitido
    assert c.sector != "industrial"


def test_sin_sector_del_proveedor_se_usa_el_declarado(cfg):
    mapa = MapaSectores(cfg)
    for vacio in (None, ""):
        c = mapa.clasificar("ITX.MC", vacio)
        assert c.admitido
        assert c.sector == _declarado(cfg, "ITX.MC")
    # Y eso no es un sector sin mapear: no hay nada que traducir.
    assert mapa.sin_mapear == {}


def test_un_sector_conocido_manda_sobre_el_declarado(cfg):
    """Si el proveedor dice banco, es banco, declare lo que declare universo.yaml."""
    c = MapaSectores(cfg).clasificar("ITX.MC", "Banks")
    assert not c.admitido
    assert c.motivo == MotivoRechazo.SECTOR_EXCLUIDO


def test_el_universo_deja_fuera_los_sectores_sin_mapear(cfg, instantanea):
    """El proveedor sintetico devuelve 'Conglomerates' para LOG.MC y TOTS3.SA,
    justo para ejercitar este caso."""
    fecha = dt.date(2024, 6, 28)
    mapa = MapaSectores(cfg)
    resultado = universo_mod.evaluar(fecha, instantanea.vista(fecha), cfg, mapa)
    for ticker in ("LOG.MC", "TOTS3.SA"):
        assert not resultado[ticker].elegible
        assert resultado[ticker].motivo == MotivoRechazo.SECTOR_DESCONOCIDO
    assert set(mapa.sin_mapear["Conglomerates"]) == {"LOG.MC", "TOTS3.SA"}


# --------------------------------------------------------------------------
# El diagnostico imprime el YAML que hay que pegar
# --------------------------------------------------------------------------


def _fila(ticker, mercado, sector_proveedor):
    return FilaDiagnostico(
        ticker=ticker,
        mercado=mercado,
        sesiones=100,
        sector_proveedor=sector_proveedor,
        sector_mapeado=False,
    )


def _bloque_yaml(lineas):
    inicio = lineas.index("```yaml") + 1
    fin = lineas.index("```", inicio)
    return "\n".join(lineas[inicio:fin])


def test_el_yaml_propone_el_sector_declarado_si_todos_coinciden(cfg):
    ind = [t for t in cfg.universo.tickers() if _declarado(cfg, t) == "industrial"][:2]
    filas = [_fila(t, cfg.universo.mercado_de_ticker[t], "Conglomerates") for t in ind]
    lineas = yaml_sectores(filas, cfg)

    texto = _bloque_yaml(lineas)
    # Se puede pegar tal cual: es YAML valido y dice lo que tiene que decir.
    assert yaml.safe_load(texto) == {"sectores": {"Conglomerates": "industrial"}}
    assert all(t in texto for t in ind)


def test_si_los_declarados_no_coinciden_la_linea_sale_comentada(cfg):
    """Hay que decidir a mano, y pegar una linea comentada no cambia nada."""
    ind = next(t for t in cfg.universo.tickers() if _declarado(cfg, t) == "industrial")
    ele = next(t for t in cfg.universo.tickers() if _declarado(cfg, t) == "electricas")
    filas = [
        _fila(ind, cfg.universo.mercado_de_ticker[ind], "Diversified"),
        _fila(ele, cfg.universo.mercado_de_ticker[ele], "Diversified"),
    ]
    texto = _bloque_yaml(yaml_sectores(filas, cfg))
    assert yaml.safe_load(texto) == {"sectores": None}
    assert '# "Diversified": ???' in texto
    assert f"{ind}=industrial" in texto and f"{ele}=electricas" in texto


def test_sin_sectores_por_mapear_no_hay_yaml(cfg):
    fila = FilaDiagnostico(ticker="ITX.MC", mercado="es", sesiones=1, sector_mapeado=True)
    assert yaml_sectores([fila], cfg) == []


def test_el_informe_del_diagnostico_incluye_el_yaml(cfg):
    texto = a_texto([_fila("ITX.MC", "es", "Conglomerates")], cfg)
    assert "Que anadir a implementacion.yaml" in texto
    assert f'"Conglomerates": {_declarado(cfg, "ITX.MC")}' in texto
