import { Sidebar, MobileNav } from '@/components/AppNav';
import { LegalApp } from '@/components/Legal';
import { Brand } from '@/components/Logo';
import { SearchShortcut } from '@/components/SearchShortcut';
import { getMarkets } from '@/lib/api';
import { demoState } from '@/lib/demo';
import { fmtDate, withFecha } from '@/lib/format';
import { isPersonal, pastDate } from '@/lib/session';
import type { Market } from '@/lib/types';

export const dynamic = 'force-dynamic';

function tape(m: Market) {
  const p = m.prices;
  if (p.status === 'retraso') return { late: true, g: '◷', txt: `retraso · cierre ${fmtDate(p.lastClose, false)}` };
  if (p.status === 'al_dia') return { late: false, g: '✓', txt: `al día · cierre ${fmtDate(p.lastClose, false)}` };
  return { late: true, g: '⊘', txt: `sin precios · ${p.reason}` };
}

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const fecha = pastDate();
  const personal = isPersonal();
  const markets = await getMarkets(fecha);
  const demo = demoState();
  const past = !!fecha;

  const chip = past
    ? `◷ ${fmtDate(fecha!).toUpperCase()}`
    : markets.status === 'ok'
      ? `HOY · ${fmtDate(markets.asOf).toUpperCase()}`
      : 'HOY · SIN FECHA DE DATOS';

  return (
    <div className="grid-canvas">
      <header className={`topbar${past ? ' is-past' : ''}`}>
        <div className="brand-cell">
          <Brand href={withFecha('/panel', fecha)} size={26} ink={past ? 'var(--paper)' : 'var(--ink)'} hole={past ? 'var(--ink)' : 'var(--color-bg)'} />
        </div>
        <div className="topbar-search desk-only">
          <form action="/buscar" method="get" role="search" className="searchbox">
            <span className="mono" aria-hidden="true">⌕</span>
            <label htmlFor="q-top" className="visually-hidden">Buscar por ticker, nombre o ISIN</label>
            <input id="q-top" name="q" type="search" placeholder="Ticker, nombre o ISIN" autoComplete="off" />
            {fecha && <input type="hidden" name="fecha" value={fecha} />}
            <kbd aria-hidden="true">/</kbd>
          </form>
          <SearchShortcut inputId="q-top" />
        </div>
        <div className="topbar-right">
          <span className="date-chip" title={past ? 'Consulta de fecha pasada' : 'Fecha de los últimos datos'}>{chip}</span>
        </div>
      </header>

      {past && (
        <div role="status" className="past-banner">
          <span className="past-tag">◷ CONSULTA PASADA · {fmtDate(fecha!).toUpperCase()}</span>
          <span className="past-text">Datos tal como estaban ese día. Nada de esta vista es de hoy.</span>
          <a className="btn btn-secondary btn-paper" href="?">Volver a hoy</a>
        </div>
      )}

      {demo && (
        <div role="note" className="demo-banner">
          DATOS DE DEMOSTRACIÓN · cifras de la maqueta, no de la API{demo !== 'datos' ? ` · estado: ${demo}` : ''}
        </div>
      )}

      <nav className="tape" aria-label="Frescura de precios por mercado">
        {markets.status === 'ok' && markets.data.length > 0 ? (
          markets.data.map((m) => {
            const t = tape(m);
            return (
              <a key={m.id} href={withFecha('/datos', fecha)} className={t.late ? 'is-late' : undefined}>
                <strong>{m.id}</strong>
                <span aria-hidden="true">{t.g}</span>
                <span className="tape-txt">{t.txt}</span>
                <span className="visually-hidden mob-only">{t.txt}</span>
              </a>
            );
          })
        ) : (
          <span className="tape-none">
            ⊘ Frescura por mercado no disponible
            {markets.status === 'unavailable' ? `: ${markets.reason}` : markets.status === 'error' ? `: ${markets.code}` : ': sin mercados cargados'}
          </span>
        )}
      </nav>

      <div className="app-body">
        <Sidebar personal={personal} fecha={fecha} />
        <div className="main">
          <main className="page">{children}</main>
          <LegalApp />
        </div>
      </div>

      <MobileNav personal={personal} fecha={fecha} />
    </div>
  );
}
