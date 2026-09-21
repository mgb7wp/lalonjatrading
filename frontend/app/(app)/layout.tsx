// El armazon de la aplicacion.
//
// ## Se adapta a si hay sesion, y no es un capricho
//
// El diseno dibuja la barra lateral con el correo y el plan de quien ha entrado.
// Pero `/valores/ACS.MC` y `/rankings` son publicas hoy —se pueden compartir y
// las indexa un buscador— y quitarles eso seria una perdida que el diseno no
// pide. Asi que con sesion se pinta la barra lateral del diseno, y sin ella una
// cabecera publica estrecha con los mismos tokens.

import Link from "next/link";
import type { ReactNode } from "react";

import { BarraLateral } from "@/components/armazon";
import { MarcaConNombre } from "@/components/marca";
import { usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

const AVISO =
  "Información y análisis de carácter general. No es asesoramiento financiero ni una recomendación personalizada: no tiene en cuenta la situación ni los objetivos de quien lo consulta. Rentabilidades pasadas no garantizan rentabilidades futuras. Los datos proceden de fuentes públicas gratuitas y pueden contener errores u omisiones.";

function Aviso() {
  return (
    <footer
      style={{
        padding: "28px",
        borderTop: "1px solid var(--borde)",
        color: "var(--tinta-4)",
        fontSize: 12,
        lineHeight: 1.7,
        maxWidth: "110ch",
      }}
    >
      {AVISO}
    </footer>
  );
}

export default async function LayoutApp({ children }: { children: ReactNode }) {
  const usuario = await usuarioActual();

  if (!usuario) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
        <header
          style={{
            display: "flex",
            alignItems: "center",
            gap: 24,
            padding: "16px 28px",
            borderBottom: "1px solid var(--borde)",
          }}
        >
          <Link href="/" style={{ color: "inherit" }}>
            <MarcaConNombre />
          </Link>
          <nav style={{ display: "flex", gap: 22, fontSize: 13 }}>
            <Link href="/rankings" style={{ color: "var(--tinta-2)" }}>
              Rankings
            </Link>
            <Link href="/screener" style={{ color: "var(--tinta-2)" }}>
              Descubrir
            </Link>
            <Link href="/buscar" style={{ color: "var(--tinta-2)" }}>
              Buscar
            </Link>
          </nav>
          <div style={{ flex: 1 }} />
          <Link
            href="/entrar"
            style={{
              background: "var(--oro)",
              color: "var(--fondo)",
              borderRadius: "var(--radio)",
              padding: "9px 16px",
              fontSize: 13,
              fontWeight: 700,
            }}
          >
            Entrar
          </Link>
        </header>
        <main style={{ flex: 1, padding: "30px 28px 60px", animation: "fadeUp .25s ease" }}>
          {children}
        </main>
        <Aviso />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", alignItems: "stretch", minHeight: "100vh" }}>
      <BarraLateral correo={usuario.email} plan={usuario.plan} />
      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div style={{ flex: 1, animation: "fadeUp .25s ease" }}>{children}</div>
        <Aviso />
      </main>
    </div>
  );
}
