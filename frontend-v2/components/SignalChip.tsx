import { SIGNALS } from '@/lib/signals';
import type { SignalKey } from '@/lib/types';

/** Chip de señal: glifo + texto + color. Sin señal se declara, no se inventa. */
export function SignalChip({ signal }: { signal: SignalKey | null }) {
  if (!signal)
    return (
      <span className="sig-chip" style={{ borderColor: 'var(--color-neutral-500)', color: 'var(--muted)', borderStyle: 'dashed' }}>
        <span className="g">○</span>Sin señal
      </span>
    );
  const s = SIGNALS[signal];
  return (
    <span className="sig-chip" style={{ borderColor: s.color, color: s.color, background: s.bg }}>
      <span className="g" aria-hidden="true">{s.glyph}</span>
      {s.label}
    </span>
  );
}
