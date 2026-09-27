"use client";

// El armazon de la aplicacion (v2): barra lateral agrupada y barra inferior movil.
//
// Es cliente solo porque marca el destino activo, y para eso hace falta la ruta.
// Se renderiza en el servidor con la ruta ya resuelta, asi que el estado activo
// se ve aunque el JavaScript no haya cargado. Aqui no se lee ni un dato ni se
// toca el token de sesion.
//
// ## Destinos que aun no existen
//
// Analista IA, Hoja de ordenes, Alertas, Estado de los datos y Ajustes estan en
// el diseno pero no tienen backend todavia. Aparecen —quitarlos cambiaria el
// diseno— marcados PRONTO y sin enlace: un enlace a una pagina en blanco es peor
// que uno que dice que aun no esta.
//
// ## Operar solo con uso personal
//
// El grupo OPERAR es lo personalizado («que compras o vendes TU»). Solo se
// pinta si `PERSONALIZATION_ENABLED` esta activo (D-6), y va en un marco rayado
// con la etiqueta PERSONAL para que no se confunda con el analisis general.

import { usePathname } from "next/navigation";

import { conFecha } from "@/lib/fecha";

type Destino = { href: string; etiqueta: string; corta?: string; pronto?: boolean; activoEn?: string[] };
type Grupo = { titulo: string; personal?: boolean; sesion?: boolean; destinos: Destino[] };

const GRUPOS: Grupo[] = [
  {
    titulo: "ANALIZAR",
    destinos: [
      { href: "/panel", etiqueta: "Panel" },
      { href: "/mercados", etiqueta: "Mercados" },
      { href: "/rankings", etiqueta: "Descubrir", activoEn: ["/rankings", "/screener"] },
      { href: "/ia", etiqueta: "Analista IA", pronto: true },
      { href: "/buscar", etiqueta: "Buscar" },
    ],
  },
  {
    titulo: "MIS DATOS",
    sesion: true,
    destinos: [
      { href: "/seguimiento", etiqueta: "Seguimiento", corta: "Seguim." },
      { href: "/cartera", etiqueta: "Cartera" },
    ],
  },
  {
    titulo: "OPERAR",
    personal: true,
    sesion: true,
    destinos: [
      { href: "/hoja", etiqueta: "Hoja de órdenes", pronto: true },
      { href: "/alertas", etiqueta: "Alertas", pronto: true },
    ],
  },
  {
    titulo: "SISTEMA",
    destinos: [
      { href: "/datos", etiqueta: "Estado de datos", pronto: true },
      { href: "/ajustes", etiqueta: "Ajustes", pronto: true },
    ],
  },
];

const BARRA_MOVIL = ["/panel", "/rankings", "/seguimiento", "/cartera", "/mercados"];

function useDestinos(dentro: boolean, personal: boolean) {
  const ruta = usePathname();
  let n = 0;
  const grupos = GRUPOS.filter((g) => (dentro || !g.sesion) && (personal || !g.personal)).map((g) => ({
    ...g,
    destinos: g.destinos.map((d) => ({
      ...d,
      n: String(++n).padStart(2, "0"),
      personal: !!g.personal,
      activo: (d.activoEn ?? [d.href]).some((h) => ruta === h || ruta.startsWith(`${h}/`)),
    })),
  }));
  return { grupos, todos: grupos.flatMap((g) => g.destinos) };
}

function Pronto() {
  return (
    <span className="mono" style={{ fontSize: 9, letterSpacing: "0.1em", opacity: 0.75 }}>
      PRONTO
    </span>
  );
}

export function BarraLateral({ dentro, personal, fecha }: { dentro: boolean; personal: boolean; fecha: string | null }) {
  const { grupos } = useDestinos(dentro, personal);
  return (
    <aside className="sidebar">
      <nav aria-label="Principal" style={{ display: "contents" }}>
        {grupos.map((g) => (
          <div key={g.titulo} className={`nav-group${g.personal ? " is-personal" : ""}`}>
            <div className="nav-group-title">
              <span>{g.titulo}</span>
              {g.personal ? <span className="personal-mark">PERSONAL</span> : null}
            </div>
            {g.destinos.map((d) =>
              d.pronto ? (
                // Un <span> y no un <a> deshabilitado: un enlace sin destino sigue
                // apareciendo en la navegacion por teclado y promete algo que no cumple.
                <span key={d.href} className="nav-link is-pronto">
                  <span className="nav-i" aria-hidden="true">
                    {d.n}
                  </span>
                  <span style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
                    {d.etiqueta}
                    <Pronto />
                  </span>
                </span>
              ) : (
                <a key={d.href} href={conFecha(d.href, fecha)} className="nav-link" aria-current={d.activo ? "page" : undefined}>
                  <span className="nav-i" aria-hidden="true">
                    {d.n}
                  </span>
                  {d.etiqueta}
                </a>
              ),
            )}
          </div>
        ))}
      </nav>
    </aside>
  );
}

/** Barra inferior movil: cuatro destinos y «Más», que es un <details> y abre sin JavaScript. */
export function BarraInferior({ dentro, personal, fecha }: { dentro: boolean; personal: boolean; fecha: string | null }) {
  const { todos } = useDestinos(dentro, personal);
  const barra = todos.filter((d) => BARRA_MOVIL.includes(d.href)).slice(0, 4);
  const mas = todos.filter((d) => !barra.includes(d));
  return (
    <nav className="mob-nav" aria-label="Principal">
      <div className="mob-nav-bar" style={{ gridTemplateColumns: `repeat(${barra.length + 1}, 1fr)` }}>
        {barra.map((d) => (
          <a key={d.href} href={conFecha(d.href, fecha)} className="mob-nav-link" aria-current={d.activo ? "page" : undefined}>
            <span className="nav-i" aria-hidden="true">
              {d.n}
            </span>
            {d.corta ?? d.etiqueta}
          </a>
        ))}
        <details className="mob-more">
          <summary>
            <span className="nav-i" aria-hidden="true">
              ··
            </span>
            <span className="when-closed">Más</span>
            <span className="when-open">Cerrar</span>
          </summary>
          <div className="mob-more-list">
            {mas.map((d) =>
              d.pronto ? (
                <span key={d.href} className="is-pronto">
                  <span className="nav-i" aria-hidden="true">
                    {d.n}
                  </span>
                  {d.etiqueta}
                  <Pronto />
                </span>
              ) : (
                <a key={d.href} href={conFecha(d.href, fecha)} aria-current={d.activo ? "page" : undefined}>
                  <span className="nav-i" aria-hidden="true">
                    {d.n}
                  </span>
                  {d.etiqueta}
                  {d.personal ? <span className="personal-mark">PERSONAL</span> : <span />}
                </a>
              ),
            )}
          </div>
        </details>
      </div>
    </nav>
  );
}
