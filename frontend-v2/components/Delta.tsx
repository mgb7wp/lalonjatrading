import { delta } from '@/lib/format';

/** Cifra con dirección: ▲/▼ siempre delante del color. */
export function Delta({ value, unit = '', digits = 0, className = '' }: { value: number | null; unit?: string; digits?: number; className?: string }) {
  const d = delta(value, unit, digits);
  return (
    <span className={`delta ${className}`} style={{ color: d.color }}>
      <span className="g" aria-hidden="true">{d.glyph}</span> {d.text}
    </span>
  );
}
