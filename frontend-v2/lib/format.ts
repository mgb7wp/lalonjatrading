const MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

export const fmtNum = (n: number, d = 0) =>
  n.toLocaleString('es-ES', { minimumFractionDigits: d, maximumFractionDigits: d });

/** «26 sep 2026». Acepta YYYY-MM-DD o ISO con hora. */
export function fmtDate(iso: string, withYear = true): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  if (!y || !m || !d) return iso;
  return `${String(d).padStart(2, '0')} ${MONTHS[m - 1]}${withYear ? ' ' + y : ''}`;
}

/** «27 sep 2026 09:00» si trae hora; si no, solo la fecha. */
export function fmtDateTime(iso: string): string {
  const t = iso.length > 10 ? iso.slice(11, 16) : '';
  return t ? `${fmtDate(iso)} ${t}` : fmtDate(iso);
}

export const UP = 'var(--up)';
export const DOWN = 'var(--down)';

export interface DeltaView {
  glyph: string;
  text: string;
  color: string;
}

/** Cifra con dirección: siempre glifo delante; null se declara «no comparable». */
export function delta(n: number | null, unit = '', d = 0): DeltaView {
  if (n == null) return { glyph: '○', text: 'no comparable', color: 'var(--muted)' };
  if (n > 0) return { glyph: '▲', text: '+' + fmtNum(n, d) + unit, color: UP };
  if (n < 0) return { glyph: '▼', text: '−' + fmtNum(-n, d) + unit, color: DOWN };
  return { glyph: '=', text: fmtNum(0, d) + unit, color: 'var(--neutral-ink)' };
}

/** Valida ?fecha=YYYY-MM-DD como consulta pasada (estrictamente anterior a hoy). */
export function parsePastDate(v: string | null | undefined): string | null {
  if (!v || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const d = new Date(v + 'T00:00:00Z');
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== v) return null;
  const today = new Date().toISOString().slice(0, 10);
  return v < today ? v : null;
}

export function withFecha(href: string, fecha: string | null): string {
  if (!fecha) return href;
  return href + (href.includes('?') ? '&' : '?') + 'fecha=' + fecha;
}
