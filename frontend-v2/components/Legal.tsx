/** Aviso legal visible en todas las páginas, no escondido en un enlace. */
export function LegalPublic() {
  return (
    <footer className="legal">
      <strong>Esto no es asesoramiento financiero.</strong>
      <span>Análisis automatizado con fines informativos.</span>
      <a href="/metodologia">Metodología y autor</a>
    </footer>
  );
}

export function LegalApp() {
  return (
    <footer className="legal legal-sticky">
      <strong>Esto no es asesoramiento financiero.</strong>
      <span className="desk-only">Análisis cuantitativo automatizado; no tiene en cuenta tu situación personal.</span>
      <a href="/metodologia">Metodología y autor</a>
    </footer>
  );
}
