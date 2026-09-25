// Raiz: fuentes y nada mas.
//
// La cabecera y el pie NO viven aqui. El diseno tiene dos armazones muy
// distintos —la portada publica con su cabecera ancha, y la aplicacion con su
// barra lateral— y meter un tercero comun aqui obligaria a cada pagina a
// deshacerlo.

import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./fuentes.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "LaLonja Trading",
  description:
    "Análisis cuantitativo de mercados sobre un motor determinista y reproducible.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
