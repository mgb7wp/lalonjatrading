import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';

export const metadata = { title: 'Analista IA' };

export default function Page() {
  return (
    <>
      <PageHead kicker="04 · ANALISTA IA" title="Analista IA" />
      <PendingScreen />
    </>
  );
}
