// Raiz: fuentes y nada mas.
//
// La cabecera y el pie NO viven aqui. El diseno tiene dos armazones muy
// distintos —la portada publica con su cabecera ancha, y la aplicacion con su
// barra lateral— y meter un tercero comun aqui obligaria a cada pagina a
// deshacerlo.

import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "LaLonja Trading",
  description:
    "Análisis cuantitativo de mercados sobre un motor determinista y reproducible.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* Las dos familias del diseno: Sora para el texto y IBM Plex Mono para
            toda cifra. `display=swap` para que el texto se lea mientras cargan
            en lugar de dejar la pagina en blanco. */}
        <link
          href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
