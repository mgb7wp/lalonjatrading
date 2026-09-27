'use client';
import { Corners } from '@/components/Blueprint';

export default function AppError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div role="alert" className="error-card">
      <div className="stripe" />
      <div className="body">
        <span className="error-code">⊘ ERROR · FALLO AL RENDERIZAR</span>
        <h2>No se ha podido cargar esta vista</h2>
        <p>No mostramos cifras guardadas como si fueran de hoy. Reintenta en unos segundos.</p>
        <div className="actions">
          <button className="btn btn-primary blueprint" onClick={reset}>
            <Corners />
            Reintentar
          </button>
        </div>
      </div>
    </div>
  );
}
