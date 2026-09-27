import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';

export const metadata = { title: 'Descubrir' };

export default function Page() {
  return (
    <>
      <PageHead kicker="03 · DESCUBRIR" title="Descubrir" />
      <PendingScreen />
    </>
  );
}
