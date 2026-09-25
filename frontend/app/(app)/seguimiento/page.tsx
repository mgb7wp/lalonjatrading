import Link from "next/link";

import { Cabecera } from "@/components/armazon";
import { redirect } from "next/navigation";

import { anadirASeguimiento, borrarLista, crearLista, quitarDeSeguimiento } from "@/app/acciones";
import { BotonAccion, Formulario } from "@/components/formularios";
import { InsigniaSenal, Medidor, numero } from "@/components/piezas";
import type { Lista, ListaResumen } from "@/lib/api";
import { apiSesion, usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

export const metadata = { title: "Seguimiento · La Lonja" };

/** Variacion con signo explicito.
 *
 * `null` NO se pinta como 0: un cero afirma "no se movio", que es una
 * afirmacion sobre datos que no existen. Se pinta la raya y el motivo va en el
 * `title`, que es donde alguien lo busca cuando le extrana el hueco.
 */
function Variacion({
  valor,
  motivo,
  sufijo = "",
  decimales = 2,
}: {
  valor: number | null;
  motivo?: string;
  sufijo?: string;
  decimales?: number;
}) {
  if (valor === null) {
    return (
      <span className="apunte" title={motivo ?? "no se puede calcular"}>
        —
      </span>
    );
  }
  const clase = valor > 0 ? "sube" : valor < 0 ? "baja" : "";
  return (
    <span className={clase}>
      {valor > 0 ? "+" : ""}
      {numero(valor, decimales)}
      {sufijo}
    </span>
  );
}

export default async function Seguimiento({
  searchParams,
}: {
  searchParams: Promise<{ lista?: string; orden?: string }>;
}) {
  const { lista: pedida, orden = "score" } = await searchParams;
  if (!(await usuarioActual())) redirect("/entrar?desde=/seguimiento");

  let listas: ListaResumen[] = [];
  let fallo: string | null = null;
  try {
    listas = await apiSesion<ListaResumen[]>("/watchlists");
  } catch (e) {
    fallo = e instanceof Error ? e.message : "no se han podido leer las listas";
  }

  const elegida = listas.find((l) => String(l.id) === pedida) ?? listas[0];
  let detalle: Lista | null = null;
  if (elegida) {
    try {
      detalle = await apiSesion<Lista>(
        `/watchlists/${elegida.id}?orden=${encodeURIComponent(orden)}`,
      );
    } catch {
      detalle = null;
    }
  }

  return (
    <>
      <Cabecera miga="Seguimiento" />
      <div className="pagina">
      <h1>Seguimiento</h1>

      {fallo ? <p className="bloque-falta">No disponible. {fallo}</p> : null}

      {listas.length > 1 ? (
        <nav className="nav" style={{ marginBottom: 16 }}>
          {listas.map((l) => (
            <Link
              key={l.id}
              href={`/seguimiento?lista=${l.id}`}
              style={l.id === elegida?.id ? { fontWeight: 700 } : undefined}
            >
              {l.nombre} ({l.valores})
            </Link>
          ))}
        </nav>
      ) : null}

      {listas.length === 0 ? (
        <section>
          <h2>Crear una lista</h2>
          <Formulario accion={crearLista} etiquetaBoton="Crear">
            <label>
              Nombre
              <input type="text" name="nombre" defaultValue="Seguimiento" maxLength={120} />
            </label>
          </Formulario>
        </section>
      ) : null}

      {elegida ? (
        <>
          <section>
            <h2>Añadir un valor</h2>
            <Formulario accion={anadirASeguimiento} etiquetaBoton="Añadir">
              <input type="hidden" name="lista" value={elegida.id} />
              <label>
                Ticker
                <input type="text" name="ticker" required placeholder="AAPL" />
              </label>
            </Formulario>
            <p className="apunte">
              ¿No sabes el ticker? <Link href="/buscar">Búscalo por nombre</Link>.
            </p>
          </section>

          {detalle === null ? (
            <p className="bloque-falta">No disponible. La lista no ha respondido.</p>
          ) : detalle.n === 0 ? (
            <p className="vacio">La lista está vacía.</p>
          ) : (
            <section>
              <h2>
                {detalle.nombre}
                <span className="frescura">
                  {" "}
                  a {detalle.fecha} · variaciones a {detalle.dias_variacion} días
                </span>
              </h2>

              <nav className="nav" style={{ marginBottom: 10 }}>
                {[
                  ["score", "Por score"],
                  ["variacion_score", "Por variación de score"],
                  ["variacion_precio", "Por variación de precio"],
                  ["ticker", "Por ticker"],
                ].map(([clave, texto]) => (
                  <Link
                    key={clave}
                    href={`/seguimiento?lista=${elegida.id}&orden=${clave}`}
                    style={orden === clave ? { fontWeight: 700 } : undefined}
                  >
                    {texto}
                  </Link>
                ))}
              </nav>

              <div className="desliza">
                <table>
                  <thead>
                    <tr>
                      <th>Valor</th>
                      <th>Score</th>
                      <th className="num">Δ score</th>
                      <th className="num">Precio</th>
                      <th className="num">Δ precio</th>
                      <th>Señal</th>
                      <th className="num">Probabilidad</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {detalle.valores.map((f) => (
                      <tr key={f.ticker}>
                        <td>
                          <Link href={`/valores/${encodeURIComponent(f.ticker)}`}>{f.ticker}</Link>
                          <div className="apunte">{f.nombre}</div>
                        </td>
                        <td>
                          {f.score === null ? (
                            <span className="apunte" title={f.motivos.score}>
                              sin puntuar
                            </span>
                          ) : (
                            <Medidor valor={f.score} />
                          )}
                        </td>
                        <td className="num">
                          <Variacion valor={f.variacion_score} motivo={f.motivos.variacion_score} />
                        </td>
                        <td className="num">{numero(f.precio)}</td>
                        <td className="num">
                          <Variacion
                            valor={f.variacion_precio}
                            motivo={f.motivos.variacion_precio}
                            sufijo=" %"
                          />
                        </td>
                        <td>
                          {f.senal ? (
                            <InsigniaSenal senal={f.senal} />
                          ) : (
                            <span className="apunte" title={f.motivos.senal}>
                              —
                            </span>
                          )}
                        </td>
                        <td className="num">
                          {/* La columna de §35 existe; el dato está bloqueado por
                              D-7. Se dice, en lugar de dejar un hueco que obliga
                              a adivinar si falta o si algo se ha roto. */}
                          <span className="apunte" title={f.motivos.probabilidad}>
                            no disponible
                          </span>
                        </td>
                        <td>
                          <BotonAccion
                            accion={quitarDeSeguimiento}
                            campos={{ lista: elegida.id, ticker: f.ticker }}
                          >
                            Quitar
                          </BotonAccion>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="apunte">
                La probabilidad de subida no se publica todavía: necesita el modelo
                estadístico, que está bloqueado hasta tener un universo y un histórico
                suficientes. Preferimos dejar la columna vacía y decirlo a llenarla con
                un número que no significaría nada.
              </p>
            </section>
          )}

          {/* <div> y no <p>: el HTML no permite un <form> dentro de un <p>
              (ver la nota de la página de cartera). */}
          <div className="apunte" style={{ marginTop: 28 }}>
            <BotonAccion
              accion={borrarLista}
              campos={{ id: elegida.id }}
              confirmar="¿Borrar esta lista entera?"
            >
              Borrar esta lista
            </BotonAccion>
          </div>
        </>
      ) : null}
      </div>
    </>
  );
}
