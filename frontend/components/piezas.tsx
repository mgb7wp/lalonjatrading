import type { ReactNode } from "react";

import type { Bloque as TipoBloque, Frescura } from "@/lib/api";

/** Medidor de un score 0-100.
 *
 * Es magnitud, asi que va en UN solo tono, claro a oscuro. Nada de semaforo:
 * pintar de rojo un 20 y de verde un 80 convierte un percentil —"esta por
 * debajo de sus comparables"— en un juicio de valor que el numero no hace.
 * Ese juicio lo emite el motor de senales, y llega aparte y etiquetado.
 */
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
        <span
          className="medidor-relleno"
          style={{ width: `${acotado}%`, background: tono }}
        />
      </span>
      <span className="medidor-valor">{acotado.toFixed(0)}</span>
    </span>
  );
}

/** Colores de ESTADO, reservados, y siempre con glifo + texto.
 *
 * Dos de los cuatro estados no llegan a 3:1 sobre la superficie clara: la
 * mitigacion es que el color nunca viaje solo. Ademas, aqui hay una razon que
 * no es de accesibilidad: una recomendacion de inversion tiene que poder leerse
 * sin interpretar un color. */
const ESTADO_SENAL: Record<string, { texto: string; glifo: string; color: string }> = {
  strong_buy: { texto: "Compra fuerte", glifo: "▲▲", color: "var(--bueno)" },
  buy: { texto: "Compra", glifo: "▲", color: "var(--bueno)" },
  hold: { texto: "Mantener", glifo: "●", color: "var(--aviso)" },
  sell: { texto: "Venta", glifo: "▼", color: "var(--serio)" },
  strong_sell: { texto: "Venta fuerte", glifo: "▼▼", color: "var(--critico)" },
};

export function InsigniaSenal({ senal }: { senal: string | null }) {
  if (!senal) return <span className="apunte">—</span>;
  const e = ESTADO_SENAL[senal] ?? {
    texto: senal,
    glifo: "●",
    color: "var(--tinta-3)",
  };
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

export function EtiquetaFrescura({ frescura }: { frescura: Frescura | null }) {
  if (!frescura) return null;
  const texto =
    frescura.dias === 0
      ? `del ${frescura.as_of}`
      : `del ${frescura.as_of} · hace ${frescura.dias} ${frescura.dias === 1 ? "dia" : "dias"}`;
  return <span className="frescura"> {texto}</span>;
}

/** Envoltorio de un bloque de §27.
 *
 * Cuando falta, se dice POR QUE y no se pinta un hueco. Un bloque vacio sin
 * explicacion obliga a quien mira a adivinar si es que no hay datos o es que
 * algo se ha roto, y esas dos cosas se atienden de forma muy distinta.
 */
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

/** Primera letra en mayuscula. Los motivos vienen del backend en minuscula y
 * se concatenan detras de un punto. */
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
