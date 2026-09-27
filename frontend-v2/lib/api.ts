import 'server-only';
import { DEMO_AS_OF, demoMarkets, demoMovers, demoSignals, demoState, demoStats, demoTop } from './demo';
import type { Loaded, Market, Movers, SignalDistribution, TopScored, UniverseStats } from './types';

// Cliente de la API del motor, solo en servidor.
//
// Contrato supuesto (ajústalo a la API real): GET {LALONJA_API_URL}{ruta}[?fecha=YYYY-MM-DD]
// responde 200 con { "data": T, "as_of": "YYYY-MM-DD[THH:MM]" }, o
//          200 con { "unavailable": "motivo legible" } si el dato no existe,
// y cualquier otro código se trata como error (con «last_valid» opcional en el cuerpo).
//
// Sin LALONJA_API_URL ni LALONJA_DEMO, todo bloque se declara «no disponible».

const NOT_CONFIGURED = 'API del motor no configurada (falta LALONJA_API_URL)';

async function get<T>(path: string, fecha: string | null, demo: () => T): Promise<Loaded<T>> {
  const d = demoState();
  if (d) {
    if (d === 'error') return { status: 'error', code: 'API 503', at: new Date().toISOString(), lastValid: '2026-09-25' };
    return { status: 'ok', data: demo(), asOf: fecha ?? DEMO_AS_OF };
  }
  const base = process.env.LALONJA_API_URL?.replace(/\/$/, '');
  if (!base) return { status: 'unavailable', reason: NOT_CONFIGURED };
  const url = base + path + (fecha ? (path.includes('?') ? '&' : '?') + 'fecha=' + fecha : '');
  try {
    const res = await fetch(url, { cache: 'no-store', headers: { accept: 'application/json' } });
    const body = await res.json().catch(() => null);
    if (!res.ok) return { status: 'error', code: `API ${res.status}`, at: new Date().toISOString(), lastValid: body?.last_valid };
    if (body && typeof body.unavailable === 'string') return { status: 'unavailable', reason: body.unavailable };
    if (!body || body.data === undefined || typeof body.as_of !== 'string')
      return { status: 'error', code: 'respuesta no válida', at: new Date().toISOString() };
    return { status: 'ok', data: body.data as T, asOf: body.as_of };
  } catch {
    return { status: 'error', code: 'sin conexión con la API', at: new Date().toISOString() };
  }
}

const isEmptyDemo = () => demoState() === 'vacio';

export const getMarkets = (fecha: string | null) =>
  get<Market[]>('/markets', fecha, () => (isEmptyDemo() ? [] : demoMarkets(demoState()!)));

export const getTopScored = (fecha: string | null) =>
  get<TopScored>('/rankings/top?limit=6', fecha, () => (isEmptyDemo() ? { ...demoTop('datos'), rows: [] } : demoTop(demoState()!)));

export const getMovers = (fecha: string | null) =>
  get<Movers>('/rankings/movers?days=30&limit=3', fecha, () =>
    isEmptyDemo() ? { up: [], down: [], excludedNonComparable: 0 } : demoMovers(demoState()!),
  );

export const getSignalDistribution = (fecha: string | null) =>
  get<SignalDistribution>('/signals/distribution', fecha, () =>
    isEmptyDemo()
      ? { counts: { compra_fuerte: 0, compra: 0, mantener: 0, venta: 0, venta_fuerte: 0 }, none: 0, total: 0, horizonDays: 90 }
      : demoSignals(),
  );

export async function getUniverseStats(): Promise<Loaded<UniverseStats>> {
  // En demo «parcial» la portada muestra el estado sin cifras, como en la maqueta.
  if (demoState() === 'parcial') return { status: 'unavailable', reason: 'La API no ha respondido' };
  return get<UniverseStats>('/universe/stats', null, demoStats);
}
