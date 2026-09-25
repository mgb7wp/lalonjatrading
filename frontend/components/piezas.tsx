import type { ReactNode } from "react";

import type { Bloque as TipoBloque, Frescura } from "@/lib/api";

/** Medidor de un score 0-100.
 *
 * UN solo tono, del oro tenue al oro pleno. Nada de semaforo: pintar de rojo un
 * 20 y de verde un 80 convierte un percentil —"esta por debajo de sus
 * comparables"— en un juicio de valor que el numero no hace. Ese juicio lo emite
 * el motor de senales, llega aparte y va etiquetado.
 *
 * El diseno hace lo mismo en su pildora de score, asi que aqui no hay conflicto
 * entre lo que pedia el sistema anterior y lo que pide el nuevo. */
export function Medidor({ valor }: { valor: number | null }) {
  if (valor === null || Number.isNaN(valor)) {
    return <span className="apunte">no disponible</span>;
  }
  const acotado = Math.max(0, Math.min(100, valor));
  const tono =
    acotado >= 75
      ? "var(--escala-600)"
      : acotado >= 50
        ? "var(--escala-450)"
        : acotado >= 25
          ? "var(--escala-300)"
          : "var(--escala-100)";
  return (
    <span className="medidor">
      <span className="medidor-canal">
        <span className="medidor-relleno" style={{ width: `${acotado}%`, background: tono }} />
      </span>
      <span className="medidor-valor">{acotado.toFixed(0)}</span>
    </span>
  );
}

/** La pildora de score del diseno: oro pleno arriba, oro tenue en medio, gris
 * abajo. Sigue siendo un solo tono. */
export function PildoraScore({ valor }: { valor: number | null }) {
  if (valor === null) return <span className="apunte">—</span>;
  const alto = valor >= 85;
  const medio = valor >= 70;
  return (
    <span
      className="mono"
      style={{
        fontSize: 13,
        padding: "3px 9px",
        borderRadius: "var(--radio-2)",
        color: alto ? "var(--fondo)" : "var(--tinta)",
        background: alto ? "var(--oro)" : medio ? "var(--oro-16)" : "var(--borde)",
      }}
    >
      {valor.toFixed(0)}
    </span>
  );
}

/** Colores de ESTADO, reservados, y siempre con glifo + texto.
 *
 * Una recomendacion de inversion tiene que poder leerse sin interpretar un
 * color: ni el daltonismo ni una pantalla mala pueden cambiar lo que dice. */
const ESTADO_SENAL: Record<string, { texto: string; glifo: string; color: string }> = {
  strong_buy: { texto: "Compra fuerte", glifo: "▲▲", color: "var(--bueno)" },
  buy: { texto: "Compra", glifo: "▲", color: "var(--bueno)" },
  hold: { texto: "Mantener", glifo: "●", color: "var(--aviso)" },
  sell: { texto: "Venta", glifo: "▼", color: "var(--serio)" },
  strong_sell: { texto: "Venta fuerte", glifo: "▼▼", color: "var(--critico)" },
};

export function InsigniaSenal({ senal }: { senal: string | null }) {
  if (!senal) return <span className="apunte">—</span>;
  const e = ESTADO_SENAL[senal] ?? { texto: senal, glifo: "●", color: "var(--tinta-3)" };
  return (
    <span className="insignia" style={{ color: e.color, borderColor: e.color }}>
      <span className="insignia-glifo" aria-hidden="true">
        {e.glifo}
      </span>
      {e.texto}
    </span>
  );
}

const ESTADO_REGIMEN: Record<string, { texto: string; glifo: string; color: string }> = {
  alcista: { texto: "Alcista", glifo: "↗", color: "var(--bueno)" },
  lateral: { texto: "Lateral", glifo: "→", color: "var(--aviso)" },
  bajista: { texto: "Bajista", glifo: "↘", color: "var(--critico)" },
  desconocido: { texto: "Desconocido", glifo: "?", color: "var(--tinta-3)" },
};

export function InsigniaRegimen({ regimen }: { regimen: string | null }) {
  const e = ESTADO_REGIMEN[regimen ?? "desconocido"] ?? ESTADO_REGIMEN.desconocido;
  return (
    <span className="insignia" style={{ color: e.color, borderColor: e.color }}>
      <span className="insignia-glifo" aria-hidden="true">
        {e.glifo}
      </span>
      {e.texto}
    </span>
  );
}

/** Variacion con signo y glifo delante.
 *
 * El diseno trae un interruptor `signalGlyphs` que antepone ▲/▼ justo para que
 * la direccion se lea sin interpretar el color. Aqui van siempre: el color es
 * refuerzo, no el portador del dato.
 *
 * `null` NO se pinta como cero. Un cero afirma "no se movio", que es una
 * afirmacion sobre datos que no existen. */
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
        —
      </span>
    );
  }
  const signo = valor > 0 ? "▲ +" : valor < 0 ? "▼ −" : "· ";
  return (
    <span className={`mono ${valor > 0 ? "sube" : valor < 0 ? "baja" : ""}`} style={{ fontSize: 12 }}>
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
          No disponible. {mayuscula(bloque.motivo) ?? "Sin motivo indicado."}
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
        <strong style={{ color: "var(--tinta-2)" }}>Todavía no disponible.</strong> {motivo}
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
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("es-ES", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

export function millones(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)} MM`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(1)} M`;
  return numero(v, 0);
}

/** Tarjeta de cifra del diseno: rotulo, cifra grande en monoespaciada y apunte. */
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
    <div
      style={{
        background: "var(--superficie)",
        border: "1px solid var(--borde-2)",
        borderLeft: acento ? "2px solid var(--oro)" : undefined,
        borderRadius: "var(--radio)",
        padding: "18px 18px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div className="rotulo" style={{ fontSize: 10, letterSpacing: "0.14em" }}>
        {rotulo}
      </div>
      <div className="mono" style={{ fontSize: 26, letterSpacing: "-0.02em" }}>
        {cifra}
      </div>
      {apunte ? <div style={{ fontSize: 11, color: "var(--tinta-4)" }}>{apunte}</div> : null}
    </div>
  );
}

/** Panel del diseno: superficie con borde y, opcionalmente, cabecera. */
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
    <div
      style={{
        background: "var(--superficie)",
        border: "1px solid var(--borde-2)",
        borderLeft: acento ? "2px solid var(--oro)" : undefined,
        borderRadius: "var(--radio)",
        overflow: "hidden",
      }}
    >
      {titulo ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 14,
            padding: "16px 20px",
            borderBottom: "1px solid var(--borde)",
          }}
        >
          <span style={{ fontWeight: 600, fontSize: 14 }}>{titulo}</span>
          {extra}
        </div>
      ) : null}
      <div style={sinRelleno ? undefined : { padding: "18px 20px" }}>{children}</div>
    </div>
  );
}
