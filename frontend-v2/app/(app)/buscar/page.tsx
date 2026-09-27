import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';

export const metadata = { title: 'Buscar' };

// Formulario GET: funciona sin JavaScript y es el destino de la búsqueda de la cabecera.
export default function Buscar({ searchParams }: { searchParams: { q?: string } }) {
  const q = (searchParams.q ?? '').trim();
  return (
    <>
      <PageHead kicker="BUSCAR" title="Buscar" meta={q ? `«${q}»` : undefined} />
      <form action="/buscar" method="get" role="search" className="searchbox" style={{ maxWidth: 560 }}>
        <span className="mono" aria-hidden="true">⌕</span>
        <label htmlFor="q-page" className="visually-hidden">Buscar por ticker, nombre o ISIN</label>
        <input id="q-page" name="q" type="search" defaultValue={q} placeholder="Ticker, nombre o ISIN" autoComplete="off" />
      </form>
      <PendingScreen />
    </>
  );
}
