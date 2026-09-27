import { Corners } from '@/components/Blueprint';
import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';
import { isPersonal } from '@/lib/session';
import { setPersonal } from './actions';

export const metadata = { title: 'Ajustes' };
export const dynamic = 'force-dynamic';

// Provisional: Ajustes aún no tiene diseño en la v2; solo el interruptor de uso personal,
// que la hoja de órdenes necesita para desbloquearse.
export default function Ajustes({ searchParams }: { searchParams: { guardado?: string } }) {
  const personal = isPersonal();
  return (
    <>
      <PageHead kicker="10 · AJUSTES" title="Ajustes" />
      <form action={setPersonal} className="blueprint toggle-form">
        <Corners />
        <span className="personal-mark" style={{ justifySelf: 'start', fontSize: 10, padding: '1px 6px' }}>PERSONAL</span>
        <h2 style={{ margin: 0, fontSize: 24, textTransform: 'uppercase' }}>Uso personal</h2>
        <p style={{ margin: 0, fontSize: 14 }}>
          Activa la hoja de órdenes semanal y las alertas: recomendaciones basadas en tu cartera. Se muestran siempre separadas del análisis general.
        </p>
        {searchParams.guardado && <div role="status" className="alert alert-ok">Guardado.</div>}
        <input type="hidden" name="personal" value={personal ? '0' : '1'} />
        <div>
          <button className="btn btn-secondary" type="submit">
            {personal ? 'Desactivar uso personal' : 'Activar uso personal'}
          </button>
        </div>
        <span className="mono muted" style={{ fontSize: 11 }}>Estado actual: {personal ? 'activado' : 'desactivado'}</span>
      </form>
      <PendingScreen />
    </>
  );
}
