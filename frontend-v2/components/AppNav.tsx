'use client';
import { usePathname } from 'next/navigation';
import { withFecha } from '@/lib/format';

// Se renderiza en servidor con la ruta actual, así que el estado activo funciona sin JavaScript.

interface Item { href: string; label: string; short?: string }
interface Group { title: string; personal?: boolean; items: Item[] }

const GROUPS: Group[] = [
  { title: 'ANALIZAR', items: [{ href: '/panel', label: 'Panel' }, { href: '/mercados', label: 'Mercados' }, { href: '/descubrir', label: 'Descubrir' }, { href: '/analista', label: 'Analista IA' }, { href: '/buscar', label: 'Buscar' }] },
  { title: 'MIS DATOS', items: [{ href: '/seguimiento', label: 'Seguimiento', short: 'Seguim.' }, { href: '/cartera', label: 'Cartera' }] },
  { title: 'OPERAR', personal: true, items: [{ href: '/hoja', label: 'Hoja de órdenes' }, { href: '/alertas', label: 'Alertas' }] },
  { title: 'SISTEMA', items: [{ href: '/datos', label: 'Estado de datos' }, { href: '/ajustes', label: 'Ajustes' }] },
];
const MOBILE_BAR = ['/panel', '/descubrir', '/seguimiento', '/cartera'];

function useNav(personal: boolean) {
  const path = usePathname();
  let i = 0;
  const groups = GROUPS.filter((g) => personal || !g.personal).map((g) => ({
    ...g,
    items: g.items.map((it) => ({ ...it, n: String(++i).padStart(2, '0'), active: path === it.href || path.startsWith(it.href + '/'), personal: !!g.personal })),
  }));
  return { groups, flat: groups.flatMap((g) => g.items) };
}

export function Sidebar({ personal, fecha }: { personal: boolean; fecha: string | null }) {
  const { groups } = useNav(personal);
  return (
    <aside className="sidebar">
      <nav aria-label="Principal" style={{ display: 'contents' }}>
        {groups.map((g) => (
          <div key={g.title} className={`nav-group${g.personal ? ' is-personal' : ''}`}>
            <div className="nav-group-title">
              <span>{g.title}</span>
              {g.personal && <span className="personal-mark">PERSONAL</span>}
            </div>
            {g.items.map((it) => (
              <a key={it.href} href={withFecha(it.href, fecha)} className="nav-link" aria-current={it.active ? 'page' : undefined}>
                <span className="nav-i" aria-hidden="true">{it.n}</span>
                {it.label}
              </a>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  );
}

/** Barra inferior móvil; «Más» es un <details>, así que abre sin JavaScript. */
export function MobileNav({ personal, fecha }: { personal: boolean; fecha: string | null }) {
  const { flat } = useNav(personal);
  const bar = flat.filter((n) => MOBILE_BAR.includes(n.href));
  const more = flat.filter((n) => !MOBILE_BAR.includes(n.href));
  return (
    <nav className="mob-nav" aria-label="Principal">
      <div className="mob-nav-bar">
        {bar.map((n) => (
          <a key={n.href} href={withFecha(n.href, fecha)} className="mob-nav-link" aria-current={n.active ? 'page' : undefined}>
            <span className="nav-i" aria-hidden="true">{n.n}</span>
            {n.short ?? n.label}
          </a>
        ))}
        <details className="mob-more">
          <summary>
            <span className="nav-i" aria-hidden="true">··</span>
            <span className="when-closed">Más</span>
            <span className="when-open">Cerrar</span>
          </summary>
          <div className="mob-more-list">
            {more.map((n) => (
              <a key={n.href} href={withFecha(n.href, fecha)} aria-current={n.active ? 'page' : undefined}>
                <span className="nav-i" aria-hidden="true">{n.n}</span>
                {n.label}
                {n.personal ? <span className="personal-mark">PERSONAL</span> : <span />}
              </a>
            ))}
          </div>
        </details>
      </div>
    </nav>
  );
}
