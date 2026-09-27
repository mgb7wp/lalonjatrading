import { Corners } from '@/components/Blueprint';
import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';
import { isPersonal } from '@/lib/session';

export const metadata = { title: 'Hoja de órdenes' };
export const dynamic = 'force-dynamic';

export default function Hoja() {
  const personal = isPersonal();
  return (
    <>
      <PageHead kicker="07 · HOJA DE ÓRDENES · PERSONAL" title="Hoja de órdenes" />
      {personal ? (
        <PendingScreen />
      ) : (
        <div className="blueprint state-card">
          <Corners />
          <span className="mono" style={{ fontSize: 11, letterSpacing: '.14em' }}>USO PERSONAL DESACTIVADO</span>
          <h2>La hoja de órdenes no está disponible</h2>
          <p>Las órdenes basadas en tu cartera solo existen con el uso personal activado. El resto del producto es análisis general.</p>
          <div>
            <a className="btn btn-secondary" href="/ajustes">Ir a Ajustes</a>
          </div>
        </div>
      )}
    </>
  );
}
