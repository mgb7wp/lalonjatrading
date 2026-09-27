// Los estados de una pantalla (v2): cargando, primer uso y error.
//
// Cada bloque de datos declara su propio «no disponible» (ver `Bloque` en
// piezas.tsx), asi que el estado «parcial» sale solo. Estos son los de pagina
// entera: cuando no hay nada que ensenar, se dice por que.

import { Esquinas } from "./piezas";

/** Cargando: huecos con la forma de la pagina, sin ninguna cifra. */
export function Cargando({ que }: { que?: string }) {
  return (
    <div aria-busy="true" className="skeleton">
      <div className="mono" style={{ fontSize: 12, color: "var(--tinta-3)" }}>
        ▮▯▯ Cargando{que ? ` ${que}` : ""}… no se muestra ninguna cifra hasta tenerla.
      </div>
      <div className="skeleton-cells">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} />
        ))}
      </div>
      <div className="skeleton-rows">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} />
        ))}
      </div>
    </div>
  );
}

/** Primer uso: todavia no hay datos que ensenar. */
export function PrimerUso({ titulo, texto, accion, href }: { titulo: string; texto: string; accion?: string; href?: string }) {
  return (
    <div className="blueprint state-card">
      <Esquinas />
      <span className="kicker">PRIMER USO</span>
      <h2>{titulo}</h2>
      <p>{texto}</p>
      {accion && href ? (
        <div>
          <a className="btn btn-primary blueprint" href={href}>
            <Esquinas />
            {accion}
          </a>
        </div>
      ) : null}
    </div>
  );
}

/** Error: nunca se ensenan cifras guardadas como si fueran de hoy. */
export function ErrorCarga({ que, detalle, reintentar }: { que: string; detalle?: string; reintentar: string }) {
  return (
    <div role="alert" className="error-card">
      <div className="stripe" />
      <div className="body">
        <span className="error-code">⊘ ERROR{detalle ? ` · ${detalle.toUpperCase()}` : ""}</span>
        <h2>No se ha podido cargar {que}</h2>
        <p>No mostramos cifras guardadas como si fueran de hoy. Reintenta en unos segundos.</p>
        <div className="actions" style={{ gap: 8 }}>
          <a className="btn btn-primary blueprint" href={reintentar}>
            <Esquinas />
            Reintentar
          </a>
        </div>
      </div>
    </div>
  );
}
