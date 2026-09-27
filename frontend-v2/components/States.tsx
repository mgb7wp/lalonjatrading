import { Corners } from './Blueprint';
import { fmtDate, fmtDateTime, withFecha } from '@/lib/format';

/** Cargando: huecos con la forma de la página, sin ninguna cifra. */
export function LoadingState({ name }: { name?: string }) {
  return (
    <div aria-busy="true" className="skeleton">
      <div className="mono muted" style={{ fontSize: 12 }}>
        ▮▯▯ Cargando{name ? ' ' + name : ''}… no se muestra ninguna cifra hasta tener la de hoy.
      </div>
      <div className="skeleton-cells">
        {[0, 1, 2, 3, 4].map((i) => <div key={i} />)}
      </div>
      <div className="skeleton-rows">
        {[0, 1, 2, 3, 4].map((i) => <div key={i} />)}
      </div>
    </div>
  );
}

/** Primer uso: todavía no hay datos. */
export function EmptyState({ title, body, cta, href }: { title: string; body: string; cta: string; href: string }) {
  return (
    <div className="blueprint state-card">
      <Corners />
      <span className="kicker">PRIMER USO</span>
      <h2>{title}</h2>
      <p>{body}</p>
      <div>
        <a className="btn btn-primary blueprint" href={href}>
          <Corners />
          {cta}
        </a>
      </div>
    </div>
  );
}

/** Error: nunca se muestran cifras guardadas como si fueran de hoy. */
export function ErrorState({ name, code, at, lastValid, retryHref }: { name: string; code: string; at: string; lastValid?: string; retryHref: string }) {
  return (
    <div role="alert" className="error-card">
      <div className="stripe" />
      <div className="body">
        <span className="error-code">⊘ ERROR · {code.toUpperCase()} · {fmtDateTime(at).toUpperCase()}</span>
        <h2>No se ha podido cargar {name}</h2>
        <p>
          No mostramos cifras guardadas como si fueran de hoy. Reintenta
          {lastValid ? ' o abre la última versión válida, que verás marcada como consulta pasada.' : '.'}
        </p>
        <div className="actions" style={{ gap: 8 }}>
          <a className="btn btn-primary blueprint" href={retryHref}>
            <Corners />
            Reintentar
          </a>
          {lastValid && (
            <a className="btn btn-secondary" href={withFecha(retryHref.split('?')[0], lastValid)}>
              Abrir versión del {fmtDate(lastValid, false)}
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

/** Bloque no disponible: el motivo escrito, nunca un 0 ni un guion mudo. */
export function Unavailable({ reason, what }: { reason: string; what?: string }) {
  return (
    <div className="unavailable" role="note">
      <strong>NO DISPONIBLE</strong>
      {what ? `${what}: ` : ''}
      {reason}
    </div>
  );
}

/** Pantalla aún sin diseño en la v2. */
export function PendingScreen() {
  return <div className="pending">Esta pantalla se rediseña en la siguiente entrega con el nuevo lenguaje visual.</div>;
}
