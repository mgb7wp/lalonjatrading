#!/usr/bin/env python
"""Comprueba, una a una, que hace de verdad cada fuente de datos.

    python scripts/verify_sources.py
    python scripts/verify_sources.py --fuente sec

`docs/DATA_SOURCES.md` esta escrito contra la documentacion de cada proveedor,
no contra su comportamiento: el entorno donde se desarrollo bloquea sec.gov,
stooq.com y data-api.ecb.europa.eu por politica de red. Todo lo que hay ahi
marcado como POR VERIFICAR es una hipotesis, y este script es lo que la convierte
en un hecho o la desmiente.

**Ninguna fuente deberia entrar en el pipeline sin pasar por aqui primero.** Una
fuente que responde 200 no es una fuente que sirva: puede devolver la mitad de
las columnas a nulo, ajustar los precios de otra manera o dar fechas de
publicacion estimadas haciendolas pasar por reales. Eso es lo que se mira.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

#: Un valor por mercado, para no gastar cuota comprobando 140.
MUESTRA = {"us": "AAPL", "es": "ITX.MC", "de": "SAP.DE", "in": "RELIANCE.NS", "br": "PETR4.SA"}

#: Valor con dividendo alto y estable, para la comprobacion de ajuste de Stooq.
#: Si una fuente no ajusta por dividendos, aqui es donde mas se nota.
TESTIGO_DIVIDENDO = "KO"


@dataclass
class Comprobacion:
    fuente: str
    prueba: str
    resultado: str
    detalle: str = ""

    def __str__(self) -> str:
        marca = {"ok": "OK  ", "aviso": "AVISO", "fallo": "FALLO", "omitida": "--  "}[
            self.resultado
        ]
        cola = f" - {self.detalle}" if self.detalle else ""
        return f"  [{marca}] {self.prueba}{cola}"


@dataclass
class Informe:
    comprobaciones: list[Comprobacion] = field(default_factory=list)

    def anotar(self, *args, **kwargs) -> None:
        self.comprobaciones.append(Comprobacion(*args, **kwargs))

    @property
    def fallos(self) -> int:
        return sum(1 for c in self.comprobaciones if c.resultado == "fallo")


def _probar(informe: Informe, fuente: str, prueba: str, funcion) -> object | None:
    """Ejecuta una prueba convirtiendo cualquier fallo en una linea del informe.

    El script tiene que terminar siempre: lo que interesa es la tabla completa de
    que sirve y que no, no la primera excepcion.
    """
    try:
        valor = funcion()
    except Exception as exc:  # noqa: BLE001 - aqui todo fallo es un resultado
        informe.anotar(fuente, prueba, "fallo", f"{type(exc).__name__}: {exc}")
        return None
    return valor


def verificar_sec(cfg, informe: Informe) -> None:
    from estrategia.datos.sec_proveedor import ProveedorSEC

    fuente = ProveedorSEC(cfg)
    ok, motivo = fuente.disponible()
    if not ok:
        informe.anotar("sec", "disponibilidad", "omitida", motivo)
        return
    informe.anotar("sec", "disponibilidad", "ok")

    cik = _probar(informe, "sec", "resuelve el CIK de AAPL", lambda: fuente.cik_de("AAPL"))
    if not cik:
        return
    informe.anotar("sec", "resuelve el CIK de AAPL", "ok", cik)

    df = _probar(
        informe,
        "sec",
        "descarga fundamentales de AAPL",
        lambda: fuente.fundamentales(["AAPL"], dt.date(2015, 1, 1), dt.date.today()),
    )
    if df is None:
        return  # _probar ya lo ha anotado
    if df.empty:
        informe.anotar("sec", "descarga fundamentales de AAPL", "fallo", "sin filas")
        return
    informe.anotar("sec", "descarga fundamentales de AAPL", "ok", f"{len(df)} ejercicios")

    # La afirmacion que hay que comprobar de verdad: que las fechas son reales y
    # que las cifras son las de su momento.
    if (df["origen_pit"] == "capturado").all():
        informe.anotar("sec", "point-in-time real", "ok", "todas las filas capturadas")
    else:
        informe.anotar("sec", "point-in-time real", "fallo", "hay filas reconstruidas")

    # Y la que de verdad decide si la fuente sirve: que las columnas
    # obligatorias no vengan enteras a nulo. Es el fallo que ya ocurrio una vez
    # en este proyecto con el EV de yfinance.
    _verificar_contrato_fundamentales(informe, "sec", df)

    # Las fechas viajan como `datetime.date` de Python por todo el motor, no como
    # marcas de tiempo de pandas, asi que `.dt` no sirve: se restan a mano.
    # Que etiquetas XBRL cubren cada magnitud. Una serie cosida a partir de dos
    # es lo normal cuando cambia una norma contable; lo que no puede pasar
    # desapercibido es cuantas y donde cae el corte, porque ahi puede haber un
    # escalon que no es un cambio del negocio.
    from estrategia.datos.sec_proveedor import conceptos_por_magnitud

    hechos: dict = {}
    ficha = fuente.ficha("AAPL")
    for espacio in ("us-gaap", "ifrs-full", "dei"):
        hechos.update((ficha.get("facts") or {}).get(espacio) or {})
    for magnitud, cuenta in conceptos_por_magnitud(hechos).items():
        if len(cuenta) > 1:
            partes = ", ".join(f"{k}={v}" for k, v in sorted(cuenta.items(), key=lambda x: -x[1]))
            informe.anotar(
                "sec",
                f"serie de {magnitud} cosida",
                "aviso",
                f"{sum(cuenta.values())} ejercicios de {len(cuenta)} etiquetas: {partes}",
            )

    # Cobertura de TODO el universo estadounidense, no solo de la muestra.
    # Un ticker cuyo CIK apunta a una entidad reorganizada sin historico devuelve
    # cero ejercicios sin que nada falle, y en un ranking eso es simplemente una
    # empresa que no aparece: es como se perdio ExxonMobil, cuyo ticker resuelve
    # a un CIK que solo ha presentado trimestrales.
    universo = cfg.universo.tickers("us")
    completo = _probar(
        informe,
        "sec",
        "cubre el universo de EE. UU.",
        lambda: fuente.fundamentales(universo, dt.date(2009, 1, 1), dt.date.today()),
    )
    if completo is not None:
        cubiertos = set(completo["ticker"].unique()) if not completo.empty else set()
        faltan = sorted(set(universo) - cubiertos)
        informe.anotar(
            "sec",
            "cubre el universo de EE. UU.",
            "ok" if not faltan else "fallo",
            f"{len(cubiertos)}/{len(universo)} valores"
            + (
                f"; sin ejercicios anuales: {', '.join(faltan)}. Revisa si su CIK "
                f"apunta a una entidad reorganizada y anotalo en `cik_sec`"
                if faltan
                else ""
            ),
        )

    retraso = sorted((a - b).days for a, b in zip(df["fecha_publicacion"], df["fin_periodo"]))
    mediana = retraso[len(retraso) // 2]
    informe.anotar(
        "sec",
        "retraso de publicacion",
        "ok",
        f"mediana {mediana} dias, rango {retraso[0]}-{retraso[-1]} "
        f"(si fueran todos identicos, estaria estimado y no seria real)",
    )


def _verificar_contrato_fundamentales(informe: Informe, fuente: str, df) -> None:
    from estrategia.datos import contrato

    inf = contrato.verificar_fundamentales(df, fuente)
    if inf.cumple:
        informe.anotar(fuente, "cumple el contrato", "ok")
    else:
        for i in inf.incumplimientos:
            informe.anotar(fuente, "cumple el contrato", "fallo", str(i))

    vacias = [c for c in ("ventas", "ebit", "ebitda", "patrimonio_neto") if df[c].isna().all()]
    if vacias:
        informe.anotar(fuente, "columnas clave con dato", "fallo", f"enteras a nulo: {vacias}")
    else:
        huecos = {c: f"{df[c].isna().mean():.0%}" for c in ("ventas", "ebit", "ebitda")}
        informe.anotar(fuente, "columnas clave con dato", "ok", f"huecos {huecos}")


def verificar_bce(cfg, informe: Informe) -> None:
    from estrategia.datos.bce_proveedor import ProveedorBCE

    fuente = ProveedorBCE(cfg)
    fin = dt.date.today()
    inicio = fin - dt.timedelta(days=30)
    df = _probar(
        informe,
        "bce",
        "descarga USD/INR/BRL",
        lambda: fuente.fx(["USD", "INR", "BRL"], inicio, fin),
    )
    if df is None:
        return  # _probar ya lo ha anotado
    if df.empty:
        informe.anotar("bce", "descarga USD/INR/BRL", "fallo", "sin filas")
        return
    informe.anotar("bce", "descarga USD/INR/BRL", "ok", f"{len(df)} observaciones")

    faltan = {"USD", "INR", "BRL"} - set(df["divisa"])
    if faltan:
        informe.anotar("bce", "cubre las tres divisas", "fallo", f"falta {faltan}")
    else:
        informe.anotar("bce", "cubre las tres divisas", "ok")

    # El sentido del tipo importa mas que su valor: invertido, la cartera se
    # valora mal sin que nada falle. Un euro son bastante mas de una unidad de
    # rupia o de real, y bastante mas de 0,5 dolares.
    usd = df[df["divisa"] == "USD"]["tasa"]
    if not usd.empty:
        sentido = "ok" if 0.5 < usd.iloc[-1] < 2.0 else "fallo"
        informe.anotar(
            "bce",
            "sentido EUR->divisa",
            sentido,
            f"1 EUR = {usd.iloc[-1]:.4f} USD (si saliera ~0,9 estaria invertido)",
        )

    ultima = df["fecha"].max()
    dias = (fin - ultima).days
    informe.anotar(
        "bce",
        "frescura",
        "ok" if dias <= 5 else "aviso",
        f"ultimo dato {ultima} ({dias} dias)",
    )


def verificar_stooq(cfg, informe: Informe) -> None:
    from estrategia.datos.stooq_proveedor import ProveedorStooq

    fuente = ProveedorStooq(cfg)
    fin = dt.date.today()
    inicio = fin - dt.timedelta(days=365)

    cubiertos = []
    for mercado, ticker in MUESTRA.items():
        df = _probar(
            informe,
            "stooq",
            f"cubre {mercado} ({ticker})",
            lambda t=ticker: fuente.precios([t], inicio, fin),
        )
        if df is None:
            continue
        if df.empty:
            informe.anotar("stooq", f"cubre {mercado} ({ticker})", "fallo", "sin datos")
        else:
            cubiertos.append(mercado)
            informe.anotar("stooq", f"cubre {mercado} ({ticker})", "ok", f"{len(df)} sesiones")

    if len(cubiertos) < len(MUESTRA):
        informe.anotar(
            "stooq",
            "cobertura de los cinco mercados",
            "aviso",
            f"solo {cubiertos}; como respaldo de precios no cubre todo",
        )

    _comparar_ajuste_dividendos(cfg, informe, fuente, inicio, fin)


def _comparar_ajuste_dividendos(cfg, informe: Informe, stooq, inicio, fin) -> None:
    """La comprobacion que decide si Stooq puede ser duena de precios.

    Se compara con yfinance sobre un valor que reparte dividendo alto. Si los
    dos ajustan igual, la rentabilidad acumulada del periodo coincide salvo
    redondeo. Si Stooq no ajusta por dividendos, se queda por debajo de forma
    sistematica, y la diferencia se parece a la rentabilidad por dividendo
    acumulada del periodo.

    Sin esta comprobacion, usar Stooq como fuente principal convierte cada
    reparto en una caida que el motor leera como senal.
    """
    from estrategia.datos.yfinance_proveedor import ProveedorYFinance

    yf = ProveedorYFinance(cfg)
    datos = _probar(
        informe,
        "stooq",
        "ajuste por dividendos",
        lambda: (
            stooq.precios([TESTIGO_DIVIDENDO], inicio, fin),
            yf.precios([TESTIGO_DIVIDENDO], inicio, fin),
        ),
    )
    if datos is None:
        return
    a, b = datos
    if a.empty or b.empty:
        informe.anotar("stooq", "ajuste por dividendos", "omitida", "falta una de las dos series")
        return

    def retorno(df):
        s = df.sort_values("fecha")["cierre"]
        return float(s.iloc[-1] / s.iloc[0] - 1.0)

    ra, rb = retorno(a), retorno(b)
    diferencia = rb - ra
    if abs(diferencia) < 0.005:
        informe.anotar(
            "stooq",
            "ajuste por dividendos",
            "ok",
            f"coincide con yfinance ({ra:.2%} vs {rb:.2%}): ajusta igual",
        )
    else:
        informe.anotar(
            "stooq",
            "ajuste por dividendos",
            "fallo",
            f"{ra:.2%} frente a {rb:.2%} en yfinance (diferencia {diferencia:+.2%}). "
            f"NO la uses como duena de precios: cada dividendo saldra como una caida",
        )


def verificar_yfinance(cfg, informe: Informe) -> None:
    from estrategia.datos.yfinance_proveedor import ProveedorYFinance

    fuente = ProveedorYFinance(cfg)
    fin = dt.date.today()
    inicio = fin - dt.timedelta(days=30)
    tickers = list(MUESTRA.values())
    df = _probar(
        informe,
        "yfinance",
        "descarga precios de los cinco mercados",
        lambda: fuente.precios(tickers, inicio, fin),
    )
    if df is None:
        return  # _probar ya lo ha anotado
    if df.empty:
        informe.anotar("yfinance", "descarga precios de los cinco mercados", "fallo", "sin filas")
        return
    devueltos = set(df["ticker"].unique())
    faltan = set(tickers) - devueltos
    informe.anotar(
        "yfinance",
        "descarga precios de los cinco mercados",
        "ok" if not faltan else "aviso",
        f"{len(devueltos)}/{len(tickers)} tickers" + (f"; falta {faltan}" if faltan else ""),
    )


def verificar_cvm(cfg, informe: Informe) -> None:
    """Comprueba la CVM y, sobre todo, que el mapeo CNPJ->ticker es correcto.

    Lo segundo importa mas que lo primero. La CVM identifica a las empresas por
    CNPJ y no publica el ticker, asi que el enlace esta escrito a mano en
    `config/cvm_empresas.yaml`. Un CNPJ equivocado no rompe nada: calcula las
    cuentas de otra empresa y las sirve como buenas.

    El contraste es con yfinance, que da unos cuatro ejercicios de los mismos
    valores. Si los ingresos de las dos fuentes coinciden, la empresa es la que
    creemos. Si no, o el mapeo esta mal o hay algo que entender.
    """
    import datetime as dt

    from estrategia.datos.cvm_proveedor import ProveedorCVM
    from estrategia.datos.yfinance_proveedor import ProveedorYFinance

    fuente = ProveedorCVM(cfg)
    tickers = cfg.universo.tickers("br")
    fin = dt.date.today()

    cvm = _probar(
        informe,
        "cvm",
        "descarga fundamentales brasilenos",
        lambda: fuente.fundamentales(tickers, dt.date(fin.year - 1, 1, 1), fin),
    )
    if cvm is None:
        return
    if cvm.empty:
        informe.anotar("cvm", "descarga fundamentales brasilenos", "fallo", "sin filas")
        return
    informe.anotar(
        "cvm",
        "descarga fundamentales brasilenos",
        "ok",
        f"{len(cvm)} filas de {cvm['ticker'].nunique()}/{len(tickers)} valores",
    )

    if (cvm["origen_pit"] == "capturado").all():
        informe.anotar("cvm", "point-in-time real", "ok", "todas las filas capturadas")
    else:
        informe.anotar("cvm", "point-in-time real", "fallo", "hay filas reconstruidas")

    _verificar_contrato_fundamentales(informe, "cvm", cvm)

    yf = _probar(
        informe,
        "cvm",
        "contraste con yfinance",
        lambda: ProveedorYFinance(cfg).fundamentales(tickers, dt.date(fin.year - 3, 1, 1), fin),
    )
    if yf is None or yf.empty:
        informe.anotar("cvm", "contraste con yfinance", "omitida", "sin datos de contraste")
        return

    iguales, divisa, reexpresadas, sospechosos, sin_contraste = 0, [], [], [], 0
    for ticker in tickers:
        a, b = cvm[cvm.ticker == ticker], yf[yf.ticker == ticker]
        if a.empty or b.empty:
            sin_contraste += 1
            continue
        comunes = set(a.fin_periodo) & set(b.fin_periodo)
        if not comunes:
            sin_contraste += 1
            continue
        periodo = max(comunes)
        va = float(a[a.fin_periodo == periodo].ventas.iloc[0])
        vb = float(b[b.fin_periodo == periodo].ventas.iloc[0])
        if not vb:
            sin_contraste += 1
            continue
        razon = va / vb
        if abs(razon - 1.0) < 0.05:
            iguales += 1
        elif abs(razon - 1.0) < 0.15:
            # Una diferencia pequena no es un mapeo malo: es lo que se espera.
            # La CVM da la cifra tal y como se publico y yfinance la reexpresada
            # a hoy, asi que las empresas que corrigieron sus cuentas TIENEN que
            # diferir. Es la propiedad point-in-time funcionando, no un fallo.
            reexpresadas.append(f"{ticker} (x{razon:.2f})")
        elif 4.0 < razon < 7.0:
            # No es un mapeo equivocado: es que yfinance informa esa empresa en
            # dolares y la CVM en reales. Petrobras y Vale reportan asi.
            divisa.append(f"{ticker} (x{razon:.2f})")
        else:
            sospechosos.append(f"{ticker} (x{razon:.2f})")

    informe.anotar(
        "cvm",
        "el mapeo CNPJ->ticker cuadra",
        "ok" if not sospechosos else "fallo",
        f"{iguales} coinciden, {len(reexpresadas)} con diferencia pequena, "
        f"{len(divisa)} en otra divisa, {sin_contraste} sin contraste"
        + (f"; REVISAR: {', '.join(sospechosos)}" if sospechosos else ""),
    )
    if reexpresadas:
        informe.anotar(
            "cvm",
            "diferencias pequenas frente a yfinance",
            "aviso",
            f"{', '.join(reexpresadas)} - probable reexpresion: la CVM da la cifra "
            f"original y yfinance la corregida. Es lo que se espera.",
        )
    if divisa:
        informe.anotar(
            "cvm",
            "empresas que yfinance informa en dolares",
            "aviso",
            f"{', '.join(divisa)} - la cifra buena es la de la CVM, en reales",
        )


VERIFICADORES = {
    "sec": verificar_sec,
    "cvm": verificar_cvm,
    "bce": verificar_bce,
    "stooq": verificar_stooq,
    "yfinance": verificar_yfinance,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fuente", choices=sorted(VERIFICADORES), help="solo una")
    args = parser.parse_args(argv)

    from estrategia import config as core_config

    cfg = core_config.cargar()
    informe = Informe()
    fuentes = [args.fuente] if args.fuente else list(VERIFICADORES)

    for nombre in fuentes:
        print(f"\n{nombre}")
        antes = len(informe.comprobaciones)
        VERIFICADORES[nombre](cfg, informe)
        for c in informe.comprobaciones[antes:]:
            print(c)

    print(
        f"\n{len(informe.comprobaciones)} comprobaciones, {informe.fallos} fallos.\n"
        f"Actualiza docs/DATA_SOURCES.md con lo que salga: mientras una fila siga "
        f"marcada POR VERIFICAR, es una hipotesis."
    )
    return 1 if informe.fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
