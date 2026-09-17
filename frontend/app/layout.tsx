import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "La Lonja — análisis cuantitativo de mercados",
  description:
    "Rankings, screener y análisis por valor sobre un motor determinista y reproducible.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>
        <header className="cabecera">
          <div className="envoltorio cabecera-fila">
            <Link href="/" className="marca">
              La Lonja <span>· análisis cuantitativo</span>
            </Link>
            <nav className="nav">
              <Link href="/">Panel</Link>
              <Link href="/rankings">Rankings</Link>
              <Link href="/screener">Screener</Link>
            </nav>
          </div>
        </header>

        <main className="envoltorio">{children}</main>

        {/* §44. No es letra pequeña de relleno: determina cómo se puede
            presentar el producto, y por eso está en todas las páginas y no
            escondido en un enlace. */}
        <footer className="envoltorio aviso-legal">
          Información y análisis de carácter general. <strong>No es asesoramiento
          financiero</strong> ni una recomendación personalizada: no tiene en cuenta
          la situación ni los objetivos de quien lo consulta. Rentabilidades pasadas
          no garantizan rentabilidades futuras. Los datos proceden de fuentes
          públicas gratuitas y pueden contener errores u omisiones.
        </footer>
      </body>
    </html>
  );
}
