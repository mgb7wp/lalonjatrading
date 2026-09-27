import type { MarketId, Regime, SignalKey } from './types';

export interface SignalView {
  glyph: string;
  label: string;
  color: string;
  bg: string;
  /** Relleno sólido para la barra de distribución (solo extremos). */
  solid: boolean;
}

export const SIGNALS: Record<SignalKey, SignalView> = {
  compra_fuerte: { glyph: '▲▲', label: 'Compra fuerte', color: 'var(--up)', bg: 'var(--up-tint)', solid: true },
  compra: { glyph: '▲', label: 'Compra', color: 'var(--up)', bg: 'transparent', solid: false },
  mantener: { glyph: '=', label: 'Mantener', color: 'var(--neutral-ink)', bg: 'transparent', solid: false },
  venta: { glyph: '▼', label: 'Venta', color: 'var(--down)', bg: 'transparent', solid: false },
  venta_fuerte: { glyph: '▼▼', label: 'Venta fuerte', color: 'var(--down)', bg: 'var(--down-tint)', solid: true },
};

export const SIGNAL_ORDER: SignalKey[] = ['compra_fuerte', 'compra', 'mantener', 'venta', 'venta_fuerte'];

export const REGIME_GLYPH: Record<Regime, string> = { alcista: '↗', lateral: '→', bajista: '↘', desconocido: '?' };

export const MARKET_NAME: Record<MarketId, string> = {
  ES: 'España',
  US: 'EE. UU.',
  DE: 'Alemania',
  IN: 'India',
  BR: 'Brasil',
};
