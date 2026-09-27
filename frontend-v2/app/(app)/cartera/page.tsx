import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';

export const metadata = { title: 'Cartera' };

export default function Page() {
  return (
    <>
      <PageHead kicker="06 · CARTERA" title="Cartera" />
      <PendingScreen />
    </>
  );
}
