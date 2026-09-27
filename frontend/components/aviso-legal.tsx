/** El aviso legal: visible en todas las paginas, no escondido en un enlace.
 *
 * La primera frase va siempre y en negrita. El resto del texto legal, que es
 * largo, se abre desde ahi sin salir de la pagina. */

const AVISO =
  "Información y análisis de carácter general. No es asesoramiento financiero ni una recomendación personalizada: no tiene en cuenta la situación ni los objetivos de quien lo consulta. Rentabilidades pasadas no garantizan rentabilidades futuras. Los datos proceden de fuentes públicas gratuitas y pueden contener errores u omisiones.";

export function AvisoLegal({ fijo = true }: { fijo?: boolean }) {
  return (
    <footer className={`legal${fijo ? " legal-sticky" : ""}`}>
      <strong>Esto no es asesoramiento financiero.</strong>
      <span className="desk-only">Análisis cuantitativo automatizado; no tiene en cuenta tu situación personal.</span>
      <details className="legal-more">
        <summary>Aviso completo</summary>
        <p>{AVISO}</p>
      </details>
    </footer>
  );
}
