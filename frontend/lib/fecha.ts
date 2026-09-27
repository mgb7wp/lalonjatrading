// Fechas de la interfaz: formato, «hoy» y la consulta de una fecha pasada.
//
// Toda cifra dice de que dia es, y una consulta con fecha pasada («como estaba
// el 31 de marzo») tiene que distinguirse de un vistazo de la vista de hoy. La
// fecha viaja en `?fecha=AAAA-MM-DD`; el middleware la reenvia como cabecera
// porque los layouts de App Router no reciben `searchParams`.

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

export const CABECERA_FECHA = "x-lalonja-fecha";

/** «26 sep 2026». Acepta AAAA-MM-DD o ISO con hora. */
export function fmtFecha(iso: string | null | undefined, conAnio = true): string {
  if (!iso) return "sin fecha";
  const [a, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!a || !m || !d) return iso;
  return `${String(d).padStart(2, "0")} ${MESES[m - 1]}${conAnio ? ` ${a}` : ""}`;
}

/** Hoy en Madrid, AAAA-MM-DD. El servidor corre en UTC y a medianoche no coincide. */
export function hoyMadrid(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid" }).format(new Date());
}

/** Valida una consulta pasada: fecha real y estrictamente anterior a hoy. */
export function fechaPasada(v: string | null | undefined): string | null {
  if (!v || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const d = new Date(`${v}T00:00:00Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== v) return null;
  return v < hoyMadrid() ? v : null;
}

/** Conserva la consulta pasada al navegar. */
export function conFecha(href: string, fecha: string | null): string {
  if (!fecha) return href;
  return `${href}${href.includes("?") ? "&" : "?"}fecha=${fecha}`;
}
