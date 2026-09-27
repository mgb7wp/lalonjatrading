// Contrato de datos del frontend. Cada bloque de información llega como `Loaded<T>`:
// un dato que falta se declara (unavailable, con motivo) y nunca se rellena.

export type Loaded<T> =
  | { status: 'ok'; data: T; asOf: string } // asOf: fecha ISO (YYYY-MM-DD o con hora) del dato
  | { status: 'unavailable'; reason: string }
  | { status: 'error'; code: string; at: string; lastValid?: string };

export type MarketId = 'ES' | 'US' | 'DE' | 'IN' | 'BR';
export type Regime = 'alcista' | 'lateral' | 'bajista' | 'desconocido';
export type SignalKey = 'compra_fuerte' | 'compra' | 'mantener' | 'venta' | 'venta_fuerte';

export interface Market {
  id: MarketId;
  name: string;
  bloc: 'desarrollado' | 'emergente';
  currency: string;
  index: string;
  stocks: number;
  regime: Regime;
  medianScore: number | null;
  prices:
    | { status: 'al_dia'; lastClose: string }
    | { status: 'retraso'; lastClose: string; lateSessions: number }
    | { status: 'no_disponible'; reason: string };
  fundamentals: { status: 'ok'; until: string } | { status: 'no_disponible'; reason: string };
}

export interface ScoredStock {
  ticker: string;
  name: string;
  market: MarketId;
  score: number | null;
  prevScore: number | null; // score hace 30 días; null = no comparable
  delta30: number | null;
  signal: SignalKey | null;
}

export interface TopScored {
  rows: ScoredStock[];
  profile: string;
  cohortMin: number;
  cohortMax: number;
}

export interface Movers {
  up: ScoredStock[];
  down: ScoredStock[];
  excludedNonComparable: number;
}

export interface SignalDistribution {
  counts: Record<SignalKey, number>;
  none: number;
  total: number;
  horizonDays: number;
}

export interface UniverseStats {
  markets: number;
  stocks: number;
  historyYears: number;
}
