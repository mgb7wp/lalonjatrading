import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "La Lonja",
  description: "Análisis cuantitativo de mercados",
};

// Sin diseño a propósito (§39 del encargo): la FASE 2 de UX/UI llega cuando el
// motor esté asentado. Lo único que no se pospone es el aviso legal, porque de
// eso depende cómo se presenta el producto, no cómo se ve.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0, padding: 24 }}>
        <header style={{ borderBottom: "1px solid #ddd", paddingBottom: 12 }}>
          <strong>La Lonja</strong> — análisis cuantitativo de mercados
        </header>
        <main style={{ paddingTop: 24 }}>{children}</main>
        <footer
          style={{
            marginTop: 48,
            borderTop: "1px solid #ddd",
            paddingTop: 12,
            fontSize: 13,
            color: "#555",
          }}
        >
          Información y análisis de carácter general. <strong>No es asesoramiento
          financiero</strong> ni una recomendación personalizada: no tiene en cuenta
          la situación ni los objetivos de quien lo consulta. Rentabilidades pasadas
          no garantizan rentabilidades futuras.
        </footer>
      </body>
    </html>
  );
}
