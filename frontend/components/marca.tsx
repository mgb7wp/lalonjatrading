/** La marca de LaLonja Trading.
 *
 * Dos cuadrados iguales desplazados en diagonal, con el solape vaciado al
 * fondo. La geometria esta medida sobre el original de 512 px —cuadrados de
 * 169, desplazamiento de 67, solape de 102— en lugar de aproximarla a ojo.
 *
 * El `viewBox` recorta al DIBUJO (138,138 y 236 de lado) y no al lienzo
 * completo: con el lienzo entero, a 22 px el dibujo se quedaba en diez y no se
 * reconocia. El icono de la pestania (`app/icon.svg`) si conserva el margen.
 *
 * Version para fondo claro (v2): el cuadrado blanco del original pasa a tinta
 * oscura, porque sobre papel no se veria; el oro se mantiene. En la consulta de
 * una fecha pasada la cabecera se invierte a oscuro, y la marca con ella: por
 * eso tinta y hueco se pueden pasar.
 */
export function Marca({
  tamano = 22,
  tinta = "var(--tinta-oscura)",
  hueco = "var(--fondo)",
}: {
  tamano?: number;
  tinta?: string;
  hueco?: string;
}) {
  return (
    <svg width={tamano} height={tamano} viewBox="138 138 236 236" aria-hidden="true">
      <rect x="205" y="138" width="169" height="169" fill={tinta} />
      <rect x="138" y="205" width="169" height="169" fill="var(--logo-oro)" />
      <rect x="205" y="205" width="102" height="102" fill={hueco} />
    </svg>
  );
}

export function MarcaConNombre({
  tamano = 26,
  tinta,
  hueco,
}: {
  tamano?: number;
  tinta?: string;
  hueco?: string;
}) {
  return (
    <span className="brand">
      <Marca tamano={tamano} tinta={tinta} hueco={hueco} />
      <span>
        <span className="brand-name" style={{ display: "block" }}>
          LaLonja
        </span>
        <span className="brand-sub" style={{ display: "block" }}>
          TRADING
        </span>
      </span>
    </span>
  );
}
