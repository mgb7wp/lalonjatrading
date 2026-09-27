import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';

export const metadata = { title: 'Alertas' };

export default function Page() {
  return (
    <>
      <PageHead kicker="08 · ALERTAS" title="Alertas" />
      <PendingScreen />
    </>
  );
}
