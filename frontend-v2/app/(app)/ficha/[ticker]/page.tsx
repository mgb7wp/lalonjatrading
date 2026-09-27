import { PageHead } from '@/components/PageHead';
import { PendingScreen } from '@/components/States';

export const metadata = { title: 'Ficha' };

export default function Ficha({ params }: { params: { ticker: string } }) {
  const t = decodeURIComponent(params.ticker).toUpperCase();
  return (
    <>
      <PageHead kicker="FICHA DE UN VALOR" title={t} />
      <PendingScreen />
    </>
  );
}
