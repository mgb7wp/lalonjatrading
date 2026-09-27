import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';

export const metadata = { title: 'Seguimiento' };

export default function Page() {
  return (
    <>
      <PageHead kicker="05 · SEGUIMIENTO" title="Seguimiento" />
      <PendingScreen />
    </>
  );
}
