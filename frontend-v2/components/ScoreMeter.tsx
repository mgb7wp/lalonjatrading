/**
 * Medidor de score: 10 celdas de UN SOLO TONO que se oscurecen al subir. Nunca semáforo.
 * `score` null → todas las celdas vacías (el texto de al lado declara el motivo).
 */
export function ScoreMeter({ score, height = 10, label }: { score: number | null; height?: number; label?: string }) {
  return (
    <span
      className="meter"
      role="img"
      aria-label={label ?? (score == null ? 'Score no disponible' : `Score ${score} sobre 100, percentil en su cohorte`)}
      style={{ ['--h' as string]: `${height}px` }}
    >
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} style={score != null && score > i * 10 ? { background: `var(--tone-${i})` } : undefined} />
      ))}
    </span>
  );
}

/** Escala completa (esquema de la portada). */
export function ToneScale({ height = 14 }: { height?: number }) {
  return (
    <span className="meter" aria-hidden="true" style={{ ['--h' as string]: `${height}px` }}>
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} style={{ background: `var(--tone-${i})` }} />
      ))}
    </span>
  );
}
