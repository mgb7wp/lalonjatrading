import type { ReactNode } from "react";

import type { Bloque as TipoBloque, Frescura } from "@/lib/api";

/** Medidor de un score 0-100 (v2): diez celdas de UN solo tono que se
 * oscurecen al subir.
 *
 * Nada de semaforo: pintar de rojo un 20 y de verde un 80 convierte un
 * percentil —"esta por debajo de sus comparables"— en un juicio de valor que el
 * numero no hace. Ese juicio lo emite el motor de senales, llega aparte y va
 * etiquetado. */
export function Celdas({ valor, alto = 10 }: { valor: number | null; alto?: number }) {
  return (
    <span
      className="meter"
      role="img"
      aria-label={valor === null ? "Score no disponible" : `Score ${valor.toFixed(0)} sobre 100, percentil en su cohorte`}
      style={{ ["--h" as string]: `${alto}px` }}
    >
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} style={valor !== null && valor > i * 10 ? { background: `var(--tono-${i})` } : undefined} />
      ))}
    </span>
  );
}

export function Medidor({ valor }: { valor: number | null }) {
  if (valor === null || Number.isNaN(valor)) {
    return <span className="apunte">no disponible</span>;
  }
  const acotado = Math.max(0, Math.min(100, valor));
  return (
    <span className="score-cell">
      <span className="s">{acotado.toFixed(0)}</span>
      <Celdas valor={acotado} />
    </span>
  );
}

/** Score compacto para tablas: la cifra y un medidor corto. */
export function PildoraScore({ valor }: { valor: number | null }) {
  if (valor === null || Number.isNaN(valor)) return <span className="apunte" title="sin score">n/d</span>;
  return (
    <span className="score-pill">
      <span className="mono">{valor.toFixed(0)}</span>
      <Celdas valor={valor} alto={8} />
    </span>
  );
}

/** Senales: glifo + texto + color, siempre los tres.
 *
 * Una recomendacion de inversion tiene que poder leerse sin interpretar un
 * color: ni el daltonismo ni una pantalla mala pueden cambiar lo que dice. */
export const ESTADO_SENAL: Record<string, { texto: string; glifo: string; color: string; fondo: string; solido: boolean }> = {
  strong_buy: { texto: "Compra fuerte", glifo: "▲▲", color: "var(--sube)", fondo: "var(--sube-tinte)", solido: true },
  buy: { texto: "Compra", glifo: "▲", color: "var(--sube)", fondo: "transparent", solido: false },
  hold: { texto: "Mantener", glifo: "=", color: "var(--tinta-2)", fondo: "transparent", solido: false },
  sell: { texto: "Venta", glifo: "▼", color: "var(--baja)", fondo: "transparent", solido: false },
  strong_sell: { texto: "Venta fuerte", glifo: "▼▼", color: "var(--baja)", fondo: "var(--baja-tinte)", solido: true },
};
export const ORDEN_SENALES = ["strong_buy", "buy", "hold", "sell", "strong_sell"];

export function InsigniaSenal({ senal }: { senal: string | null }) {
  if (!senal)
    return (
      <span className="sig-chip" style={{ borderColor: "var(--color-neutral-500)", borderStyle: "dashed", color: "var(--tinta-3)" }}>
        <span className="g" aria-hidden="true">○</span>Sin señal
      </span>
    );
  const e = ESTADO_SENAL[senal] ?? { texto: senal, glifo: "·", color: "var(--tinta-3)", fondo: "transparent", solido: false };
  return (
    <span className="sig-chip" style={{ color: e.color, borderColor: e.color, background: e.fondo }}>
      <span className="g" aria-hidden="true">
        {e.glifo}
      </span>
      {e.texto}
    </span>
  );
}

export const GLIFO_REGIMEN: Record<string, string> = { alcista: "↗", lateral: "→", bajista: "↘", desconocido: "?" };

/** Regimen del mercado: glifo y texto, sin color. Es contexto, no un juicio. */
export function InsigniaRegimen({ regimen }: { regimen: string | null }) {
  const r = regimen && GLIFO_REGIMEN[regimen] ? regimen : "desconocido";
  return (
    <span className="tag tag-neutral" style={{ gap: 5 }}>
      <span className="mono" aria-hidden="true">
        {GLIFO_REGIMEN[r]}
      </span>
      {r.charAt(0).toUpperCase() + r.slice(1)}
    </span>
  );
}

/** Variacion con glifo delante: el color es refuerzo, no el portador del dato.
 *
 * `null` NO se pinta como cero ni como un guion mudo: se escribe «n/d» y el
 * motivo va en el titulo. Un cero afirma "no se movio", que es una afirmacion
 * sobre datos que no existen. */
export function Variacion({
  valor,
  motivo,
  sufijo = "%",
  decimales = 2,
}: {
  valor: number | null;
  motivo?: string;
  sufijo?: string;
  decimales?: number;
}) {
  if (valor === null || Number.isNaN(valor)) {
    return (
      <span className="apunte" title={motivo ?? "no se puede calcular"}>
        ○ n/d
      </span>
    );
  }
  const glifo = valor > 0 ? "▲" : valor < 0 ? "▼" : "=";
  const signo = valor > 0 ? "+" : valor < 0 ? "−" : "";
  return (
    <span className={`delta ${valor > 0 ? "sube" : valor < 0 ? "baja" : ""}`}>
      <span className="g" aria-hidden="true">
        {glifo}
      </span>{" "}
      {signo}
      {Math.abs(valor).toLocaleString("es-ES", {
        minimumFractionDigits: decimales,
        maximumFractionDigits: decimales,
      })}
      {sufijo}
    </span>
  );
}

export function EtiquetaFrescura({ frescura }: { frescura: Frescura | null }) {
  if (!frescura) return null;
  const texto =
    frescura.dias === 0
      ? `del ${frescura.as_of}`
      : `del ${frescura.as_of} · hace ${frescura.dias} ${frescura.dias === 1 ? "día" : "días"}`;
  return <span className="frescura"> {texto}</span>;
}

/** Envoltorio de un bloque de §27.
 *
 * Cuando falta, se dice POR QUE y no se pinta un hueco. Un bloque vacio sin
 * explicacion obliga a adivinar si es que no hay datos o es que algo se ha roto,
 * y esas dos cosas se atienden de forma muy distinta. */
export function Bloque<T>({
  titulo,
  bloque,
  children,
}: {
  titulo: string;
  bloque: TipoBloque<T>;
  children: (datos: T) => ReactNode;
}) {
  return (
    <section>
      <h2>
        {titulo}
        <EtiquetaFrescura frescura={bloque.frescura} />
      </h2>
      {bloque.disponible && bloque.datos ? (
        children(bloque.datos)
      ) : (
        <p className="bloque-falta">
          <strong>NO DISPONIBLE</strong>
          {mayuscula(bloque.motivo) ?? "Sin motivo indicado."}
        </p>
      )}
    </section>
  );
}

/** Lo que el diseno dibuja pero el backend no tiene todavia.
 *
 * Se mantiene el hueco en su sitio, con el motivo escrito, en lugar de
 * rellenarlo con datos de ejemplo o de borrar el bloque. Rellenarlo seria
 * mentir; borrarlo dejaria al usuario preguntandose si la funcion existe. */
export function Pendiente({ titulo, motivo }: { titulo: string; motivo: string }) {
  return (
    <section>
      <h2>{titulo}</h2>
      <p className="bloque-falta">
        <strong>TODAVÍA NO DISPONIBLE</strong>
        {motivo}
      </p>
    </section>
  );
}

const NOMBRES: Record<string, string> = {
  overall: "Global",
  fundamental: "Fundamental",
  technical: "Técnico",
  sentiment: "Sentimiento",
  risk: "Riesgo",
  growth: "Crecimiento",
  profitability: "Rentabilidad",
  financial_health: "Salud financiera",
  quality: "Calidad",
  valuation: "Valoración",
  momentum: "Momentum",
  trend: "Tendencia",
  volatility: "Volatilidad",
  volume: "Volumen",
  score: "Score",
  regimen: "Régimen",
  base: "Señal base",
  variacion_score: "Variación del score",
};

export function nombre(clave: string): string {
  return NOMBRES[clave] ?? clave.replace(/_/g, " ");
}

function mayuscula(texto: string | null): string | null {
  if (!texto) return null;
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

export function numero(v: number | null | undefined, decimales = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/d";
  return v.toLocaleString("es-ES", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

export function millones(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/d";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)} MM`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(1)} M`;
  return numero(v, 0);
}

/** Tarjeta de cifra (v2): rotulo en mono, cifra grande y de donde sale. */
export function Tarjeta({
  rotulo,
  cifra,
  apunte,
  acento = false,
}: {
  rotulo: string;
  cifra: ReactNode;
  apunte?: ReactNode;
  acento?: boolean;
}) {
  return (
    <div className={`kpi${acento ? " is-accent" : ""}`}>
      <div className="label-mono">{rotulo}</div>
      <div className="kpi-n">{cifra}</div>
      {apunte ? <div className="kpi-note">{apunte}</div> : null}
    </div>
  );
}

/** Panel (v2): caja de borde fino con cabecera subrayada en tinta. */
export function Panel({
  titulo,
  extra,
  children,
  acento = false,
  sinRelleno = false,
}: {
  titulo?: ReactNode;
  extra?: ReactNode;
  children: ReactNode;
  acento?: boolean;
  sinRelleno?: boolean;
}) {
  return (
    <div className={`panel-box${acento ? " is-accent" : ""}`}>
      {titulo ? (
        <div className="panel-box-head">
          <h2>{titulo}</h2>
          {extra}
        </div>
      ) : null}
      <div style={sinRelleno ? undefined : { padding: "14px" }}>{children}</div>
    </div>
  );
}

/** Las cuatro marcas de registro «+» del marco blueprint de Industry. */
export function Esquinas() {
  return (
    <>
      <i className="corner tl" />
      <i className="corner tr" />
      <i className="corner bl" />
      <i className="corner br" />
    </>
  );
}

/** Cabecera de pagina (v2): numero y seccion en mono, titulo condensado, dato de contexto. */
export function Encabezado({ rotulo, titulo, meta }: { rotulo: string; titulo: ReactNode; meta?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <span className="kicker">{rotulo}</span>
        <h1>{titulo}</h1>
      </div>
      {meta ? <span className="meta">{meta}</span> : null}
    </div>
  );
}

/** Las dos vistas de Descubrir: rankings y screener. Enlaces, no pestañas con estado. */
export function PestanasDescubrir({ activa, fecha }: { activa: "rankings" | "screener"; fecha: string | null }) {
  const sufijo = fecha ? `?fecha=${fecha}` : "";
  return (
    <nav className="seg" aria-label="Descubrir" style={{ marginBottom: 20 }}>
      <a className={`seg-opt${activa === "rankings" ? " is-on" : ""}`} href={`/rankings${sufijo}`} aria-current={activa === "rankings" ? "page" : undefined}>
        Rankings · 10 vistas
      </a>
      <a className={`seg-opt${activa === "screener" ? " is-on" : ""}`} href={`/screener${sufijo}`} aria-current={activa === "screener" ? "page" : undefined}>
        Screener · filtros
      </a>
    </nav>
  );
}
