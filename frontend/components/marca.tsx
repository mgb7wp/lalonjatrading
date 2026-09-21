/** La marca de LaLonja Trading.
 *
 * Dos cuadrados iguales desplazados en diagonal, con el solape vaciado al
 * fondo. La geometria esta medida sobre el original de 512 px —cuadrados de
 * 169, desplazamiento de 67, solape de 102— en lugar de aproximarla a ojo.
 *
 * El `viewBox` recorta al DIBUJO (138,138 y 236 de lado) y no al lienzo
 * completo. El original trae un margen de seguridad generoso alrededor, que un
 * icono de aplicacion necesita y una marca en linea no: con el lienzo entero,
 * a 22 px el dibujo se quedaba en diez y no se reconocia. El icono de la
 * pestania (`app/icon.svg`) si conserva ese margen, porque alli hace falta.
 *
 * El vaciado del solape va en `var(--fondo)` y no en un gris fijo: asi sigue
 * siendo un hueco de verdad si algun dia cambia el fondo de la aplicacion.
 *
 * Antes aqui habia otra cosa: unas eles entrelazadas que venian del prototipo
 * del diseno y que no eran el logotipo real.
 */
export function Marca({ tamano = 22 }: { tamano?: number }) {
  return (
    <svg width={tamano} height={tamano} viewBox="138 138 236 236" aria-hidden="true">
      <rect x="205" y="138" width="169" height="169" fill="#F5F5F5" />
      <rect x="138" y="205" width="169" height="169" fill="#F0B90B" />
      <rect x="205" y="205" width="102" height="102" fill="var(--fondo)" />
    </svg>
  );
}

export function MarcaConNombre({ tamano = 22 }: { tamano?: number }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <Marca tamano={tamano} />
      <span style={{ display: "flex", flexDirection: "column", lineHeight: 1 }}>
        <span style={{ fontWeight: 600, fontSize: 15, letterSpacing: "-0.01em" }}>LaLonja</span>
        <span
          className="mono"
          style={{ fontSize: 9, letterSpacing: "0.24em", color: "var(--tinta-3)", marginTop: 4 }}
        >
          TRADING
        </span>
      </span>
    </span>
  );
}
