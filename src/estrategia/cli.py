"""Interfaz de linea de comandos.

Se apoya en `argparse` de la biblioteca estandar a proposito: es una dependencia
menos, y lo que hace falta aqui son siete subcomandos y un par de opciones.

El comando `foto` merece una nota. El documento pide guardar cada semana una
copia de los fundamentales y del tipo de cambio "desde el primer dia", para ir
construyendo un historico propio sin sesgo de anticipacion. Una app de escritorio
no tiene forma de hacerlo sola, asi que el comando esta pensado para programarlo
(cron en Linux o macOS, Programador de tareas en Windows) y es idempotente por
semana: ejecutarlo dos veces el mismo lunes no duplica nada.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from . import backtest as backtest_mod
from . import config as config_mod
from . import diagnostico as diagnostico_mod
from . import informe as informe_mod
from . import informe_html as informe_html_mod
from . import metricas as metricas_mod
from . import universo as universo_mod
from . import validacion as validacion_mod
from .datos.almacen import Instantanea
from .datos.enrutador import Enrutador
from .errores import ErrorEstrategia
from .sectores import MapaSectores

RAIZ = config_mod.RAIZ
DIR_DATOS = RAIZ / "datos"
DIR_CACHE = DIR_DATOS / "cache"
DIR_FOTOS = DIR_DATOS / "fotos"
DIR_RESULTADOS = DIR_DATOS / "resultados"
DIR_SITIO = RAIZ / "sitio"
RUTA_CONSULTAS = DIR_DATOS / "consultas_validacion.json"


def _enrutador(cfg, forzar: str | None = None) -> Enrutador:
    """El enrutador de fuentes, con la opcion de forzar una sola desde el CLI.

    Sin `--proveedor` manda el reparto de `reglas.yaml`. La opcion sigue
    existiendo porque es comoda para los tests y para trabajar sin red, pero
    tiene que pedirse a proposito: un valor por defecto que forzara una fuente
    haria inalcanzable el reparto y, si esa fuente fuera la sintetica, daria
    datos inventados a quien cree estar trabajando con los reales.
    """
    if forzar:
        cfg = cfg.con_fuente_unica(forzar)
    return Enrutador(cfg)


def _nombre_cache(args, cfg) -> str:
    """Carpeta de `datos/cache/` que corresponde a esta ejecucion.

    Es el origen de los datos (`yfinance`, `eodhd+yfinance`, `sintetico`...), el
    mismo que queda anotado en la instantanea. Asi `datos` escribe justo donde
    luego leen los demas comandos y el panel, que ofrece una opcion por carpeta.
    """
    return _enrutador(cfg, args.proveedor).origen


def _opcion_proveedor(args) -> str:
    """Como repetir la opcion `--proveedor` en un mensaje, si se uso."""
    return f"--proveedor {args.proveedor} " if args.proveedor else ""


def _descargar(cfg, nombre_proveedor: str | None, inicio: date, fin: date) -> Instantanea:
    """Descarga cada tipo de dato por separado.

    Un tipo que falla no arrastra a los demas: se anota en
    `Instantanea.incompletos`, se deja vacio y quien guarde decide si conserva
    el de la descarga anterior. Las filas que se han tenido que reparar o
    apartar se imprimen como avisos.
    """
    enrutador = _enrutador(cfg, nombre_proveedor)

    problemas = enrutador.comprobar_disponibilidad()
    if problemas:
        for p in problemas:
            print(f"  fuente no disponible -> {p}", file=sys.stderr)
        raise SystemExit(2)

    reparto = ", ".join(f"{k}={v}" for k, v in enrutador.reparto.items())
    print(f"Fuentes: {reparto}")

    tickers = cfg.universo.tickers()
    indices = list(cfg.reglas.tecnico.indices_regimen.values())
    referencias = [r.ticker for r in cfg.implementacion.referencias.values()]
    divisas = sorted(
        {m.divisa for m in cfg.reglas.universo.mercados}
        | {r.divisa for r in cfg.implementacion.referencias.values()}
    )

    incompletos: list[str] = []

    def paso(tipo: str, mensaje: str, descarga, vacio):
        print(mensaje)
        try:
            return descarga()
        except Exception as exc:  # noqa: BLE001 - frontera con la red
            incompletos.append(tipo)
            print(f"  FALLO en {tipo}: {exc}", file=sys.stderr)
            return vacio

    precios = paso(
        "precios",
        f"Descargando precios de {len(tickers)} valores + indices y referencias...",
        lambda: enrutador.precios(tickers + indices + referencias, inicio, fin),
        pd.DataFrame(),
    )
    fundamentales = paso(
        "fundamentales", f"Descargando fundamentales de {len(tickers)} valores...",
        lambda: enrutador.fundamentales(tickers, inicio, fin), pd.DataFrame(),
    )
    fx = paso(
        "fx", "Descargando tipos de cambio...",
        lambda: enrutador.fx(divisas, inicio, fin), pd.DataFrame(),
    )
    sectores = paso(
        "sectores", "Leyendo sectores...", lambda: enrutador.sectores(tickers), {},
    )
    for aviso in enrutador.avisos:
        print(f"  aviso: {aviso}")

    # El origen refleja el reparto real, no una sola fuente: si los precios
    # vienen de una y los fundamentales de otra, el informe tiene que decirlo.
    return Instantanea(
        precios=precios, fundamentales=fundamentales, fx=fx, sectores=sectores,
        fecha_descarga=date.today(), origen=enrutador.origen, incompletos=incompletos,
    )


def _informar_incompletos(inst: Instantanea, destino: Path, conservados: bool) -> None:
    """Explica que falta y termina con codigo 1, para que la tarea programada
    se entere de que la descarga no fue completa."""
    if not inst.incompletos:
        return
    que = ", ".join(inst.incompletos)
    if conservados:
        detalle = (
            "se conservan los de la descarga anterior donde los habia; donde no, "
            "quedan vacios"
        )
    else:
        detalle = "quedan vacios en esta copia"
    print(f"\nDESCARGA INCOMPLETA: ha fallado {que}; {detalle} ({destino}).", file=sys.stderr)
    raise SystemExit(1)


def _cargar_instantanea(args, cfg) -> Instantanea:
    nombre = _nombre_cache(args, cfg)
    directorio = DIR_CACHE / nombre
    if not (directorio / "precios.parquet").is_file():
        print(
            f"No hay datos en cache para '{nombre}' ({directorio}). "
            f"Ejecuta primero: estrategia {_opcion_proveedor(args)}datos",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return Instantanea.cargar(directorio)


# --------------------------------------------------------------------------
# Comandos
# --------------------------------------------------------------------------


def cmd_datos(args, cfg) -> None:
    fin = date.today()
    inicio = fin - timedelta(days=int(args.anos * 365.25))
    inst = _descargar(cfg, args.proveedor, inicio, fin)
    destino = DIR_CACHE / inst.origen
    if "precios" in inst.incompletos:
        # Sin precios no hay nada que guardar: se deja la cache como estaba.
        print(
            f"\nNo se han podido descargar los precios; la cache de {destino} "
            f"no se ha tocado.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    inst.guardar(destino, conservar=set(inst.incompletos))
    print(
        f"Guardado en {destino}: {len(inst.precios)} filas de precios, "
        f"{len(inst.fundamentales)} de fundamentales, {len(inst.fx)} de divisas."
    )
    _informar_incompletos(inst, destino, conservados=True)


def cmd_foto(args, cfg) -> None:
    """Foto semanal de fundamentales y divisas.

    Idempotente por semana ISO: dos ejecuciones el mismo lunes no duplican nada.
    """
    hoy = date.today()
    ano, semana, _ = hoy.isocalendar()
    destino = DIR_FOTOS / f"{ano}-S{semana:02d}"
    if destino.is_dir() and not args.forzar:
        print(f"Ya existe la foto de la semana {ano}-S{semana:02d} en {destino}.")
        return

    inicio = hoy - timedelta(days=int(args.anos * 365.25))
    inst = _descargar(cfg, args.proveedor, inicio, hoy)

    # Se escribe aparte y solo se mueve al final. Una descarga que se corta a
    # medias no puede quedar archivada como si fuera la foto de la semana: el
    # valor de estas fotos esta en poder confiar en ellas dentro de tres anios.
    import shutil
    import tempfile

    # La carpeta se crea antes del temporal: en una copia recien clonada
    # `datos/` no existe, y `mkdtemp` dentro de ella fallaba.
    DIR_FOTOS.mkdir(parents=True, exist_ok=True)
    temporal = Path(tempfile.mkdtemp(prefix="foto-", dir=str(DIR_FOTOS.parent)))
    try:
        inst.guardar(temporal)
        if destino.is_dir():
            shutil.rmtree(destino)
        shutil.move(str(temporal), str(destino))
    finally:
        if temporal.is_dir():
            shutil.rmtree(temporal, ignore_errors=True)
    print(f"Foto de {ano}-S{semana:02d} guardada en {destino}.")
    # Una foto con huecos se guarda igual —lo que si llego vale— pero queda
    # marcada como incompleta en su manifiesto.
    _informar_incompletos(inst, destino, conservados=False)


def cmd_universo(args, cfg) -> None:
    inst = _cargar_instantanea(args, cfg).preparar(cfg)
    fecha = args.fecha or inst.rango_precios[1]
    vista = inst.vista(fecha)
    mapa = MapaSectores(cfg)
    resultado = universo_mod.evaluar(fecha, vista, cfg, mapa)

    elegibles = [e for e in resultado.values() if e.elegible]
    print(f"Universo a {fecha}: {len(elegibles)} elegibles de {len(resultado)}.\n")
    for mercado_id in cfg.reglas.mercados_por_id:
        delm = [e for e in resultado.values() if e.mercado == mercado_id]
        ok = [e for e in delm if e.elegible]
        print(f"  {mercado_id}: {len(ok)}/{len(delm)} elegibles")
        if args.detalle:
            for e in sorted(delm, key=lambda x: x.ticker):
                estado = "OK " if e.elegible else f"NO ({e.motivo})"
                print(f"      {e.ticker:16s} {estado:32s} vol {e.volumen_medio_base:,.0f}")
    if mapa.sin_mapear:
        print(f"\nSectores sin mapear: {mapa.sin_mapear}")


def cmd_senales(args, cfg) -> None:
    """Candidatas de la ultima revision semanal disponible."""
    inst = _cargar_instantanea(args, cfg).preparar(cfg)
    fin = args.fecha or inst.rango_precios[1]
    # Se corre un backtest corto que termina en la fecha pedida y se leen los
    # eventos de la ultima semana: asi las senales salen del mismo codigo que
    # las produce en el backtest, y no de un camino paralelo que puede divergir.
    inicio = fin - timedelta(days=int(3 * 365.25))
    r = backtest_mod.ejecutar(inst, cfg, max(inicio, inst.rango_precios[0]), fin)
    ev = r.eventos_df
    reparto = ev[ev["tipo"].isin(["orden", "rechazo"])] if not ev.empty else ev
    if reparto.empty:
        print("No hay ninguna revision con candidatas en el periodo.")
        return
    # La fecha de la ultima revision es la de su reparto, que anota a la vez
    # las ordenes y los rechazos. Antes los rechazos se filtraban por la fecha
    # del ultimo evento de cualquier tipo (una venta del martes, por ejemplo),
    # y `--detalle` casi nunca ensenaba nada.
    ultima = reparto["fecha"].max()
    ordenes = reparto[(reparto["tipo"] == "orden") & (reparto["fecha"] == ultima)]
    if ordenes.empty:
        print(f"La revision del {ultima} no genero ordenes.")
    else:
        print(f"Ordenes de la revision del {ultima}:\n")
        print(ordenes.to_string(index=False))

    rech = reparto[(reparto["tipo"] == "rechazo") & (reparto["fecha"] == ultima)]
    if not rech.empty and args.detalle:
        print("\nRechazos de esa revision:\n")
        print(rech.dropna(axis=1, how="all").to_string(index=False))


def cmd_diagnostico(args, cfg) -> None:
    """Que resuelve cada fuente y que no, ticker a ticker.

    Pensado para la primera ejecucion con datos reales: da la lista entera de
    cosas que arreglar en vez de reventar en el ticker numero 37.
    """
    fin = args.fecha or date.today()
    inicio = fin - timedelta(days=int(args.anos * 365.25))
    if args.proveedor:
        cfg = cfg.con_fuente_unica(args.proveedor)

    filas = diagnostico_mod.ejecutar(cfg, inicio, fin)
    auxiliares = diagnostico_mod.comprobar_auxiliares(cfg, inicio, fin)
    texto = diagnostico_mod.a_texto(
        filas, cfg, detalle=args.detalle, auxiliares=auxiliares
    )
    print(texto)

    DIR_RESULTADOS.mkdir(parents=True, exist_ok=True)
    ruta = DIR_RESULTADOS / f"diagnostico_{date.today().isoformat()}.md"
    ruta.write_text(texto, encoding="utf-8")
    print(f"\nGuardado en {ruta}")

    if any(not a.utilizable for a in auxiliares):
        # Sin un indice o una divisa, un mercado entero queda inservible.
        raise SystemExit(1)
    utilizables = sum(1 for f in filas if f.utilizable)
    if utilizables < len(filas):
        # Codigo de salida distinto de cero para que CI se entere, pero sin
        # tratarlo como un fallo: un universo con huecos sigue siendo operable.
        raise SystemExit(0 if utilizables else 1)


def cmd_backtest(args, cfg) -> None:
    inst = _cargar_instantanea(args, cfg)
    division = validacion_mod.dividir(inst, cfg)

    if division.toca_validacion(args.periodo):
        # "todo" incluye la validacion entera: tambien gasta una consulta.
        registro = validacion_mod.RegistroConsultas(RUTA_CONSULTAS)
        n = registro.anotar(f"{args.comando} --periodo {args.periodo}")
        print(
            f"AVISO: has abierto el periodo de validacion ({division.corte} a "
            f"{division.fin}). Van {n} consultas.\n"
            f"Cada una lo acerca a ser un periodo de diseno mas.\n"
        )
    if args.periodo == "validacion":
        inicio, fin = division.validacion
    elif args.periodo == "diseno":
        inicio, fin = division.diseno
    else:
        inicio, fin = division.inicio, division.fin

    print(f"Backtest de {inicio} a {fin} (periodo: {args.periodo})...")
    r = backtest_mod.ejecutar(inst, cfg, inicio, fin)

    consultas = validacion_mod.RegistroConsultas(RUTA_CONSULTAS).n
    inf = informe_mod.construir(r, cfg, inst, consultas_validacion=consultas)
    texto = informe_mod.a_markdown(inf)
    print("\n" + texto)
    _guardar_informe(inf, texto, args, _nombre_cache(args, cfg))


def cmd_validar(args, cfg) -> None:
    inst = _cargar_instantanea(args, cfg)
    division = validacion_mod.dividir(inst, cfg)
    inicio, fin = division.diseno
    print(f"Periodo de diseno: {inicio} a {fin}")
    print(f"Periodo de validacion (sin tocar): {division.corte} a {division.fin}\n")

    r = backtest_mod.ejecutar(inst, cfg, inicio, fin)
    base = metricas_mod.resumir(r.curva, r.operaciones_df, cfg)
    print(
        f"Base: anualizada {base.rentabilidad_anualizada:+.2%}, "
        f"Sharpe {base.sharpe:.2f}, {base.n_operaciones} operaciones."
    )
    print("\nAnalisis de sensibilidad (puede tardar varios minutos)...")
    sens = validacion_mod.sensibilidad(inst, cfg, inicio, fin, base)

    consultas = validacion_mod.RegistroConsultas(RUTA_CONSULTAS).n
    inf = informe_mod.construir(
        r, cfg, inst, sensibilidad=sens, consultas_validacion=consultas
    )
    texto = informe_mod.a_markdown(inf)
    print("\n" + texto)
    _guardar_informe(inf, texto, args, _nombre_cache(args, cfg))


def cmd_informe(args, cfg) -> None:
    cmd_backtest(args, cfg)


def _guardar_informe(inf, texto: str, args, nombre: str) -> None:
    DIR_RESULTADOS.mkdir(parents=True, exist_ok=True)
    marca = "sintetico_" if inf.sintetico else ""
    formato = getattr(args, "formato", "md")

    if formato in ("md", "ambos"):
        ruta = DIR_RESULTADOS / f"informe_{marca}{date.today().isoformat()}.md"
        ruta.write_text(texto, encoding="utf-8")
        print(f"\nInforme guardado en {ruta}")

    if formato in ("html", "ambos") and inf.sintetico:
        # El sitio se despliega entero: un informe sintetico en `sitio/` acabaria
        # publicado como si fuera el estado real de la cartera. Se deja en
        # resultados, que no se publica, para poder mirarlo igualmente.
        ruta = DIR_RESULTADOS / f"informe_{marca}{date.today().isoformat()}.html"
        ruta.write_text(informe_html_mod.a_html(inf), encoding="utf-8")
        print(
            f"\nInforme HTML guardado en {ruta}. No se copia a {DIR_SITIO} "
            f"porque esta hecho con datos sinteticos."
        )
    elif formato in ("html", "ambos"):
        # El sitio se despliega entero, asi que el informe de esta semana es el
        # index y ademas queda archivado por semana: poder ver que decia el
        # sistema una semana concreta es justo lo que hace que no valga
        # reescribir la historia.
        DIR_SITIO.mkdir(parents=True, exist_ok=True)
        (DIR_SITIO / "informes").mkdir(exist_ok=True)
        pagina = informe_html_mod.a_html(inf)
        ano, semana, _ = date.today().isocalendar()
        archivo = DIR_SITIO / "informes" / f"{ano}-S{semana:02d}.html"
        archivo.write_text(pagina, encoding="utf-8")
        (DIR_SITIO / "index.html").write_text(pagina, encoding="utf-8")
        print(f"\nSitio generado en {DIR_SITIO} (index.html y {archivo.name})")
    inf.curva.to_parquet(DIR_RESULTADOS / f"curva_{nombre}.parquet", index=False)
    if not inf.operaciones.empty:
        inf.operaciones.to_parquet(
            DIR_RESULTADOS / f"operaciones_{nombre}.parquet", index=False
        )
    if not inf.eventos.empty:
        inf.eventos.to_parquet(DIR_RESULTADOS / f"eventos_{nombre}.parquet", index=False)
    if inf.sensibilidad is not None and not inf.sensibilidad.empty:
        inf.sensibilidad.to_parquet(
            DIR_RESULTADOS / f"sensibilidad_{nombre}.parquet", index=False
        )


# --------------------------------------------------------------------------
# Entrada
# --------------------------------------------------------------------------


def _fecha(texto: str) -> date:
    return date.fromisoformat(texto)


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="estrategia",
        description="Estrategia mixta (fundamental + tecnica) multi-mercado.",
    )
    p.add_argument(
        "--config", type=Path, default=None,
        help="directorio de configuracion (por defecto config/)",
    )
    p.add_argument(
        "--proveedor", default=None,
        help="fuerza UNA sola fuente para todos los tipos de dato, ignorando el "
             "reparto de reglas.yaml. Sin esta opcion manda reglas.yaml. Comodo "
             "para trabajar sin red ('sintetico') o para probar una fuente "
             "concreta.",
    )
    sub = p.add_subparsers(dest="comando", required=True)

    d = sub.add_parser("datos", help="descarga y cachea datos")
    d.add_argument("--anos", type=float, default=8.0, help="anos de historico")
    d.set_defaults(func=cmd_datos)

    f = sub.add_parser("foto", help="foto semanal de fundamentales y divisas")
    f.add_argument("--anos", type=float, default=8.0)
    f.add_argument("--forzar", action="store_true", help="rehacer la foto de esta semana")
    f.set_defaults(func=cmd_foto)

    u = sub.add_parser("universo", help="quien entra en el universo y por que no")
    u.add_argument("--fecha", type=_fecha, default=None)
    u.add_argument("--detalle", action="store_true")
    u.set_defaults(func=cmd_universo)

    s = sub.add_parser("senales", help="candidatas de la ultima revision")
    s.add_argument("--fecha", type=_fecha, default=None)
    s.add_argument("--detalle", action="store_true")
    s.set_defaults(func=cmd_senales)

    b = sub.add_parser("backtest", help="corre el backtest")
    b.add_argument(
        "--periodo", choices=["diseno", "validacion", "todo"], default="diseno",
        help="'validacion' y 'todo' abren el periodo reservado y anotan la consulta",
    )
    b.add_argument("--formato", choices=["md", "html", "ambos"], default="md")
    b.set_defaults(func=cmd_backtest)

    g = sub.add_parser(
        "diagnostico", help="que resuelve cada fuente y que no, ticker a ticker"
    )
    g.add_argument("--fecha", type=_fecha, default=None)
    g.add_argument("--anos", type=float, default=8.0)
    g.add_argument("--detalle", action="store_true")
    g.set_defaults(func=cmd_diagnostico)

    v = sub.add_parser("validar", help="backtest de diseno mas analisis de sensibilidad")
    v.add_argument("--formato", choices=["md", "html", "ambos"], default="md")
    v.set_defaults(func=cmd_validar)

    i = sub.add_parser("informe", help="alias de backtest, guarda el informe")
    # Por defecto solo el diseno: el informe se genera y se publica cada semana,
    # y si mostrara la validacion la gastaria sin que nadie lo pidiera.
    i.add_argument(
        "--periodo", choices=["diseno", "validacion", "todo"], default="diseno",
        help="'validacion' y 'todo' abren el periodo reservado y anotan la consulta",
    )
    i.add_argument("--formato", choices=["md", "html", "ambos"], default="ambos")
    i.set_defaults(func=cmd_informe)

    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        cfg = config_mod.cargar(args.config)
        args.func(args, cfg)
    except ErrorEstrategia as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
