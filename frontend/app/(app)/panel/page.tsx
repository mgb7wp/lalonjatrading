// El panel (v2): el universo de un vistazo.
//
// Cinco mercados, la distribucion de senales, los mejor puntuados y lo que mas
// ha subido y caido en 30 dias. Cada bloque se pide por separado y, si uno no
// responde, se declara ese y se ensenan los demas.
//
// ## Lo que el diseno pide y la API no publica
//
// - El REGIMEN de cada mercado: el motor lo calcula por valor, pero ningun
//   endpoint lo sirve por mercado. Se declara no disponible, con el motivo; no
//   se deduce aqui a partir de otra cosa.
// - El SCORE MEDIANO de cada mercado es la mediana de los scores que devuelve
//   el screener. Es un resumen de cifras del motor, no una cifra nueva, y solo
//   se ensena si el screener ha devuelto el universo entero: con una muestra
//   recortada la mediana saldria sesgada hacia arriba.
// - La DISTRIBUCION DE SENALES se cuenta sobre las mismas filas, con la misma
//   condicion, y dice sobre cuantos valores se ha contado.

import { Encabezado, InsigniaSenal, Celdas, ESTADO_SENAL, ORDEN_SENALES, Variacion } from "@/components/piezas";
import { ErrorCarga, PrimerUso } from "@/components/estados";
import {
  api,
  frescuraPorMercado,
  intenta,
  screener,
  type FilaScreener,
  type Market,
  type Puesto,
  type RespuestaRanking,
  type SaludDatos,
} from "@/lib/api";
import { fechaConsulta } from "@/lib/consulta";
import { conFecha, fmtFecha } from "@/lib/fecha";

export const dynamic = "force-dynamic";

export const metadata = { title: "Panel" };

const TOPE_SCREENER = 200;

const MOTIVO_REGIMEN = "la API no publica el régimen por mercado";

function mediana(xs: number[]): number | null {
  if (!xs.length) return null;
  const o = [...xs].sort((a, b) => a - b);
  const m = Math.floor(o.length / 2);
  return o.length % 2 ? o[m] : (o[m - 1] + o[m]) / 2;
}

export default async function PanelPagina() {
  const fecha = fechaConsulta();
  const [mercados, salud, universo, subidas, caidas] = await Promise.all([
    intenta(api<Market[]>("/markets")),
    intenta(api<SaludDatos>("/health/data")),
    intenta(screener({ orden: "overall", descendente: true, n: TOPE_SCREENER, ...(fecha ? { fecha } : {}) })),
    intenta(api<RespuestaRanking>(`/rankings?tipo=mas_mejorado&n=100`)),
    intenta(api<RespuestaRanking>(`/rankings?tipo=mayor_caida&n=100`)),
  ]);

  const filas = universo?.filas ?? [];
  const completo = universo !== null && universo.total <= universo.n;
  const fechaDatos = universo?.fecha_datos ?? subidas?.fecha_datos ?? null;
  const href = (t: string) => conFecha(`/valores/${encodeURIComponent(t)}`, fecha);
  const nombreMercado = new Map((mercados ?? []).map((m) => [m.id, m.name]));

  const encabezado = (
    <Encabezado
      rotulo="01 · PANEL"
      titulo={fechaDatos ? `Universo al ${fmtFecha(fechaDatos)}` : "Universo"}
      meta={universo && universo.total > 0 ? `${universo.total} valores puntuados · perfil ${universo.modelo}` : undefined}
    />
  );

  if (!mercados && !universo && !subidas && !caidas) {
    return (
      <div className="page">
        {encabezado}
        <ErrorCarga que="el panel" detalle="la API no responde" reintentar={conFecha("/panel", fecha)} />
      </div>
    );
  }

  if (universo && universo.total === 0 && (mercados?.length ?? 0) > 0) {
    return (
      <div className="page">
        {encabezado}
        <PrimerUso
          titulo="Aún no hay scores"
          texto={
            fecha
              ? `El motor no tenía scores calculados el ${fmtFecha(fecha)}.`
              : "El motor calcula los primeros scores tras la primera carga de precios y fundamentales."
          }
          accion="Ver los mercados"
          href="/mercados"
        />
      </div>
    );
  }

  // Variacion a 30 dias por valor: la unen las dos listas de variacion. Un valor
  // que no aparece en ninguna no tiene score comparable hace 30 dias.
  const delta = new Map<string, number>();
  for (const p of [...(subidas?.puestos ?? []), ...(caidas?.puestos ?? [])]) delta.set(p.ticker, p.valor);

  const precios = frescuraPorMercado(salud, "precios");
  const top = filas.slice(0, 6);

  return (
    <div className="page">
      {encabezado}

      {/* Los cinco mercados */}
      {mercados ? (
        <section className="markets-strip" aria-label="Mercados">
          {mercados.map((m) => {
            const scores = filas.filter((f) => f.mercado === m.id && f.overall !== null).map((f) => f.overall as number);
            const med = completo ? mediana(scores) : null;
            const f = precios.get(m.id);
            return (
              <a key={m.id} className="market-cell" href={conFecha("/mercados", fecha)}>
                <div className="top">
                  <span className="name">{m.name}</span>
                  <span className="idx">{m.benchmark ?? "sin índice"}</span>
                </div>
                <div className="mid">
                  <div style={{ display: "grid" }}>
                    <span style={{ fontSize: 11, color: "var(--tinta-3)" }}>Score mediano</span>
                    {med !== null ? (
                      <span className="med">{med.toFixed(0)}</span>
                    ) : (
                      <span style={{ fontSize: 12 }} title={completo ? "sin valores puntuados" : "el screener no ha devuelto el universo completo"}>
                        no disponible
                      </span>
                    )}
                  </div>
                  <span className="reg" title={MOTIVO_REGIMEN}>
                    <span className="mono" aria-hidden="true">?</span>
                    <br />
                    régimen n/d
                  </span>
                </div>
                <Celdas valor={med} alto={6} />
                <div className="foot">
                  {m.securities} valores ·{" "}
                  {!f ? "sin precios" : f.is_stale ? `precios con ${f.days_behind ?? "?"} d de retraso` : `precios al ${fmtFecha(f.last_data_date, false)}`}
                </div>
              </a>
            );
          })}
        </section>
      ) : (
        <p className="bloque-falta">
          <strong>NO DISPONIBLE</strong>Mercados: la API no ha respondido.
        </p>
      )}

      {/* Distribucion de senales */}
      <section style={{ display: "grid", gap: 10 }} aria-labelledby="h-senales">
        <div className="section-head">
          <h2 id="h-senales">Señales del universo</h2>
          {universo && fechaDatos ? (
            <span className="mono" style={{ fontSize: 11, color: "var(--tinta-3)" }}>
              {completo ? `${universo.total} valores` : `los ${universo.n} primeros de ${universo.total}`} · horizonte 90 días ·{" "}
              {fmtFecha(fechaDatos)}
            </span>
          ) : null}
        </div>
        {universo && filas.length ? (
          <Senales filas={filas} />
        ) : (
          <p className="bloque-falta">
            <strong>NO DISPONIBLE</strong>Distribución de señales: {universo ? "no hay valores puntuados." : "la API no ha respondido."}
          </p>
        )}
      </section>

      <section className="cols-21">
        {/* Mejor puntuados */}
        <div className="panel-box">
          <div className="panel-box-head">
            <h2>Mejor puntuados</h2>
            <a href={conFecha("/rankings", fecha)}>Ver ranking completo</a>
          </div>
          {top.length ? (
            <>
              <div className="rank-headrow" aria-hidden="true">
                <span>#</span>
                <span>Valor</span>
                <span className="desk-only">Mercado</span>
                <span>Score · percentil</span>
                <span className="desk-only">Señal</span>
                <span className="right">Δ 30 d</span>
              </div>
              <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {top.map((r, i) => (
                  <li key={r.ticker}>
                    <a className="rank-row" href={href(r.ticker)}>
                      <span className="rank">{String(i + 1).padStart(2, "0")}</span>
                      <span className="stock-id">
                        <span className="t">{r.ticker}</span>
                        <span className="n">{r.nombre}</span>
                      </span>
                      <span className="desk-only" style={{ fontSize: 13 }}>
                        {nombreMercado.get(r.mercado) ?? r.mercado.toUpperCase()}
                      </span>
                      <span className="score-cell">
                        <span className="s">{r.overall?.toFixed(0) ?? "n/d"}</span>
                        <Celdas valor={r.overall} />
                      </span>
                      <span className="desk-only">
                        <InsigniaSenal senal={r.senal} />
                      </span>
                      <span className="right">
                        <Variacion
                          valor={delta.get(r.ticker) ?? null}
                          sufijo=""
                          decimales={0}
                          motivo="no comparable: sin score hace 30 días o cambio de cohorte"
                        />
                      </span>
                    </a>
                  </li>
                ))}
              </ol>
              <div className="note">
                Percentil dentro de su cohorte sectorial
                {cohortes(top)}. Perfil {universo?.modelo ?? "equilibrado"}.
              </div>
            </>
          ) : (
            <p className="bloque-falta" style={{ margin: 14 }}>
              <strong>NO DISPONIBLE</strong>
              {universo ? "Todavía no hay scores calculados." : "La API no ha respondido."}
            </p>
          )}
        </div>

        {/* Lo que mas cambia a 30 dias */}
        <div className="stack">
          <Movimientos titulo="Más mejoran" datos={subidas} href={href} />
          <Movimientos titulo="Más caen" datos={caidas} href={href} />
        </div>
      </section>
    </div>
  );
}

function cohortes(filas: FilaScreener[]): string {
  const n = filas.map((f) => f.campos.n_cohorte).filter((x): x is number => typeof x === "number");
  if (!n.length) return "";
  const min = Math.min(...n);
  const max = Math.max(...n);
  return min === max ? ` (de ${min} valores)` : ` (de ${min} a ${max} valores)`;
}

function Senales({ filas }: { filas: FilaScreener[] }) {
  const cuenta = new Map<string, number>();
  let sin = 0;
  for (const f of filas) {
    if (f.senal && ESTADO_SENAL[f.senal]) cuenta.set(f.senal, (cuenta.get(f.senal) ?? 0) + 1);
    else sin++;
  }
  return (
    <>
      <div className="sig-bar" aria-hidden="true">
        {ORDEN_SENALES.filter((k) => (cuenta.get(k) ?? 0) > 0).map((k) => {
          const e = ESTADO_SENAL[k];
          return (
            <div key={k} style={{ flex: cuenta.get(k), background: e.solido ? e.color : "transparent", color: e.solido ? "var(--papel)" : e.color }}>
              {e.glifo} {cuenta.get(k)}
            </div>
          );
        })}
      </div>
      <ul className="sig-legend">
        {ORDEN_SENALES.map((k) => (
          <li key={k}>
            <span className="mono" aria-hidden="true">
              {ESTADO_SENAL[k].glifo}
            </span>{" "}
            {ESTADO_SENAL[k].texto}{" "}
            <span className="mono" style={{ color: "var(--tinta-3)" }}>
              {cuenta.get(k) ?? 0}
            </span>
          </li>
        ))}
        <li style={{ color: "var(--tinta-3)" }}>
          ○ Sin señal <span className="mono">{sin}</span>
        </li>
      </ul>
    </>
  );
}

function Movimientos({ titulo, datos, href }: { titulo: string; datos: RespuestaRanking | null; href: (t: string) => string }) {
  const filas: Puesto[] = datos?.puestos.slice(0, 3) ?? [];
  return (
    <div className="panel-box">
      <div className="panel-box-head">
        <h2 className="sm">{titulo}</h2>
        <span className="mono" style={{ fontSize: 11, color: "var(--tinta-3)" }}>
          score · 30 d
        </span>
      </div>
      {filas.length ? (
        filas.map((p) => (
          <a key={p.ticker} className="move-row" href={href(p.ticker)}>
            <span className="t">{p.ticker}</span>
            <span className="from">
              {p.anterior?.toFixed(0) ?? "n/d"} → {p.overall?.toFixed(0) ?? "n/d"}
            </span>
            <Variacion valor={p.valor} sufijo="" decimales={0} />
          </a>
        ))
      ) : (
        <p className="bloque-falta" style={{ margin: 14 }}>
          <strong>NO DISPONIBLE</strong>
          {datos
            ? "Sin comparación posible: hace falta que el motor haya puntuado en dos fechas separadas por 30 días."
            : "La API no ha respondido."}
        </p>
      )}
    </div>
  );
}
