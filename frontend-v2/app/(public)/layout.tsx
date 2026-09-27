import { Brand } from '@/components/Logo';
import { LegalPublic } from '@/components/Legal';

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid-canvas">
      <header className="pub-header">
        <Brand />
        <nav aria-label="Público">
          <a href="/metodologia" className="desk-only">Metodología</a>
          <a className="btn btn-secondary" href="/entrar">Entrar</a>
        </nav>
      </header>
      {children}
      <LegalPublic />
    </div>
  );
}
