import { Corners } from '@/components/Blueprint';
import { ToneScale } from '@/components/ScoreMeter';
import { getUniverseStats } from '@/lib/api';
import { fmtDateTime, fmtNum } from '@/lib/format';

export const dynamic = 'force-dynamic';

const LEGEND: [string, string][] = [
  ['SEÑAL', 'glifo + texto, nunca solo color'],
  ['MOTIVO', 'por qué es esa y no otra'],
  ['RÉGIMEN', 'alcista · lateral · bajista · desconocido'],
  ['CONFIANZA', 'grado de acuerdo de los pilares, no probabilidad'],
  ['HORIZONTE', '90 días'],
  ['FECHA', 'toda cifra dice de qué día es'],
];

export default async function Portada() {
  const stats = await getUniverseStats();
  return (
    <main>
      <section className="hero">
        <div className="hero-main">
          <div className="kicker" style={{ letterSpacing: '.16em' }}>ANÁLISIS CUANTITATIVO · 5 MERCADOS</div>
          <h1>Cada acción, medida contra sus iguales.</h1>
          <p className="hero-lede">
            Un motor determinista puntúa cada valor de 0 a 100 dentro de su cohorte y emite señales con motivo, régimen y horizonte. La IA explica lo que el motor calculó; nunca produce una cifra.
          </p>
          <div className="actions">
            <a className="btn btn-primary blueprint btn-lg" href="/entrar?modo=registro">
              <Corners />
              Crear cuenta
            </a>
            <a className="btn btn-secondary btn-lg" href="/metodologia">Leer la metodología</a>
          </div>
        </div>
        <div className="hero-side">
          <div className="label-mono">ESQUEMA · CÓMO SE LEE UNA FICHA</div>
          <div className="blueprint schema">
            <Corners />
            <div className="schema-row">
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                <span>Score total</span>
                <span className="mono muted">0 — 100</span>
              </div>
              <ToneScale />
              <div style={{ fontSize: 12, color: 'var(--color-neutral-800)' }}>Percentil dentro de su cohorte. Un tono, de claro a oscuro. Nunca semáforo.</div>
            </div>
            <dl className="schema-legend">
              {LEGEND.map(([k, v]) => (
                <div key={k} style={{ display: 'contents' }}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </section>
      <section className="stats" aria-label="Universo analizado">
        {stats.status === 'ok' ? (
          ([
            [stats.data.markets, 'mercados'],
            [stats.data.stocks, 'valores analizados'],
            [stats.data.historyYears, 'años de histórico'],
          ] as const).map(([n, l]) => (
            <div key={l} className="stat">
              <span className="stat-n">{fmtNum(n)}</span>
              <span style={{ fontSize: 14 }}>{l}</span>
              <span className="stat-src">API · {fmtDateTime(stats.asOf)}</span>
            </div>
          ))
        ) : (
          <div className="stats-none">
            <strong>Cifras del universo no disponibles.</strong>{' '}
            {stats.status === 'unavailable' ? stats.reason + '.' : 'La API no ha respondido.'} No mostramos aproximaciones en su lugar.
          </div>
        )}
      </section>
    </main>
  );
}
