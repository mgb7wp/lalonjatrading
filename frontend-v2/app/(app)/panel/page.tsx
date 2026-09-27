import { Delta } from '@/components/Delta';
import { PageHead } from '@/components/PageHead';
import { ScoreMeter } from '@/components/ScoreMeter';
import { SignalChip } from '@/components/SignalChip';
import { EmptyState, ErrorState, Unavailable } from '@/components/States';
import { getMarkets, getMovers, getSignalDistribution, getTopScored } from '@/lib/api';
import { fmtDate, fmtNum, withFecha } from '@/lib/format';
import { pastDate } from '@/lib/session';
import { MARKET_NAME, REGIME_GLYPH, SIGNALS, SIGNAL_ORDER } from '@/lib/signals';
import type { Loaded, ScoredStock } from '@/lib/types';

export const metadata = { title: 'Panel' };
export const dynamic = 'force-dynamic';

const why = (l: Loaded<unknown>) => (l.status === 'unavailable' ? l.reason : l.status === 'error' ? `error de la API (${l.code})` : '');

export default async function Panel() {
  const fecha = pastDate();
  const [markets, signals, top, movers] = await Promise.all([getMarkets(fecha), getSignalDistribution(fecha), getTopScored(fecha), getMovers(fecha)]);
  const all = [markets, signals, top, movers];
  const asOf = [markets, signals, top].find((l) => l.status === 'ok')?.asOf ?? fecha;
  const head = (
    <PageHead
      kicker="01 · PANEL"
      title={asOf ? `Universo al ${fmtDate(asOf)}` : 'Universo'}
      meta={signals.status === 'ok' ? `${fmtNum(signals.data.total)} valores · perfil ${top.status === 'ok' ? top.data.profile : 'equilibrado'}` : undefined}
    />
  );

  const firstErr = all.find((l) => l.status === 'error');
  if (all.every((l) => l.status === 'error') && firstErr?.status === 'error')
    return (
      <>
        {head}
        <ErrorState name="el panel" code={firstErr.code} at={firstErr.at} lastValid={firstErr.lastValid} retryHref={withFecha('/panel', fecha)} />
      </>
    );

  const empty = markets.status === 'ok' && markets.data.length === 0 && (top.status !== 'ok' || top.data.rows.length === 0);
  if (empty)
    return (
      <>
        {head}
        <EmptyState
          title="Aún no hay scores"
          body="El motor calcula los primeros scores tras la primera carga de precios y fundamentales."
          cta="Ver estado de los datos"
          href="/datos"
        />
      </>
    );

  const href = (t: string) => withFecha(`/ficha/${encodeURIComponent(t)}`, fecha);

  return (
    <>
      {head}

      {/* Los cinco mercados */}
      {markets.status === 'ok' ? (
        <section className="markets-strip" aria-label="Mercados">
          {markets.data.map((m) => (
            <a key={m.id} className="market-cell" href={withFecha('/mercados', fecha)}>
              <div className="top">
                <span className="name">{m.name}</span>
                <span className="idx">{m.index}</span>
              </div>
              <div className="mid">
                <div style={{ display: 'grid' }}>
                  <span style={{ fontSize: 11 }} className="muted">Score mediano</span>
                  <span className="med">{m.medianScore ?? 'n/d'}</span>
                  {m.medianScore == null && <span style={{ fontSize: 11 }}>no disponible</span>}
                </div>
                <span className="reg">
                  <span className="mono" aria-hidden="true">{REGIME_GLYPH[m.regime]}</span>
                  <br />
                  {m.regime}
                </span>
              </div>
              <ScoreMeter score={m.medianScore} height={6} />
              <div className="foot">
                {m.stocks} valores · {m.prices.status === 'al_dia' ? 'precios al día' : m.prices.status === 'retraso' ? 'precios con retraso' : 'sin precios'}
              </div>
            </a>
          ))}
        </section>
      ) : (
        <Unavailable what="Mercados" reason={why(markets)} />
      )}

      {/* Distribución de señales */}
      <section style={{ display: 'grid', gap: 10 }} aria-labelledby="h-sig">
        <div className="section-head">
          <h2 id="h-sig">Señales del universo</h2>
          {signals.status === 'ok' && (
            <span className="mono muted" style={{ fontSize: 11 }}>
              {fmtNum(signals.data.total)} valores · horizonte {signals.data.horizonDays} días · {fmtDate(signals.asOf)}
            </span>
          )}
        </div>
        {signals.status === 'ok' ? (
          <>
            <div className="sig-bar" aria-hidden="true">
              {SIGNAL_ORDER.filter((k) => signals.data.counts[k] > 0).map((k) => {
                const s = SIGNALS[k];
                return (
                  <div key={k} style={{ flex: signals.data.counts[k], background: s.solid ? s.color : 'transparent', color: s.solid ? 'var(--paper)' : s.color }}>
                    {s.glyph} {signals.data.counts[k]}
                  </div>
                );
              })}
            </div>
            <ul className="sig-legend">
              {SIGNAL_ORDER.map((k) => (
                <li key={k}>
                  <span className="mono" aria-hidden="true">{SIGNALS[k].glyph}</span> {SIGNALS[k].label}{' '}
                  <span className="mono muted">{signals.data.counts[k]}</span>
                </li>
              ))}
              <li className="muted">
                ○ Sin señal <span className="mono">{signals.data.none}</span>
              </li>
            </ul>
          </>
        ) : (
          <Unavailable what="Distribución de señales" reason={why(signals)} />
        )}
      </section>

      <section className="cols-21">
        {/* Mejor puntuados */}
        <div className="panel-box">
          <div className="panel-box-head">
            <h2>Mejor puntuados</h2>
            <a href={withFecha('/descubrir', fecha)}>Ver ranking completo</a>
          </div>
          {top.status === 'ok' ? (
            <>
              <div className="rank-headrow" aria-hidden="true">
                <span>#</span>
                <span>Valor</span>
                <span className="desk-only">Mercado</span>
                <span>Score · percentil</span>
                <span className="desk-only">Señal</span>
                <span className="right">Δ 30 d</span>
              </div>
              <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {top.data.rows.map((r, i) => (
                  <li key={r.ticker}>
                    <a className="rank-row" href={href(r.ticker)}>
                      <span className="rank">{String(i + 1).padStart(2, '0')}</span>
                      <span className="stock-id">
                        <span className="t">{r.ticker}</span>
                        <span className="n">{r.name}</span>
                      </span>
                      <span className="desk-only" style={{ fontSize: 13 }}>{MARKET_NAME[r.market]}</span>
                      <span className="score-cell">
                        <span className="s">{r.score ?? 'n/d'}</span>
                        <ScoreMeter score={r.score} />
                      </span>
                      <span className="desk-only">
                        <SignalChip signal={r.signal} />
                      </span>
                      <Delta value={r.delta30} className="right" />
                    </a>
                  </li>
                ))}
              </ol>
              <div className="note">
                Percentil dentro de cada cohorte sectorial (de {top.data.cohortMin} a {top.data.cohortMax} valores). Perfil {top.data.profile}.
              </div>
            </>
          ) : (
            <Unavailable reason={why(top)} />
          )}
        </div>

        {/* Movimientos a 30 días */}
        <div className="stack">
          <MoversBox title="Más mejoran" rows={movers.status === 'ok' ? movers.data.up : null} reason={why(movers)} href={href} />
          <MoversBox
            title="Más caen"
            rows={movers.status === 'ok' ? movers.data.down : null}
            reason={why(movers)}
            href={href}
            note={
              movers.status === 'ok' && movers.data.excludedNonComparable > 0
                ? `${movers.data.excludedNonComparable} valores no comparables (cambio de cohorte o sin score hace 30 días), excluidos de la lista.`
                : undefined
            }
          />
        </div>
      </section>
    </>
  );
}

function MoversBox({ title, rows, reason, note, href }: { title: string; rows: ScoredStock[] | null; reason: string; note?: string; href: (t: string) => string }) {
  return (
    <div className="panel-box">
      <div className="panel-box-head">
        <h2 className="sm">{title}</h2>
        <span className="mono muted" style={{ fontSize: 11 }}>score · 30 d</span>
      </div>
      {rows ? (
        rows.map((r) => (
          <a key={r.ticker} className="move-row" href={href(r.ticker)}>
            <span className="t">{r.ticker}</span>
            <span className="from">
              {r.prevScore ?? 'n/d'} → {r.score ?? 'n/d'}
            </span>
            <Delta value={r.delta30} />
          </a>
        ))
      ) : (
        <Unavailable reason={reason} />
      )}
      {note && <div className="note">{note}</div>}
    </div>
  );
}
