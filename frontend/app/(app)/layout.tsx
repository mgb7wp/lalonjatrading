// El armazon de la aplicacion (v2).
//
// Cabecera con la marca, la busqueda (atajo «/») y la fecha de la vista; franja
// con la frescura de precios de cada mercado; barra lateral agrupada; aviso
// legal fijo al pie. En movil, la barra lateral pasa a una barra inferior.
//
// ## Con y sin sesion
//
// `/valores/ACS.MC` y `/rankings` son publicas —se pueden compartir y las
// indexa un buscador—, asi que el armazon es el mismo con y sin sesion. Sin
// ella no aparecen «Mis datos» ni «Operar», y arriba sale «Entrar».
//
// ## Consulta pasada
//
// Con `?fecha=` la cabecera se invierte a oscuro y aparece una franja rayada
// con «Volver a hoy»: una vista del 31 de marzo tiene que distinguirse de la de
// hoy de un vistazo, no leyendo una etiqueta.

import type { ReactNode } from "react";

import { salir } from "@/app/acciones";
import { BarraInferior, BarraLateral } from "@/components/armazon";
import { AtajoBusqueda } from "@/components/atajo-busqueda";
import { AvisoLegal } from "@/components/aviso-legal";
import { MarcaConNombre } from "@/components/marca";
import { api, frescuraPorMercado, intenta, type Market, type SaludDatos } from "@/lib/api";
import { fechaConsulta } from "@/lib/consulta";
import { conFecha, fmtFecha, hoyMadrid } from "@/lib/fecha";
import { usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

const PERSONAL = ["1", "true", "yes", "si"].includes((process.env.PERSONALIZATION_ENABLED ?? "").toLowerCase());

export default async function LayoutApp({ children }: { children: ReactNode }) {
  const fecha = fechaConsulta();
  const [usuario, mercados, salud] = await Promise.all([
    usuarioActual(),
    intenta(api<Market[]>("/markets")),
    intenta(api<SaludDatos>("/health/data")),
  ]);
  const dentro = usuario !== null;
  const pasado = fecha !== null;
  const precios = frescuraPorMercado(salud, "precios");
  const hoy = hoyMadrid();

  return (
    <div className="grid-canvas">
      <header className={`topbar${pasado ? " is-past" : ""}`}>
        <div className="brand-cell">
          <a href={conFecha("/panel", fecha)} aria-label="LaLonja Trading, panel" style={{ color: "inherit", textDecoration: "none" }}>
            <MarcaConNombre
              tamano={26}
              tinta={pasado ? "var(--papel)" : "var(--tinta-oscura)"}
              hueco={pasado ? "var(--tinta-oscura)" : "var(--fondo)"}
            />
          </a>
        </div>
        <div className="topbar-search desk-only">
          <form action="/buscar" method="get" role="search" className="searchbox">
            <span className="mono" aria-hidden="true">
              ⌕
            </span>
            <label htmlFor="q-cabecera" className="visually-hidden">
              Buscar por ticker, nombre o ISIN
            </label>
            <input id="q-cabecera" name="q" type="search" placeholder="Ticker, nombre o ISIN" autoComplete="off" />
            {fecha ? <input type="hidden" name="fecha" value={fecha} /> : null}
            <kbd aria-hidden="true">/</kbd>
          </form>
          <AtajoBusqueda inputId="q-cabecera" />
        </div>
        <div className="topbar-right">
          {/* La fecha de la vista, y desde ahi la consulta de otra fecha. Un
              <details> con un formulario GET: funciona sin JavaScript. */}
          <details className="date-pick">
            <summary className="date-chip" title={pasado ? "Consulta de fecha pasada" : "Fecha de la vista"}>
              {pasado ? `◷ ${fmtFecha(fecha).toUpperCase()}` : `HOY · ${fmtFecha(hoy).toUpperCase()}`}
            </summary>
            <form method="get" className="date-pick-form">
              <label htmlFor="fecha-consulta">Consultar cómo estaba el</label>
              <input id="fecha-consulta" type="date" name="fecha" max={hoy} defaultValue={fecha ?? ""} required />
              <button type="submit" className="btn btn-secondary">
                Consultar
              </button>
            </form>
          </details>
          {usuario ? (
            <form action={salir} className="desk-only">
              <button type="submit" className="user-chip" title={`${usuario.email} · salir`}>
                <span aria-hidden="true">{usuario.email.slice(0, 2).toUpperCase()}</span>
                <span className="visually-hidden">Salir de {usuario.email}</span>
              </button>
            </form>
          ) : (
            <a className="btn btn-secondary" href="/entrar">
              Entrar
            </a>
          )}
        </div>
      </header>

      {pasado ? (
        <div role="status" className="past-banner">
          <span className="past-tag">◷ CONSULTA PASADA · {fmtFecha(fecha).toUpperCase()}</span>
          <span className="past-text">Datos tal como estaban ese día. Nada de esta vista es de hoy.</span>
          <a className="btn btn-secondary btn-paper" href="?">
            Volver a hoy
          </a>
        </div>
      ) : null}

      {/* La frescura es de HOY: en una consulta pasada no se ensena, porque esa
          vista promete que nada de lo que se ve es de hoy. */}
      {pasado ? null : (
      <nav className="tape" aria-label="Frescura de precios por mercado">
        {mercados && mercados.length > 0 ? (
          mercados.map((m) => {
            const f = precios.get(m.id);
            const tarde = !f || f.is_stale;
            const texto = !f
              ? "sin precios cargados"
              : f.is_stale
                ? `retraso · ${f.days_behind ?? "?"} d · ${fmtFecha(f.last_data_date, false)}`
                : `al día · ${fmtFecha(f.last_data_date, false)}`;
            return (
              <a key={m.id} href={conFecha("/mercados", fecha)} className={tarde ? "is-late" : undefined} title={`${m.name}: ${texto}`}>
                <strong>{m.id.toUpperCase()}</strong>
                <span aria-hidden="true">{!f ? "⊘" : f.is_stale ? "◷" : "✓"}</span>
                <span className="tape-txt">{texto}</span>
                <span className="visually-hidden mob-only">{texto}</span>
              </a>
            );
          })
        ) : (
          <span className="tape-none">⊘ Frescura por mercado no disponible: la API no ha respondido.</span>
        )}
      </nav>
      )}

      <div className="app-body">
        <BarraLateral dentro={dentro} personal={PERSONAL} fecha={fecha} />
        <div className="main">
          <main className="app-main">{children}</main>
          <AvisoLegal />
        </div>
      </div>

      <BarraInferior dentro={dentro} personal={PERSONAL} fecha={fecha} />
    </div>
  );
}
