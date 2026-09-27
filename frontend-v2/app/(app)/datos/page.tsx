import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';

export const metadata = { title: 'Estado de los datos' };

export default function Page() {
  return (
    <>
      <PageHead kicker="09 · ESTADO DE LOS DATOS" title="Estado de los datos" />
      <PendingScreen />
    </>
  );
}
