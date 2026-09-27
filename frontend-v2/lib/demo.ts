// Datos de demostración: las mismas cifras de la maqueta de Claude Design.
// Solo se usan con LALONJA_DEMO activado, y la interfaz lo declara con una franja visible.
// NO son datos reales.
import type { Market, Movers, ScoredStock, SignalDistribution, SignalKey, TopScored, UniverseStats } from './types';

export type DemoState = 'datos' | 'parcial' | 'vacio' | 'error';

export function demoState(): DemoState | null {
  const v = (process.env.LALONJA_DEMO || '').trim().toLowerCase();
  if (!v || v === '0' || v === 'false') return null;
  if (v === 'parcial' || v === 'vacio' || v === 'error') return v;
  return 'datos';
}

export const DEMO_AS_OF = '2026-09-26';

const RAW: [string, string, ScoredStock['market'], number, number | null, SignalKey, number | null][] = [
  ['IBE.MC', 'Iberdrola', 'ES', 81, 6, 'compra', 75],
  ['ITX.MC', 'Inditex', 'ES', 78, 2, 'compra', 76],
  ['MSFT', 'Microsoft', 'US', 74, 1, 'mantener', 73],
  ['HDFCBANK.NS', 'HDFC Bank', 'IN', 72, 4, 'compra', 68],
  ['WEGE3.SA', 'WEG', 'BR', 71, 3, 'compra', 68],
  ['SAN.MC', 'Banco Santander', 'ES', 69, 11, 'compra', 58],
  ['SAP.DE', 'SAP', 'DE', 63, -9, 'mantener', 72],
  ['PETR4.SA', 'Petrobras', 'BR', 41, 9, 'mantener', 32],
  ['VALE3.SA', 'Vale', 'BR', 31, -12, 'venta', 43],
  ['BAYN.DE', 'Bayer', 'DE', 22, -14, 'venta_fuerte', 36],
  ['RELIANCE.NS', 'Reliance Industries', 'IN', 55, null, 'mantener', null],
];

const STOCKS: ScoredStock[] = RAW.map(([ticker, name, market, score, delta30, signal, prevScore]) => ({
  ticker,
  name,
  market,
  score,
  delta30,
  signal,
  prevScore,
}));
const by = (t: string) => STOCKS.find((s) => s.ticker === t)!;

export function demoMarkets(s: DemoState): Market[] {
  const partial = s === 'parcial';
  return [
    { id: 'ES', name: 'España', bloc: 'desarrollado', currency: 'EUR', index: 'IBEX 35', stocks: 30, regime: 'lateral', medianScore: 54, prices: { status: 'al_dia', lastClose: '2026-09-25' }, fundamentals: { status: 'ok', until: '2026-09-15' } },
    { id: 'US', name: 'EE. UU.', bloc: 'desarrollado', currency: 'USD', index: 'S&P 500', stocks: 40, regime: 'alcista', medianScore: 57, prices: { status: 'al_dia', lastClose: '2026-09-25' }, fundamentals: partial ? { status: 'no_disponible', reason: 'fuente caída desde 24 sep' } : { status: 'ok', until: '2026-09-19' } },
    { id: 'DE', name: 'Alemania', bloc: 'desarrollado', currency: 'EUR', index: 'DAX 40', stocks: 25, regime: 'lateral', medianScore: 52, prices: { status: 'al_dia', lastClose: '2026-09-25' }, fundamentals: { status: 'ok', until: '2026-09-12' } },
    { id: 'IN', name: 'India', bloc: 'emergente', currency: 'INR', index: 'Nifty 50', stocks: 25, regime: 'alcista', medianScore: 55, prices: { status: 'retraso', lastClose: '2026-09-22', lateSessions: 3 }, fundamentals: { status: 'ok', until: '2026-09-10' } },
    { id: 'BR', name: 'Brasil', bloc: 'emergente', currency: 'BRL', index: 'Ibovespa', stocks: 23, regime: partial ? 'desconocido' : 'bajista', medianScore: 46, prices: { status: 'al_dia', lastClose: '2026-09-25' }, fundamentals: { status: 'ok', until: '2026-09-05' } },
  ];
}

export function demoTop(s: DemoState): TopScored {
  return { rows: STOCKS.slice(0, s === 'parcial' ? 4 : 6), profile: 'equilibrado', cohortMin: 18, cohortMax: 40 };
}

export function demoMovers(s: DemoState): Movers {
  return {
    up: ['SAN.MC', 'PETR4.SA', 'IBE.MC'].map(by),
    down: ['BAYN.DE', 'VALE3.SA', 'SAP.DE'].map(by),
    excludedNonComparable: s === 'parcial' ? 3 : 0,
  };
}

export function demoSignals(): SignalDistribution {
  return { counts: { compra_fuerte: 6, compra: 21, mantener: 88, venta: 17, venta_fuerte: 7 }, none: 4, total: 143, horizonDays: 90 };
}

export function demoStats(): UniverseStats {
  return { markets: 5, stocks: 143, historyYears: 11 };
}
