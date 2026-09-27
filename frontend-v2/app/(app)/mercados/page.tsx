import { PageHead } from '@/components/PageHead';
import { EmptyState, ErrorState, Unavailable } from '@/components/States';
import { getMarkets } from '@/lib/api';
import { fmtDate, withFecha } from '@/lib/format';
import { pastDate } from '@/lib/session';
import { REGIME_GLYPH } from '@/lib/signals';
import type { Market } from '@/lib/types';

export const metadata = { title: 'Mercados' };
export const dynamic = 'force-dynamic';

function prices(m: Market) {
  const p = m.prices;
  if (p.status === 'al_dia') return { cls: '', g: '✓', t: `cierre ${fmtDate(p.lastClose, false)}` };
  if (p.status === 'retraso') return { cls: 'is-late', g: '◷', t: `cierre ${fmtDate(p.lastClose, false)} · ${p.lateSessions} sesiones tarde` };
  return { cls: 'is-none', g: '⊘', t: `no disponible: ${p.reason}` };
}

export default async function Mercados() {
  const fecha = pastDate();
  const markets = await getMarkets(fecha);
  const total = markets.status === 'ok' ? markets.data.reduce((a, m) => a + m.stocks, 0) : null;
  const head = (
    <PageHead kicker="02 · MERCADOS" title="Cinco mercados" meta={total != null ? `${total} valores · precios y fundamentales por mercado` : undefined} />
  );

  if (markets.status === 'error')
    return (
      <>
        {head}
        <ErrorState name="los mercados" code={markets.code} at={markets.at} lastValid={markets.lastValid} retryHref={withFecha('/mercados', fecha)} />
      </>
    );
  if (markets.status === 'unavailable')
    return (
      <>
        {head}
        <Unavailable what="Mercados" reason={markets.reason} />
      </>
    );
  if (markets.data.length === 0)
    return (
      <>
        {head}
        <EmptyState title="Ningún mercado cargado" body="Los cinco mercados aparecerán tras la primera carga de precios." cta="Ver estado de los datos" href="/datos" />
      </>
    );

  return (
    <>
      {head}
      <section className="mk-table" aria-label={`Mercados a ${fmtDate(markets.asOf)}`}>
        <div className="mk-headrow desk-only" aria-hidden="true">
          <span>Mercado</span>
          <span>Bloque</span>
          <span>Divisa</span>
          <span>Índice</span>
          <span>Valores</span>
          <span>Régimen</span>
          <span>Precios</span>
          <span>Fundamentales</span>
        </div>
        {markets.data.map((m) => {
          const p = prices(m);
          const f = m.fundamentals;
          return (
            <div key={m.id} className="mk-row">
              <span className="name">{m.name}</span>
              <span>
                <span className="tag tag-neutral">{m.bloc === 'desarrollado' ? 'Desarrollado' : 'Emergente'}</span>
              </span>
              <span className="mono"><span className="k">Divisa</span>{m.currency}</span>
              <span className="mono"><span className="k">Índice</span>{m.index}</span>
              <span className="mono">{m.stocks} valores</span>
              <span>
                <span className="k">Régimen</span>
                <span className="mono" aria-hidden="true">{REGIME_GLYPH[m.regime]}</span> {m.regime}
              </span>
              <span className="wide">
                <span className="k">Precios</span>
                <span className={`fresh ${p.cls}`}>
                  {p.g} {p.t}
                </span>
              </span>
              <span className="mono wide" style={{ fontSize: 12 }}>
                <span className="k">Fundamentales</span>
                {f.status === 'ok' ? `✓ hasta ${fmtDate(f.until, false)}` : `⊘ no disponible: ${f.reason}`}
              </span>
            </div>
          );
        })}
      </section>
      <p className="explainer">
        El régimen se calcula sobre el índice de referencia de cada mercado y limita las señales de sus valores. «Desconocido» significa que el índice no tiene histórico suficiente; no se sustituye por lateral.
      </p>
    </>
  );
}
