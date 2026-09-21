/** La marca: el logotipo del diseno y el nombre en dos lineas.
 *
 * El trazo del logotipo se copia tal cual del diseno (dos eles entrelazadas que
 * forman una lonja) en lugar de redibujarlo a ojo. */
export function Marca({ tamano = 22 }: { tamano?: number }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M2 2 H8 V16 H22 V22 H2 Z" fill="var(--oro)" />
      <path d="M22 22 H16 V8 H2 V2 H22 Z" fill="var(--oro)" />
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
