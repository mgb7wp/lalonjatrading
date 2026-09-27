/** Dos cuadrados iguales desplazados en diagonal; el solape se vacía al color del fondo. */
export function LogoMark({ size = 28, ink = 'var(--ink)', hole = 'var(--color-bg)' }: { size?: number; ink?: string; hole?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 236 236" aria-hidden="true">
      <rect x="67" y="0" width="169" height="169" fill={ink} />
      <rect x="0" y="67" width="169" height="169" fill="var(--logo-gold)" />
      <rect x="67" y="67" width="102" height="102" fill={hole} />
    </svg>
  );
}

export function Brand({ href = '/', size = 28, ink, hole }: { href?: string; size?: number; ink?: string; hole?: string }) {
  return (
    <a href={href} className="brand" aria-label="LaLonja Trading, inicio">
      <LogoMark size={size} ink={ink} hole={hole} />
      <span>
        <span className="brand-name" style={{ display: 'block' }}>LaLonja</span>
        <span className="brand-sub" style={{ display: 'block' }}>TRADING</span>
      </span>
    </a>
  );
}
