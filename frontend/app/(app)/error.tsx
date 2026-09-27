"use client";

// Un fallo al pintar una pagina de la aplicacion: se dice, sin cifras viejas.

import { Esquinas } from "@/components/piezas";

export default function ErrorPagina({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="page">
      <div role="alert" className="error-card">
        <div className="stripe" />
        <div className="body">
          <span className="error-code">⊘ ERROR · FALLO AL PINTAR LA PÁGINA</span>
          <h2>No se ha podido cargar esta vista</h2>
          <p>No mostramos cifras guardadas como si fueran de hoy. Reintenta en unos segundos.</p>
          <div className="actions">
            <button className="btn btn-primary blueprint" onClick={reset}>
              <Esquinas />
              Reintentar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
