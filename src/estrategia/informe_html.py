"""Informe en HTML: un solo fichero, sin JavaScript y sin nada externo.

Los graficos son SVG generado aqui mismo. La alternativa era una libreria de
graficos, y no compensa: son tres graficos, y traerse tres megas de JavaScript
para pintar una curva y dos series de barras hace la pagina mas fragil y mas
lenta a cambio de nada. Asi el fichero se abre igual desde un servidor, desde el
disco o desde un correo, y funciona con JavaScript desactivado.

Sin JavaScript tampoco hay tooltips propios, asi que la capa de detalle son los
`<title>` de cada marca —que el navegador muestra de forma nativa— y las tablas,
que llevan todos los valores. Eso cubre ademas la regla de relieve: el aqua de la
tercera serie queda por debajo de 3:1 de contraste sobre el fondo claro, asi que
lleva etiqueta directa visible y sus datos estan tambien en tabla.

Los colores salen de una paleta validada: categorica de tres ranuras para la
curva (la estrategia y sus dos referencias) y divergente azul/rojo para las
barras, donde lo que se codifica es el signo del resultado. Se paso el validador
en claro y en oscuro; las separaciones para daltonismo quedan holgadas.
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .informe import Informe

# --------------------------------------------------------------------------
# Paleta
# --------------------------------------------------------------------------

#: Ranuras categoricas 1-3: la estrategia y sus dos referencias. Validadas en
#: los dos modos (peor par adyacente, deuteranopia: dE 9,2 claro / 9,4 oscuro).
SERIES_CLARO = ("#2a78d6", "#eb6834", "#1baf7a")
SERIES_OSCURO = ("#3987e5", "#d95926", "#199e70")


@dataclass(frozen=True, slots=True)
class Lienzo:
    """Medidas de un grafico. Todo en coordenadas de `viewBox`."""

    ancho: int = 720
    alto: int = 300
    izq: int = 56
    der: int = 96
    arriba: int = 16
    abajo: int = 34

    @property
    def x0(self) -> int:
        return self.izq

    @property
    def x1(self) -> int:
        return self.ancho - self.der

    @property
    def y0(self) -> int:
        return self.arriba

    @property
    def y1(self) -> int:
        return self.alto - self.abajo


def _e(texto) -> str:
    return html.escape(str(texto), quote=True)


def _eur(valor: float) -> str:
    return f"{valor:,.0f} EUR".replace(",", ".")


def _pct(valor: float, signo: bool = True) -> str:
    return f"{valor:+.1%}" if signo else f"{valor:.1%}"


def _escala_bonita(minimo: float, maximo: float, objetivo: int = 5) -> list[float]:
    """Marcas de eje en numeros redondos.

    Los ticks cargan los valores que no llevan etiqueta directa, asi que tienen
    que ser legibles: 10.000 y 12.000, no 10.347,82.
    """
    if maximo <= minimo:
        maximo = minimo + 1.0
    bruto = (maximo - minimo) / max(objetivo, 1)
    if bruto <= 0:
        return [minimo, maximo]

    magnitud = 10.0 ** math.floor(math.log10(bruto))
    paso = magnitud * 10
    for multiplo in (1, 2, 2.5, 5, 10):
        if bruto <= magnitud * multiplo:
            paso = magnitud * multiplo
            break

    marcas: list[float] = []
    valor = math.floor(minimo / paso) * paso
    while valor <= maximo + paso * 0.5:
        if valor >= minimo - paso * 0.5:
            marcas.append(round(valor, 10))
        valor += paso
    return marcas or [minimo, maximo]


# --------------------------------------------------------------------------
# Graficos
# --------------------------------------------------------------------------


def curva_svg(informe: Informe, lienzo: Lienzo | None = None) -> str:
    """Curva de capital contra las referencias.

    Tres series categoricas, linea de 2px, marcador de final con anillo del color
    del fondo para que se lea donde se cruzan, y etiqueta directa al final de cada
    una. La leyenda va siempre: la identidad nunca depende solo del color.
    """
    lz = lienzo or Lienzo()
    curva = informe.curva
    if curva.empty:
        return "<p class='vacio'>No hay curva que pintar.</p>"

    series: list[tuple[str, pd.Series]] = [
        ("Estrategia", pd.Series(
            curva["valor"].to_numpy(dtype=float),
            index=pd.Index(list(curva["fecha"])),
        ))
    ]
    nombres = {
        "msci_world_eur": "MSCI World",
        "msci_emerging_markets_eur": "MSCI Emerging",
    }
    for clave, serie in informe.referencias.items():
        series.append((nombres.get(clave, clave), serie))

    # Se reduce a un punto cada pocos dias: una linea no gana nada con 1.500
    # puntos y el fichero pesa cuatro veces mas.
    maximo_puntos = 360
    paso = max(1, len(series[0][1]) // maximo_puntos)

    reducidas = [(nombre, s.iloc[::paso]) for nombre, s in series]
    fechas = list(reducidas[0][1].index)
    if len(fechas) < 2:
        return "<p class='vacio'>No hay curva que pintar.</p>"

    todos = [float(v) for _, s in reducidas for v in s.to_numpy() if pd.notna(v)]
    marcas = _escala_bonita(min(todos), max(todos))
    v_min, v_max = min(marcas[0], min(todos)), max(marcas[-1], max(todos))

    def px(i: int) -> float:
        return lz.x0 + (lz.x1 - lz.x0) * i / (len(fechas) - 1)

    def py(v: float) -> float:
        return lz.y1 - (lz.y1 - lz.y0) * (v - v_min) / (v_max - v_min or 1.0)

    partes: list[str] = [
        f'<svg viewBox="0 0 {lz.ancho} {lz.alto}" role="img" '
        f'aria-label="Curva de capital de la estrategia frente a sus referencias" '
        f'class="gr">'
    ]

    # Rejilla: hairline de 1px, solida y recesiva.
    for m in marcas:
        y = py(m)
        partes.append(
            f'<line x1="{lz.x0}" y1="{y:.1f}" x2="{lz.x1}" y2="{y:.1f}" class="rejilla"/>'
            f'<text x="{lz.x0 - 8}" y="{y + 4:.1f}" class="tick tick-y">'
            f'{_e(f"{m:,.0f}".replace(",", "."))}</text>'
        )

    # Eje de tiempo: un anio por marca, sin abarrotar.
    ultimo_anio = None
    for i, f in enumerate(fechas):
        if f.year != ultimo_anio:
            ultimo_anio = f.year
            if i > 0:
                partes.append(
                    f'<text x="{px(i):.1f}" y="{lz.y1 + 20}" class="tick tick-x">'
                    f"{f.year}</text>"
                )

    partes.append(
        f'<line x1="{lz.x0}" y1="{lz.y1}" x2="{lz.x1}" y2="{lz.y1}" class="eje"/>'
    )

    for idx, (nombre, serie) in enumerate(reducidas):
        valores = [float(v) if pd.notna(v) else None for v in serie.to_numpy()]
        puntos = [
            f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(valores) if v is not None
        ]
        if not puntos:
            continue
        partes.append(
            f'<polyline points="{" ".join(puntos)}" class="linea s{idx + 1}">'
            f"<title>{_e(nombre)}</title></polyline>"
        )
        # Marcador final: r>=4 con anillo de 2px del color del fondo.
        ultimo = next(v for v in reversed(valores) if v is not None)
        x_fin, y_fin = px(len(valores) - 1), py(ultimo)
        partes.append(
            f'<circle cx="{x_fin:.1f}" cy="{y_fin:.1f}" r="4.5" class="punta s{idx + 1}">'
            f"<title>{_e(nombre)}: {_e(_eur(ultimo))}</title></circle>"
        )
        # Etiqueta directa: ademas de la leyenda, y obligatoria porque una de
        # las series no llega a 3:1 de contraste sobre el fondo claro.
        partes.append(
            f'<text x="{x_fin + 10:.1f}" y="{y_fin + 4:.1f}" class="etiqueta">'
            f"{_e(nombre)}</text>"
        )

    partes.append("</svg>")

    leyenda = "".join(
        f'<span class="clave"><i class="pastilla s{i + 1}"></i>{_e(n)}</span>'
        for i, (n, _) in enumerate(reducidas)
    )
    return f'<div class="leyenda">{leyenda}</div>{"".join(partes)}'


def barras_svg(
    etiquetas: list[str],
    valores: list[float],
    formato,
    titulo_accesible: str,
    alto_fila: int = 30,
) -> str:
    """Barras horizontales con el signo codificado en color.

    Divergente azul/rojo: lo que se esta codificando es la polaridad —ganar o
    perder—, no la identidad, asi que no toca paleta categorica. El cero es el
    origen comun de las dos direcciones.
    """
    if not valores:
        return "<p class='vacio'>Sin datos.</p>"

    ancho, izq, der = 720, 116, 96
    alto = alto_fila * len(valores) + 24
    x0, x1 = izq, ancho - der
    extremo = max(abs(min(valores)), abs(max(valores))) or 1.0
    cero = x0 + (x1 - x0) / 2

    def px(v: float) -> float:
        return cero + (x1 - x0) / 2 * (v / extremo)

    partes = [
        f'<svg viewBox="0 0 {ancho} {alto}" role="img" '
        f'aria-label="{_e(titulo_accesible)}" class="gr">'
    ]
    for i, (etq, val) in enumerate(zip(etiquetas, valores)):
        # Barra de 18px: por debajo del tope de 24, y el resto de la banda es aire.
        y = 12 + i * alto_fila
        grosor = 18
        xa, xb = (cero, px(val)) if val >= 0 else (px(val), cero)
        clase = "pos" if val >= 0 else "neg"
        # Extremo del dato redondeado, cuadrado en la linea de cero.
        radio = 4
        if val >= 0:
            d = (
                f"M{xa:.1f},{y} H{max(xb - radio, xa):.1f} "
                f"a{radio},{radio} 0 0 1 {radio},{radio} "
                f"v{grosor - 2 * radio} a{radio},{radio} 0 0 1 -{radio},{radio} "
                f"H{xa:.1f} Z"
            )
        else:
            d = (
                f"M{xb:.1f},{y} H{min(xa + radio, xb):.1f} "
                f"a{radio},{radio} 0 0 0 -{radio},{radio} "
                f"v{grosor - 2 * radio} a{radio},{radio} 0 0 0 {radio},{radio} "
                f"H{xb:.1f} Z"
            )
        partes.append(
            f'<path d="{d}" class="barra {clase}">'
            f"<title>{_e(etq)}: {_e(formato(val))}</title></path>"
        )
        partes.append(
            f'<text x="{izq - 12}" y="{y + grosor / 2 + 4:.1f}" class="tick tick-y">'
            f"{_e(etq)}</text>"
        )
        # Valor en la punta, fuera de la barra: dentro no siempre cabe.
        anclaje = "start" if val >= 0 else "end"
        x_txt = (xb + 8) if val >= 0 else (xa - 8)
        partes.append(
            f'<text x="{x_txt:.1f}" y="{y + grosor / 2 + 4:.1f}" '
            f'class="valor" text-anchor="{anclaje}">{_e(formato(val))}</text>'
        )

    partes.append(
        f'<line x1="{cero:.1f}" y1="6" x2="{cero:.1f}" y2="{alto - 6}" class="eje"/>'
    )
    partes.append("</svg>")
    return "".join(partes)


# --------------------------------------------------------------------------
# Pagina
# --------------------------------------------------------------------------


ESTILO = """
:root {
  color-scheme: light;
  --plano: #f9f9f7; --sup: #fcfcfb;
  --tinta: #0b0b0b; --tinta2: #52514e; --tinta3: #898781;
  --rejilla: #e1e0d9; --eje: #c3c2b7; --borde: rgba(11,11,11,0.10);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a;
  --pos: #2a78d6; --neg: #d03b3b;
  --aviso: #fab219; --grave: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --plano: #0d0d0d; --sup: #1a1a19;
    --tinta: #ffffff; --tinta2: #c3c2b7; --tinta3: #898781;
    --rejilla: #2c2c2a; --eje: #383835; --borde: rgba(255,255,255,0.10);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70;
    --pos: #3987e5; --neg: #e66767;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--plano); color: var(--tinta);
  font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.envoltura { max-width: 940px; margin: 0 auto; padding: 32px 20px 72px; }
h1 { font-size: 1.7rem; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 1.15rem; margin: 40px 0 12px; letter-spacing: -0.01em; }
h3 { font-size: .95rem; margin: 24px 0 8px; color: var(--tinta2); font-weight: 600; }
p { margin: 0 0 12px; }
.sub { color: var(--tinta2); margin-bottom: 24px; font-size: .92rem; }

.tarjeta {
  background: var(--sup); border: 1px solid var(--borde);
  border-radius: 12px; padding: 20px; margin: 16px 0;
}

.descargo {
  border-left: 3px solid var(--aviso); background: var(--sup);
  border-radius: 0 8px 8px 0; padding: 14px 18px; margin: 0 0 24px;
  font-size: .9rem; color: var(--tinta2);
}
.descargo strong { color: var(--tinta); }
.sintetico {
  border-left: 3px solid var(--grave); background: var(--sup);
  border-radius: 0 8px 8px 0; padding: 16px 18px; margin: 0 0 20px;
}
.sintetico strong { color: var(--grave); }

.heroe { font-size: 3rem; font-weight: 650; line-height: 1.05; letter-spacing: -0.02em; }
.heroe.neg { color: var(--neg); }
.rejilla-tarjetas {
  display: grid; gap: 12px; margin: 16px 0;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
}
.dato {
  background: var(--sup); border: 1px solid var(--borde);
  border-radius: 10px; padding: 14px 16px;
}
.dato .etq { font-size: .78rem; color: var(--tinta3); display: block; margin-bottom: 4px; }
.dato .val { font-size: 1.45rem; font-weight: 600; letter-spacing: -0.01em; }

.gr { width: 100%; height: auto; display: block; }
.rejilla { stroke: var(--rejilla); stroke-width: 1; }
.eje { stroke: var(--eje); stroke-width: 1; }
.tick { fill: var(--tinta3); font-size: 11px; font-variant-numeric: tabular-nums; }
.tick-y { text-anchor: end; }
.tick-x { text-anchor: middle; }
.valor { fill: var(--tinta2); font-size: 11.5px; font-variant-numeric: tabular-nums; }
.etiqueta { fill: var(--tinta2); font-size: 12px; }
.linea { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.punta { stroke: var(--sup); stroke-width: 2; }
.s1 { stroke: var(--s1); } circle.s1 { fill: var(--s1); }
.s2 { stroke: var(--s2); } circle.s2 { fill: var(--s2); }
.s3 { stroke: var(--s3); } circle.s3 { fill: var(--s3); }
.barra.pos { fill: var(--pos); } .barra.neg { fill: var(--neg); }

.leyenda { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 8px; font-size: .85rem; color: var(--tinta2); }
.clave { display: inline-flex; align-items: center; gap: 7px; }
.pastilla { width: 14px; height: 3px; border-radius: 2px; display: inline-block; }
.pastilla.s1 { background: var(--s1); }
.pastilla.s2 { background: var(--s2); }
.pastilla.s3 { background: var(--s3); }

.desliza { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .87rem; }
th, td { text-align: right; padding: 7px 10px; border-bottom: 1px solid var(--borde); font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { text-align: left; font-variant-numeric: normal; }
th { color: var(--tinta3); font-weight: 600; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }
td.pos { color: var(--pos); } td.neg { color: var(--neg); }

.avisos { list-style: none; padding: 0; margin: 0; }
.avisos li {
  background: var(--sup); border: 1px solid var(--borde);
  border-left-width: 3px; border-radius: 0 8px 8px 0;
  padding: 12px 16px; margin-bottom: 10px; font-size: .9rem; color: var(--tinta2);
}
.avisos li.permanente { border-left-color: var(--aviso); }
.avisos li.importante { border-left-color: var(--grave); }
.avisos li.normal { border-left-color: var(--eje); }
.avisos .marca {
  display: inline-block; font-size: .7rem; font-weight: 700; letter-spacing: .05em;
  text-transform: uppercase; color: var(--tinta3); margin-right: 8px;
}
.pie { margin-top: 48px; padding-top: 20px; border-top: 1px solid var(--borde);
       color: var(--tinta3); font-size: .82rem; }
.vacio { color: var(--tinta3); font-style: italic; }
@media (max-width: 560px) { .heroe { font-size: 2.3rem; } .envoltura { padding: 20px 16px 56px; } }
"""


# Formateadores por tipo de columna. Se pasan explicitamente y no se adivinan
# por el nombre: adivinando, un ano salia como "2.019,00" y un recuento de
# operaciones como "0.000".
def _f_entero(v) -> str:
    return f"{int(v)}"


def _f_ano(v) -> str:
    return f"{int(v)}"


def _f_pct(v) -> str:
    return f"{float(v):.1%}"


def _f_pct_signo(v) -> str:
    return f"{float(v):+.1%}"


def _f_eur(v) -> str:
    return f"{float(v):+,.0f}".replace(",", ".") + " EUR"


def _f_texto(v) -> str:
    return str(v)


def _tabla(
    df: pd.DataFrame,
    columnas: dict[str, tuple[str, object]],
    colorear: set[str] = frozenset(),
) -> str:
    """Tabla HTML. Cada columna trae su titulo y su formateador."""
    if df.empty:
        return "<p class='vacio'>Sin datos.</p>"

    cabecera = "".join(f"<th>{_e(titulo)}</th>" for titulo, _ in columnas.values())
    filas = []
    for _, fila in df.iterrows():
        celdas = []
        for col, (_, formato) in columnas.items():
            valor = fila.get(col)
            clase = ""
            if col in colorear and isinstance(valor, (int, float)):
                clase = ' class="pos"' if valor >= 0 else ' class="neg"'
            texto = "" if valor is None else formato(valor)
            celdas.append(f"<td{clase}>{_e(texto)}</td>")
        filas.append(f"<tr>{''.join(celdas)}</tr>")
    return (
        f'<div class="desliza"><table><thead><tr>{cabecera}</tr></thead>'
        f"<tbody>{''.join(filas)}</tbody></table></div>"
    )


def a_html(informe: Informe, titulo: str = "Estrategia mixta") -> str:
    """El informe entero como una sola pagina autocontenida."""
    r = informe.resumen
    meta = informe.meta

    partes: list[str] = []

    if informe.sintetico:
        partes.append(
            '<div class="sintetico"><strong>DATOS SINTETICOS: no son resultados '
            "reales.</strong><br>Esta pagina se ha generado con el proveedor de "
            "datos inventados, que sirve para comprobar que el motor hace lo que "
            "dice. No describe ningun mercado.</div>"
        )

    # El descargo va arriba, no enterrado al final: la pagina es publica.
    partes.append(
        '<div class="descargo"><strong>Esto no es asesoramiento financiero.</strong> '
        "Es un sistema propio, publicado para dejar constancia de lo que decidio y "
        "cuando. Los parametros son un punto de partida razonable, no valores "
        "optimizados, y un backtest comprueba que el codigo hace lo que dice, no "
        "predice nada. Los avisos del final no son letra pequena: explican por que "
        "estas cifras dicen menos de lo que parece.</div>"
    )

    partes.append(f"<h1>{_e(titulo)}</h1>")
    partes.append(
        f'<p class="sub">Periodo {_e(meta["inicio"])} a {_e(meta["fin"])} '
        f"({r.anos:.1f} anos) · Fuentes: {_e(meta['origen'])} · "
        f"Descarga {_e(meta['fecha_descarga'])} · "
        f"Filtro fundamental {'activo' if meta.get('fundamental_activo') else 'DESACTIVADO'}"
        "</p>"
    )

    # Una sola cifra heroe.
    clase_heroe = "heroe" if r.rentabilidad_anualizada >= 0 else "heroe neg"
    partes.append(
        f'<div class="tarjeta"><span class="etq" style="color:var(--tinta3);'
        f'font-size:.8rem">Rentabilidad anualizada</span>'
        f'<div class="{clase_heroe}">{_pct(r.rentabilidad_anualizada)}</div></div>'
    )

    tarjetas = [
        ("Rentabilidad total", _pct(r.rentabilidad_total)),
        ("Drawdown maximo", _pct(r.drawdown_maximo, signo=False)),
        (f"Sharpe ({r.periodicidad_sharpe})", f"{r.sharpe:.2f}"),
        ("Ganadoras", _pct(r.pct_ganadoras, signo=False)),
        ("Operaciones", f"{r.n_operaciones}"),
        ("Exposicion media", _pct(r.exposicion_media, signo=False)),
    ]
    partes.append(
        '<div class="rejilla-tarjetas">'
        + "".join(
            f'<div class="dato"><span class="etq">{_e(e)}</span>'
            f'<span class="val">{_e(v)}</span></div>'
            for e, v in tarjetas
        )
        + "</div>"
    )

    partes.append("<h2>Curva de capital</h2>")
    partes.append(
        f'<p class="sub">Las referencias estan invertidas al 100% todo el tiempo '
        f"y la estrategia no: su exposicion media fue del "
        f"{r.exposicion_media:.0%}. Comparar las curvas sin tener eso delante no "
        f"seria una comparacion justa.</p>"
    )
    partes.append(f'<div class="tarjeta">{curva_svg(informe)}</div>')

    if not informe.por_ano.empty:
        partes.append("<h2>Por ano</h2>")
        datos = informe.por_ano
        partes.append(
            '<div class="tarjeta">'
            + barras_svg(
                [str(int(a)) for a in datos["ano"]],
                [float(v) for v in datos["rentabilidad"]],
                lambda v: f"{v:+.1%}",
                "Rentabilidad de cada ano",
            )
            + "</div>"
        )
        partes.append(
            _tabla(
                datos,
                {
                    "ano": ("Ano", _f_ano),
                    "rentabilidad": ("Rentabilidad", _f_pct_signo),
                    "drawdown_maximo": ("Drawdown", _f_pct),
                    "n_operaciones": ("Operaciones", _f_entero),
                    "pct_ganadoras": ("Ganadoras", _f_pct),
                },
                colorear={"rentabilidad"},
            )
        )

    if not informe.por_mercado.empty:
        partes.append("<h2>Por mercado</h2>")
        partes.append(
            '<p class="sub">Una estrategia global puede parecer solida en el '
            "agregado mientras una region concreta arrastra el resultado.</p>"
        )
        datos = informe.por_mercado
        partes.append(
            '<div class="tarjeta">'
            + barras_svg(
                [str(m) for m in datos["mercado"]],
                [float(v) for v in datos["resultado_base"]],
                lambda v: f"{v:+,.0f} EUR".replace(",", "."),
                "Resultado acumulado de cada mercado",
            )
            + "</div>"
        )
        partes.append(
            _tabla(
                datos,
                {
                    "mercado": ("Mercado", _f_texto),
                    "bloque": ("Bloque", _f_texto),
                    "n_operaciones": ("Operaciones", _f_entero),
                    "resultado_base": ("Resultado", _f_eur),
                    "pct_ganadoras": ("Ganadoras", _f_pct),
                    "coste_pct_medio": ("Coste medio", _f_pct),
                },
                colorear={"resultado_base"},
            )
        )

    if not informe.por_bloque.empty:
        partes.append("<h3>Desarrollados frente a emergentes</h3>")
        partes.append(
            _tabla(
                informe.por_bloque,
                {
                    "bloque": ("Bloque", _f_texto),
                    "n_operaciones": ("Operaciones", _f_entero),
                    "resultado_base": ("Resultado", _f_eur),
                    "pct_ganadoras": ("Ganadoras", _f_pct),
                    "costes_base": ("Costes", _f_eur),
                },
                colorear={"resultado_base"},
            )
        )

    u = informe.uso_riesgo
    if u.n:
        partes.append("<h2>Riesgo nominal frente a riesgo real</h2>")
        partes.append(
            '<div class="rejilla-tarjetas">'
            + "".join(
                f'<div class="dato"><span class="etq">{_e(e)}</span>'
                f'<span class="val">{_e(v)}</span></div>'
                for e, v in (
                    ("Riesgo teorico", _pct(u.riesgo_teorico_medio, signo=False)),
                    ("Riesgo efectivo", _pct(u.riesgo_efectivo_medio, signo=False)),
                    ("Topadas por peso", _pct(u.pct_limitadas_por_peso, signo=False)),
                )
            )
            + "</div>"
        )
        if u.pct_limitadas_por_peso > 0.5:
            partes.append(
                "<p>En la mayoria de las ordenes manda <code>cartera.peso_maximo</code>, "
                "no <code>riesgo.por_operacion</code>. Si la sensibilidad de ese "
                "segundo parametro sale plana, no es que la estrategia sea robusta: "
                "es que el parametro no estaba actuando.</p>"
            )

    if not informe.rechazos_top.empty:
        partes.append("<h2>Candidatas del top 3 que se quedaron fuera</h2>")
        partes.append(
            '<p class="sub">Contesta a por que no se compro la mejor de la semana, '
            "y deja ver si un limite de cartera esta costando dinero de forma "
            "sistematica.</p>"
        )
        partes.append(
            _tabla(
                informe.rechazos_top,
                {
                    "motivo": ("Motivo", _f_texto),
                    "mercado": ("Mercado", _f_texto),
                    "veces": ("Veces", _f_entero),
                },
            )
        )

    partes.append("<h2>Avisos</h2>")
    elementos = []
    for aviso in informe.avisos:
        if aviso.permanente:
            clase, marca = "permanente", "Permanente"
        elif aviso.gravedad == "importante":
            clase, marca = "importante", "Importante"
        else:
            clase, marca = "normal", "Aviso"
        elementos.append(
            f'<li class="{clase}"><span class="marca">{marca}</span>{_e(aviso.texto)}</li>'
        )
    partes.append(f'<ul class="avisos">{"".join(elementos)}</ul>')

    partes.append(
        f'<div class="pie">Generado el {date.today().isoformat()} · '
        f"Capital inicial {_e(_eur(float(meta['capital_inicial'])))} · "
        f"Divisa base {_e(meta['divisa_base'])}<br>"
        "La especificacion de la estrategia y el codigo que produce esta pagina "
        "estan en el repositorio del proyecto.</div>"
    )

    return (
        "<!doctype html>\n"
        '<html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(titulo)}</title>"
        f"<style>{ESTILO}</style></head>"
        f'<body><div class="envoltura">{"".join(partes)}</div></body></html>'
    )
