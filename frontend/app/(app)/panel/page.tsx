// El panel. Implementa la pantalla `dashboard` del diseno.
//
// ## Lo que el diseno pide y lo que hay
//
// El diseno lo dibuja para un usuario con sesion: saludo, resumen escrito por la
// IA, KPIs de su cartera, su watchlist y noticias. Aqui:
//
// - Con sesion, los KPIs y la watchlist son SUYOS, de la API.
// - Sin sesion se pinta la misma rejilla con el estado del universo, que es lo
//   que si se puede saber de alguien que no ha entrado.
// - El "RESUMEN LALONJA" es la FASE 16. Su bloque se queda, con el motivo
//   escrito: rellenarlo con un parrafo de ejemplo seria exactamente lo que el
//   producto promete no hacer.
// - "Noticias que mueven tu radar" no tiene fuente y no la va a tener gratis.
//   Mismo tratamiento.

import Link from "next/link";

import { Cabecera } from "@/components/armazon";
import { Medidor, Panel, PildoraScore, Tarjeta, Variacion } from "@/components/piezas";
import { api, intenta, type Health, type Market, type RespuestaRanking } from "@/lib/api";
import { apiSesion, usuarioActual } from "@/lib/sesion";
import type { CarteraResumen, Lista, ListaResumen, Valoracion } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata = { title: "Panel · LaLonja" };

const MOTIVO_IA =
  "El resumen lo redacta la capa de IA sobre los scores ya calculados, y esa capa todavía no está construida. Nunca producirá un número: solo explica los que ya existen.";

const MOTIVO_NOTICIAS =
  "No hay ninguna fuente de noticias gratuita con licencia para reproducirlas a escala, así que el pilar de sentimiento se declara no disponible y su peso se reparte entre los demás. No es un olvido: está en el registro de fuentes.";

function Rejilla({ children, columnas = "repeat(auto-fit,minmax(200px,1fr))" }: { children: React.ReactNode; columnas?: string }) {
  return <div style={{ display: "grid", gridTemplateColumns: columnas, gap: 14 }}>{children}</div>;
}

function Seccion({ children }: { children: React.ReactNode }) {
  return <section style={{ marginBottom: 28 }}>{children}</section>;
}

export default async function PanelPagina() {
  const usuario = await usuarioActual();
  const hoy = new Date().toLocaleDateString("es-ES", {
    weekday: "long",
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  const [salud, mercados, mejores, subidas, caidas] = await Promise.all([
    intenta(api<Health>("/health")),
    intenta(api<Market[]>("/markets")),
    intenta(api<RespuestaRanking>("/rankings?tipo=mejor_score&n=6")),
    intenta(api<RespuestaRanking>("/rankings?tipo=mas_mejorado&n=4")),
    intenta(api<RespuestaRanking>("/rankings?tipo=mayor_caida&n=4")),
  ]);

  // Lo del usuario, solo si ha entrado. Un fallo aqui no puede tumbar el panel.
  const carteras = usuario ? await intenta(apiSesion<CarteraResumen[]>("/portfolios")) : null;
  const listas = usuario ? await intenta(apiSesion<ListaResumen[]>("/watchlists")) : null;
  const cartera =
    carteras && carteras.length
      ? await intenta(apiSesion<Valoracion>(`/portfolios/${carteras[0].id}`))
      : null;
  const lista =
    listas && listas.length ? await intenta(apiSesion<Lista>(`/watchlists/${listas[0].id}`)) : null;

  const nValores = mercados?.reduce((t, m) => t + m.securities, 0) ?? null;

  return (
    <>
      {usuario ? <Cabecera miga="Panel" /> : null}

      <div style={{ padding: "30px 28px 60px" }}>
        <Seccion>
          <div className="rotulo">{hoy}</div>
          <h1 style={{ fontSize: 30, margin: "10px 0 0" }}>
            {usuario ? `Buenos días, ${usuario.email.split("@")[0]}` : "Todo el mercado, ya ordenado"}
          </h1>
          <p style={{ color: "var(--tinta-3)", margin: "8px 0 0", maxWidth: "60ch" }}>
            {usuario
              ? "Esto es lo que ha cambiado en el universo desde el último cálculo."
              : "Estás viendo el panel público. Entra para seguir valores y llevar tu cartera."}
          </p>
        </Seccion>

        {/* El "RESUMEN LALONJA" del diseño, con su motivo en lugar de un párrafo
            de ejemplo. El bloque se queda para que se vea que está previsto. */}
        <Seccion>
          <div
            style={{
              background: "var(--superficie)",
              border: "1px solid var(--borde-2)",
              borderLeft: "2px solid var(--borde-vivo)",
              borderRadius: "var(--radio)",
              padding: "22px 24px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <span className="rotulo" style={{ letterSpacing: "0.18em", color: "var(--tinta-3)" }}>
                Resumen LaLonja
              </span>
              <span className="mono" style={{ fontSize: 10, color: "var(--tinta-4)" }}>
                TODAVÍA NO DISPONIBLE
              </span>
            </div>
            <p style={{ margin: 0, fontSize: 15, lineHeight: 1.65, maxWidth: "92ch", color: "var(--tinta-3)" }}>
              {MOTIVO_IA}
            </p>
          </div>
        </Seccion>

        <Seccion>
          <Rejilla>
            {cartera ? (
              <>
                <Tarjeta
                  rotulo="Valor de la cartera"
                  cifra={`${Number.parseFloat(cartera.totales.valor).toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${cartera.divisa_base}`}
                  apunte={`${cartera.diversificacion.posiciones} posiciones`}
                  acento
                />
                <Tarjeta
                  rotulo="Resultado total"
                  cifra={<Variacion valor={Number.parseFloat(cartera.totales.total)} sufijo={` ${cartera.divisa_base}`} />}
                  apunte="realizado + no realizado + dividendos − gastos"
                />
                <Tarjeta
                  rotulo="Score medio"
                  cifra={cartera.score_medio.valor?.toFixed(0) ?? "—"}
                  apunte={`ponderado, sobre el ${(cartera.score_medio.cobertura * 100).toFixed(0)} % del valor`}
                />
                <Tarjeta
                  rotulo="Posiciones efectivas"
                  cifra={cartera.diversificacion.posiciones_efectivas?.toFixed(2) ?? "—"}
                  apunte="inverso del índice de concentración"
                />
              </>
            ) : (
              <>
                <Tarjeta rotulo="Universo" cifra={nValores ?? "—"} apunte="valores en catálogo" acento />
                <Tarjeta rotulo="Mercados" cifra={mercados?.length ?? "—"} apunte="con calendario y divisa propios" />
                <Tarjeta
                  rotulo="Último cálculo"
                  cifra={<span style={{ fontSize: 18 }}>{mejores?.fecha_datos ?? "—"}</span>}
                  apunte={mejores?.modelo ? `modelo ${mejores.modelo}` : "sin scores todavía"}
                />
                <Tarjeta
                  rotulo="Motor"
                  cifra={<span style={{ fontSize: 18 }}>{salud?.estado ?? "sin respuesta"}</span>}
                  apunte={salud?.version ? `versión ${salud.version}` : null}
                />
              </>
            )}
          </Rejilla>
        </Seccion>

        <Seccion>
          <div className="dos-columnas" style={{ "--izq": "1.55fr", gap: 18 } as React.CSSProperties}>
            <Panel
              titulo={lista ? lista.nombre : "Mejor puntuados"}
              extra={
                <Link href={lista ? "/seguimiento" : "/rankings"} style={{ fontSize: 12 }}>
                  Ver todo →
                </Link>
              }
              sinRelleno
            >
              {lista && lista.n > 0 ? (
                <TablaSeguimiento lista={lista} />
              ) : mejores && mejores.puestos.length ? (
                <TablaRanking datos={mejores} />
              ) : (
                <p className="bloque-falta" style={{ margin: 18 }}>
                  No disponible. Todavía no hay scores calculados.
                </p>
              )}
            </Panel>

            <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
              <Panel titulo="Qué ha cambiado" extra={<span className="mono" style={{ fontSize: 10, color: "var(--tinta-4)" }}>30 DÍAS</span>}>
                <Cambios subidas={subidas} caidas={caidas} />
              </Panel>
            </div>
          </div>
        </Seccion>

        {/* "Noticias que mueven tu radar": el bloque del diseño, con su motivo. */}
        <Seccion>
          <h2 style={{ fontSize: 16, margin: "0 0 12px" }}>Noticias que mueven tu radar</h2>
          <p className="bloque-falta">
            <strong style={{ color: "var(--tinta-2)" }}>Todavía no disponible.</strong>{" "}
            {MOTIVO_NOTICIAS}
          </p>
        </Seccion>
      </div>
    </>
  );
}

function TablaSeguimiento({ lista }: { lista: Lista }) {
  return (
    <div className="desliza">
      <table>
        <thead>
          <tr>
            <th style={{ paddingLeft: 20 }}>Valor</th>
            <th className="num">Precio</th>
            <th className="num">Δ precio</th>
            <th className="num">Δ score</th>
            <th className="num" style={{ paddingRight: 20 }}>Score</th>
          </tr>
        </thead>
        <tbody>
          {lista.valores.slice(0, 6).map((v) => (
            <tr key={v.ticker}>
              <td style={{ paddingLeft: 20 }}>
                <Link href={`/valores/${encodeURIComponent(v.ticker)}`} className="mono" style={{ fontSize: 13 }}>
                  {v.ticker}
                </Link>
                <div className="apunte">{v.nombre}</div>
              </td>
              <td className="num">{v.precio?.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? "—"}</td>
              <td className="num">
                <Variacion valor={v.variacion_precio} motivo={v.motivos.variacion_precio} />
              </td>
              <td className="num">
                <Variacion valor={v.variacion_score} motivo={v.motivos.variacion_score} sufijo=" pts" decimales={1} />
              </td>
              <td className="num" style={{ paddingRight: 20 }}>
                <PildoraScore valor={v.score} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TablaRanking({ datos }: { datos: RespuestaRanking }) {
  return (
    <div className="desliza">
      <table>
        <thead>
          <tr>
            <th style={{ paddingLeft: 20 }}>Valor</th>
            <th>Mercado</th>
            <th>Sector</th>
            <th className="num" style={{ paddingRight: 20 }}>Score</th>
          </tr>
        </thead>
        <tbody>
          {datos.puestos.map((p) => (
            <tr key={p.ticker}>
              <td style={{ paddingLeft: 20 }}>
                <Link href={`/valores/${encodeURIComponent(p.ticker)}`} className="mono" style={{ fontSize: 13 }}>
                  {p.ticker}
                </Link>
                <div className="apunte">{p.nombre}</div>
              </td>
              <td className="apunte">{p.mercado.toUpperCase()}</td>
              <td className="apunte">{p.sector?.replace(/_/g, " ") ?? "—"}</td>
              <td className="num" style={{ paddingRight: 20 }}>
                <PildoraScore valor={p.valor} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Cambios({ subidas, caidas }: { subidas: RespuestaRanking | null; caidas: RespuestaRanking | null }) {
  const filas = [
    ...(subidas?.puestos ?? []).map((p) => ({ ...p, sube: true })),
    ...(caidas?.puestos ?? []).map((p) => ({ ...p, sube: false })),
  ];

  if (!filas.length) {
    return (
      <p className="apunte" style={{ margin: 0, lineHeight: 1.6 }}>
        Sin comparación posible: hace falta que el motor haya puntuado en dos fechas separadas por
        30 días. No es un cero, es que todavía no se puede calcular.
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {filas.map((p) => (
        <div key={`${p.sube}-${p.ticker}`} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              marginTop: 6,
              flex: "0 0 6px",
              background: p.sube ? "var(--sube)" : "var(--baja)",
            }}
            aria-hidden
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, lineHeight: 1.45 }}>
              <Link href={`/valores/${encodeURIComponent(p.ticker)}`} className="mono" style={{ fontSize: 12 }}>
                {p.ticker}
              </Link>{" "}
              <span style={{ color: "var(--tinta-2)" }}>
                {p.sube ? "sube" : "baja"} <Variacion valor={p.valor} sufijo=" pts" decimales={1} /> de score
              </span>
            </div>
            <div className="mono" style={{ fontSize: 10, color: "var(--tinta-4)", marginTop: 4 }}>
              {p.anterior !== null ? `DESDE ${p.anterior.toFixed(0)}` : null}
              {p.overall !== null ? ` · AHORA ${p.overall.toFixed(0)}` : null}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
