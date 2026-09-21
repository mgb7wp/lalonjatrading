"use client";

// El armazon de la aplicacion: barra lateral y cabecera.
//
// Es cliente porque marca el destino activo, y para eso hace falta la ruta. Todo
// lo demas de la aplicacion sigue siendo servidor: aqui no se lee ni un dato ni
// se toca el token de sesion.
//
// ## Dos destinos del diseno no existen todavia
//
// `AI Analyst` es la FASE 16 y `Settings` no esta construida. Aparecen en la
// barra —quitarlos cambiaria el diseno— pero se marcan como PRONTO y no navegan
// a ningun sitio. Un enlace que lleva a una pagina en blanco es peor que uno que
// dice que aun no esta.

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { MarcaConNombre } from "./marca";

type Destino = {
  href: string;
  etiqueta: string;
  icono: ReactNode;
  insignia?: string;
  pronto?: boolean;
};

/** Iconos del diseno, que los declara como glifos de una fuente monoespaciada.
 * Se copian tal cual en lugar de sustituirlos por una libreria: cambiarlos
 * cambiaria el diseno. */
const GLIFOS = {
  panel: "▤",
  mercados: "◎",
  descubrir: "◈",
  seguimiento: "◇",
  cartera: "◐",
  ia: "✦",
  ajustes: "⚙",
  buscar: "▭",
} as const;

const PLATAFORMA: Destino[] = [
  { href: "/panel", etiqueta: "Panel", icono: GLIFOS.panel },
  { href: "/mercados", etiqueta: "Mercados", icono: GLIFOS.mercados },
  { href: "/screener", etiqueta: "Descubrir", icono: GLIFOS.descubrir },
  { href: "/seguimiento", etiqueta: "Seguimiento", icono: GLIFOS.seguimiento },
  { href: "/cartera", etiqueta: "Cartera", icono: GLIFOS.cartera },
  { href: "/ia", etiqueta: "Analista IA", icono: GLIFOS.ia, pronto: true },
];

const SECUNDARIOS: Destino[] = [
  { href: "/buscar", etiqueta: "Buscar", icono: GLIFOS.buscar },
  { href: "/ajustes", etiqueta: "Ajustes", icono: GLIFOS.ajustes, pronto: true },
];

function estiloDestino(activo: boolean) {
  return {
    display: "flex",
    alignItems: "center",
    gap: 10,
    width: "100%",
    background: activo ? "var(--oro)" : "transparent",
    border: "none",
    borderRadius: "var(--radio)",
    padding: "9px 10px",
    fontSize: 13,
    fontWeight: activo ? 700 : 400,
    color: activo ? "var(--fondo)" : "var(--tinta-2)",
    textDecoration: "none",
  } as const;
}

function Entrada({ destino, activo }: { destino: Destino; activo: boolean }) {
  const contenido = (
    <>
      <span style={{ display: "inline-flex", width: 16, justifyContent: "center" }} aria-hidden>
        {destino.icono}
      </span>
      <span style={{ flex: 1, textAlign: "left" }}>{destino.etiqueta}</span>
      {destino.pronto ? (
        <span className="mono" style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--tinta-4)" }}>
          PRONTO
        </span>
      ) : destino.insignia ? (
        <span className="mono" style={{ fontSize: 10, color: "var(--oro)" }}>
          {destino.insignia}
        </span>
      ) : null}
    </>
  );

  if (destino.pronto) {
    // Un <span> y no un <a> deshabilitado: un enlace sin destino sigue
    // apareciendo en la navegacion por teclado y promete algo que no cumple.
    return (
      <span style={{ ...estiloDestino(false), color: "var(--tinta-4)", cursor: "default" }}>
        {contenido}
      </span>
    );
  }
  return (
    <Link href={destino.href} style={estiloDestino(activo)} aria-current={activo ? "page" : undefined}>
      {contenido}
    </Link>
  );
}

function esActivo(ruta: string, href: string) {
  return ruta === href || ruta.startsWith(`${href}/`);
}

export function BarraLateral({ correo, plan }: { correo: string; plan: string }) {
  const ruta = usePathname();
  const iniciales = correo.slice(0, 2).toUpperCase();

  return (
    <aside
      style={{
        width: 236,
        flex: "0 0 236px",
        background: "var(--fondo)",
        borderRight: "1px solid var(--borde)",
        padding: "22px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 26,
        position: "sticky",
        top: 0,
        height: "100vh",
      }}
    >
      <div style={{ padding: "0 8px" }}>
        <Link href="/panel" style={{ color: "inherit" }}>
          <MarcaConNombre />
        </Link>
      </div>

      <Link
        href="/buscar"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          background: "var(--superficie)",
          border: "1px solid var(--borde-2)",
          borderRadius: "var(--radio)",
          padding: "9px 10px",
          color: "var(--tinta-3)",
          fontSize: 13,
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
          <circle cx="7" cy="7" r="4.5" />
          <path d="M10.5 10.5 L14 14" />
        </svg>
        <span style={{ flex: 1 }}>Buscar</span>
      </Link>

      <nav style={{ display: "flex", flexDirection: "column", gap: 2 }} aria-label="Plataforma">
        <div className="rotulo" style={{ fontSize: 9, letterSpacing: "0.18em", color: "var(--tinta-4)", padding: "0 10px 8px" }}>
          Plataforma
        </div>
        {PLATAFORMA.map((d) => (
          <Entrada key={d.href} destino={d} activo={esActivo(ruta, d.href)} />
        ))}
      </nav>

      <nav style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: "auto" }} aria-label="Cuenta">
        {SECUNDARIOS.map((d) => (
          <Entrada key={d.href} destino={d} activo={esActivo(ruta, d.href)} />
        ))}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "14px 10px 2px",
            marginTop: 10,
            borderTop: "1px solid var(--borde)",
          }}
        >
          <span
            className="mono"
            style={{
              width: 26,
              height: 26,
              borderRadius: "50%",
              background: "var(--borde-2)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 10,
            }}
            aria-hidden
          >
            {iniciales}
          </span>
          <span style={{ flex: 1, minWidth: 0 }}>
            <span
              style={{
                display: "block",
                fontSize: 12,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={correo}
            >
              {correo}
            </span>
            <span className="mono" style={{ fontSize: 9, letterSpacing: "0.1em", color: "var(--tinta-3)" }}>
              {plan.toUpperCase()}
            </span>
          </span>
        </div>
      </nav>
    </aside>
  );
}

/** La cabecera: miga de pan, estado del mercado y la accion de la IA.
 *
 * El punto de "mercado abierto" del diseno NO se pinta aqui: saber si un mercado
 * esta abierto exige su calendario y su huso, y el dato existe en el backend
 * pero no se sirve todavia. Un punto verde fijo seria decorar con una
 * afirmacion que no hemos comprobado. */
export function Cabecera({ miga, accion }: { miga: string; accion?: ReactNode }) {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "16px 28px",
        borderBottom: "1px solid var(--borde)",
        position: "sticky",
        top: 0,
        background: "rgba(11,14,17,.92)",
        backdropFilter: "blur(8px)",
        zIndex: 20,
      }}
    >
      <div className="rotulo">{miga}</div>
      <div style={{ flex: 1 }} />
      {accion}
    </header>
  );
}
