// La ficha de un valor. Implementa la pantalla `asset` del diseno.
//
// ## Las siete pestanias del diseno, y cuales existen
//
// El diseno dibuja Resumen, Fundamental, Tecnico, Valoracion, Comparables, IA y
// Noticias. Las tres primeras salen de `/stocks/{ticker}/analysis` y estan
// conectadas. IA sale de `/stocks/{ticker}/explanation` (FASE 16), y solo se
// pide al abrir su pestania: cada explicacion nueva cuesta tokens y cupo, y
// pedirla en cada visita a la ficha seria gastar por quien no la va a leer.
// Las otras tres NO tienen backend:
//
// - Valoracion pide un DCF de tres metodos que el motor no calcula.
// - Comparables no existe.
// - Noticias no tiene fuente y no la va a tener gratis.
//
// Se quedan en la barra de pestanias, marcadas, y al abrirlas explican por que
// estan vacias. Quitarlas escondería que estan previstas; rellenarlas con
// numeros de ejemplo seria justo lo que este producto promete no hacer.

import Link from "next/link";
import { notFound } from "next/navigation";

import { anadirASeguimiento } from "@/app/acciones";
import { Cabecera } from "@/components/armazon";
import { Formulario } from "@/components/formularios";
import {
  Bloque,
  EtiquetaFrescura,
  InsigniaRegimen,
  InsigniaSenal,
  Medidor,
  Panel,
  millones,
  nombre,
  numero,
} from "@/components/piezas";
import {
  ApiError,
  NO_DISPONIBLE,
  api,
  type Analisis,
  type ExplicacionIA,
  type RespuestaExplicacion,
} from "@/lib/api";
import { apiSesion, usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

const MOTIVOS: Record<string, string> = {
  score_alto: "El score está por encima del umbral de compra",
  score_intermedio: "El score está en la franja intermedia",
  score_bajo: "El score está por debajo del umbral de venta",
  limita_regimen: "Limitada por el régimen del mercado",
  limita_riesgo: "Limitada por el riesgo",
  limita_momentum: "Limitada por el momentum",
  limita_score_cayendo: "Rebajada porque el score viene cayendo",
  limita_valoracion: "Limitada por la valoración",
  datos_insuficientes: "No hay datos suficientes para emitir una señal",
};

type Pestana = { id: string; etiqueta: string; motivo?: string };

const PESTANAS: Pestana[] = [
  { id: "resumen", etiqueta: "Resumen" },
  { id: "fundamental", etiqueta: "Fundamental" },
  { id: "tecnico", etiqueta: "Técnico" },
  {
    id: "valoracion",
    etiqueta: "Valoración",
    motivo:
      "El diseño muestra un valor razonable calculado por tres métodos ponderados. El motor no calcula descuento de flujos: publicaría un precio objetivo sin poder enseñar de dónde sale, que es lo contrario de lo que hace el resto de la ficha.",
  },
  {
    id: "comparables",
    etiqueta: "Comparables",
    motivo:
      "Comparar con el sector exige agrupar empresas por actividad real y no por la etiqueta del proveedor, y capitalización y múltiplos para todas ellas. El universo tiene 140 valores: las cohortes saldrían de dos o tres empresas y la comparación no diría nada.",
  },
  { id: "ia", etiqueta: "Análisis IA" },
  {
    id: "noticias",
    etiqueta: "Noticias",
    motivo:
      "No hay fuente de noticias gratuita con licencia para reproducirlas a escala. Por eso el pilar de sentimiento se declara no disponible en el score en lugar de imputarse un valor neutro.",
  },
];

export default async function Valor({
  params,
  searchParams,
}: {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { ticker } = await params;
  const { tab = "resumen" } = await searchParams;

  let a: Analisis;
  try {
    a = await api<Analisis>(`/stocks/${encodeURIComponent(ticker)}/analysis`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    return (
      <div style={{ padding: "30px 28px" }}>
        <h1>No se ha podido cargar {ticker.toUpperCase()}</h1>
        <p className="apunte">El motor no ha respondido. Inténtalo de nuevo en un momento.</p>
      </div>
    );
  }

  const v = a.valor;
  const dentro = (await usuarioActual()) !== null;
  const score = a.score.datos;
  const activa = PESTANAS.find((p) => p.id === tab) ?? PESTANAS[0];

  return (
    <>
      {dentro ? <Cabecera miga={`Mercados / ${v.market_id.toUpperCase()} / ${v.ticker}`} /> : null}

      <div style={{ padding: "26px 28px 0" }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 28, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: "min(300px, 100%)" }}>
            <div className="rotulo" style={{ fontSize: 10, letterSpacing: "0.14em" }}>
              {v.market_id.toUpperCase()} · {v.currency_code}
              {v.sector ? ` · ${v.sector.replace(/_/g, " ")}` : null}
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 10, flexWrap: "wrap" }}>
              <h1 style={{ fontSize: 32, margin: 0 }}>{v.name}</h1>
              <span className="mono" style={{ fontSize: 16, color: "var(--tinta-3)" }}>
                {v.ticker}
              </span>
            </div>

            <div style={{ display: "flex", alignItems: "baseline", gap: 16, marginTop: 16 }}>
              {a.precio.datos ? (
                <>
                  <span className="mono" style={{ fontSize: 38, letterSpacing: "-0.02em" }}>
                    {numero(a.precio.datos.cierre)} {v.currency_code}
                  </span>
                  <span className="apunte">
                    último cierre
                    <EtiquetaFrescura frescura={a.precio.frescura} />
                  </span>
                </>
              ) : (
                <span className="bloque-falta" style={{ display: "block" }}>
                  Sin precio. {a.precio.motivo ?? "No hay precios cargados para este valor."}
                </span>
              )}
            </div>

            <div style={{ display: "flex", gap: 26, marginTop: 20, flexWrap: "wrap" }}>
              <Dato k="Señal" v={<InsigniaSenal senal={a.senal.datos?.senal ?? null} />} />
              <Dato k="Régimen" v={<InsigniaRegimen regimen={a.senal.datos?.regimen ?? null} />} />
              {v.is_primary_listing ? null : <Dato k="Línea" v="secundaria" />}
              {v.active ? null : <Dato k="Estado" v="dado de baja" />}
            </div>
          </div>

          <div style={{ minWidth: "min(320px, 100%)", flex: "0 1 380px" }}>
            <Panel>
              <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
                <AnilloScore valor={score?.overall ?? null} />
                <div style={{ flex: 1 }}>
                  <div className="rotulo" style={{ fontSize: 10, letterSpacing: "0.14em", color: "var(--oro)" }}>
                    Score LaLonja
                  </div>
                  {score ? (
                    <>
                      <div style={{ fontWeight: 600, fontSize: 15, marginTop: 6 }}>
                        Mejor que el {score.overall.toFixed(0)} % de su cohorte
                      </div>
                      <div style={{ fontSize: 12, color: "var(--tinta-3)", marginTop: 4, lineHeight: 1.45 }}>
                        {score.n_cohorte} comparables · {score.cohorte.replace(/_/g, " ")} ·{" "}
                        {score.fecha}
                      </div>
                    </>
                  ) : (
                    <div style={{ fontSize: 13, color: "var(--tinta-3)", marginTop: 6, lineHeight: 1.5 }}>
                      {a.score.motivo ?? "Sin puntuar."}
                    </div>
                  )}
                </div>
              </div>

              {score ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 9, marginTop: 18 }}>
                  {Object.entries(score.pilares).map(([clave, valor]) => (
                    <div key={clave} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <span
                        className="mono"
                        style={{ fontSize: 10, letterSpacing: "0.1em", color: "var(--tinta-3)", width: 96 }}
                      >
                        {nombre(clave)}
                      </span>
                      {valor === null ? (
                        <span
                          className="apunte"
                          style={{ flex: 1, fontSize: 11 }}
                          title={score.pilares_no_disponibles[clave]}
                        >
                          no disponible
                        </span>
                      ) : (
                        <span style={{ flex: 1 }}>
                          <Medidor valor={valor} />
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ) : null}

              <div style={{ marginTop: 18 }}>
                {dentro ? (
                  <Formulario accion={anadirASeguimiento} etiquetaBoton="Seguir este valor">
                    <input type="hidden" name="ticker" value={v.ticker} />
                  </Formulario>
                ) : (
                  <p className="apunte" style={{ margin: 0 }}>
                    <Link href="/entrar">Entra</Link> para seguir este valor o añadirlo a una
                    cartera.
                  </p>
                )}
              </div>
            </Panel>
          </div>
        </div>

        <nav
          style={{
            display: "flex",
            gap: 4,
            marginTop: 26,
            borderBottom: "1px solid var(--borde)",
            overflowX: "auto",
            maxWidth: "100%",
            scrollbarWidth: "none",
          }}
          aria-label="Secciones del análisis"
        >
          {PESTANAS.map((p) => {
            const sel = p.id === activa.id;
            return (
              <Link
                key={p.id}
                href={`/valores/${encodeURIComponent(v.ticker)}?tab=${p.id}`}
                aria-current={sel ? "page" : undefined}
                style={{
                  padding: "10px 14px",
                  fontSize: 13,
                  whiteSpace: "nowrap",
                  color: sel ? "var(--tinta)" : p.motivo ? "var(--tinta-4)" : "var(--tinta-3)",
                  borderBottom: sel ? "2px solid var(--oro)" : "2px solid transparent",
                  marginBottom: -1,
                }}
              >
                {p.etiqueta}
                {p.motivo ? (
                  <span className="mono" style={{ fontSize: 9, marginLeft: 6, color: "var(--tinta-4)" }}>
                    ·
                  </span>
                ) : null}
              </Link>
            );
          })}
        </nav>
      </div>

      <div style={{ padding: "26px 28px 60px" }}>
        {activa.motivo ? (
          <p className="bloque-falta" style={{ maxWidth: "80ch" }}>
            <strong style={{ color: "var(--tinta-2)" }}>Todavía no disponible.</strong>{" "}
            {activa.motivo}
          </p>
        ) : activa.id === "resumen" ? (
          <Resumen a={a} />
        ) : activa.id === "fundamental" ? (
          <Fundamental a={a} />
        ) : activa.id === "ia" ? (
          <AnalisisIA ticker={v.ticker} dentro={dentro} />
        ) : (
          <Tecnico a={a} />
        )}
      </div>
    </>
  );
}

function Dato({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div>
      <div className="mono" style={{ fontSize: 9, letterSpacing: "0.14em", color: "var(--tinta-4)", textTransform: "uppercase" }}>
        {k}
      </div>
      <div style={{ marginTop: 6 }}>{v}</div>
    </div>
  );
}

/** El anillo de score del diseno. Un solo tono; el arco mide el percentil. */
function AnilloScore({ valor }: { valor: number | null }) {
  const r = 38;
  const circunferencia = 2 * Math.PI * r;
  const arco = valor === null ? 0 : (Math.max(0, Math.min(100, valor)) / 100) * circunferencia;
  return (
    <svg width="88" height="88" viewBox="0 0 88 88" role="img" aria-label={valor === null ? "Sin puntuar" : `Score ${valor.toFixed(0)} sobre 100`}>
      <circle cx="44" cy="44" r={r} fill="none" stroke="var(--borde)" strokeWidth="7" />
      {valor !== null ? (
        <circle
          cx="44"
          cy="44"
          r={r}
          fill="none"
          stroke="var(--oro)"
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${arco} ${circunferencia}`}
          transform="rotate(-90 44 44)"
        />
      ) : null}
      <text x="44" y="42" textAnchor="middle" fill="var(--tinta)" className="mono" fontSize="26">
        {valor === null ? "—" : valor.toFixed(0)}
      </text>
      <text x="44" y="57" textAnchor="middle" fill="var(--tinta-3)" className="mono" fontSize="8" letterSpacing="1.4">
        /100
      </text>
    </svg>
  );
}

function Resumen({ a }: { a: Analisis }) {
  return (
    <div className="dos-columnas" style={{ "--izq": "1.6fr", gap: 18 } as React.CSSProperties}>
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <Bloque titulo="Qué sostiene el score y qué lo lastra" bloque={a.explicacion}>
          {(e) => (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 22 }}>
              <div>
                <div className="rotulo" style={{ color: "var(--sube)" }}>A favor</div>
                <ul style={{ margin: "10px 0 0", paddingLeft: 18, lineHeight: 1.7 }}>
                  {e.a_favor.length ? (
                    e.a_favor.map((f) => (
                      <li key={f.nombre}>
                        {nombre(f.nombre)} <strong className="mono">{f.valor.toFixed(0)}</strong>{" "}
                        <span className="apunte">({f.nivel})</span>
                      </li>
                    ))
                  ) : (
                    <li className="apunte">Nada destaca por encima del umbral.</li>
                  )}
                </ul>
              </div>
              <div>
                <div className="rotulo" style={{ color: "var(--baja)" }}>En contra</div>
                <ul style={{ margin: "10px 0 0", paddingLeft: 18, lineHeight: 1.7 }}>
                  {e.en_contra.length ? (
                    e.en_contra.map((f) => (
                      <li key={f.nombre}>
                        {nombre(f.nombre)} <strong className="mono">{f.valor.toFixed(0)}</strong>{" "}
                        <span className="apunte">({f.nivel})</span>
                      </li>
                    ))
                  ) : (
                    <li className="apunte">Nada cae por debajo del umbral.</li>
                  )}
                </ul>
              </div>
            </div>
          )}
        </Bloque>

        <Bloque titulo="Sub-scores" bloque={a.score}>
          {(s) => (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(230px,1fr))", gap: "10px 24px" }}>
              {Object.entries(s.subscores).map(([clave, valor]) => (
                <div key={clave} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span style={{ fontSize: 12, color: "var(--tinta-3)", width: 110 }}>{nombre(clave)}</span>
                  <span style={{ flex: 1 }}>
                    <Medidor valor={valor} />
                  </span>
                </div>
              ))}
            </div>
          )}
        </Bloque>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <Bloque titulo="Señal" bloque={a.senal}>
          {(s) => (
            <>
              <InsigniaSenal senal={s.senal} />
              <p style={{ margin: "12px 0 0", fontSize: 13, lineHeight: 1.6, color: "var(--tinta-2)" }}>
                {MOTIVOS[s.motivo] ?? s.motivo}
              </p>
              {/* Metadatos que exige publicar una recomendación general (MAR). */}
              <div className="mono" style={{ fontSize: 10, color: "var(--tinta-4)", marginTop: 14, lineHeight: 1.7 }}>
                AUTOR: {s.autor.toUpperCase()}
                {s.metodologia ? (
                  <>
                    <br />
                    METODOLOGÍA: {s.metodologia}
                  </>
                ) : null}
                <br />
                FECHA: {s.fecha}
              </div>
            </>
          )}
        </Bloque>

        <Bloque titulo="Predicción del modelo" bloque={a.prediccion}>
          {() => <p className="apunte">—</p>}
        </Bloque>
      </div>
    </div>
  );
}

function Fundamental({ a }: { a: Analisis }) {
  return (
    <Bloque titulo="Cuentas publicadas" bloque={a.fundamental}>
      {(f) => (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))", gap: 18 }}>
          <Panel titulo="Cuenta de resultados" sinRelleno>
            <div className="desliza">
              <table>
                <tbody>
                  <Fila k="Ventas" v={millones(f.ventas)} />
                  <Fila k="EBIT" v={millones(f.ebit)} />
                  <Fila k="Beneficio neto" v={millones(f.beneficio_neto)} />
                  <Fila k="Flujo de caja libre" v={millones(f.flujo_caja_libre)} />
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel titulo="Balance y ratios" sinRelleno>
            <div className="desliza">
              <table>
                <tbody>
                  <Fila k="Patrimonio neto" v={millones(f.patrimonio_neto)} />
                  <Fila k="Deuda neta" v={millones(f.deuda_neta)} />
                  <Fila k="ROE" v={f.roe === null ? "—" : `${(f.roe * 100).toFixed(1)} %`} />
                  <Fila
                    k="Margen operativo"
                    v={f.margen_operativo === null ? "—" : `${(f.margen_operativo * 100).toFixed(1)} %`}
                  />
                </tbody>
              </table>
            </div>
          </Panel>
          <Panel titulo="Procedencia del dato">
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.7, color: "var(--tinta-2)" }}>
              Ejercicio cerrado el <strong>{f.fin_periodo}</strong> y publicado el{" "}
              <strong>{f.fecha_publicacion}</strong>.
            </p>
            <p style={{ margin: "12px 0 0", fontSize: 12, lineHeight: 1.7, color: "var(--tinta-3)" }}>
              {f.origen_pit === "captured" ? (
                <>
                  La fecha de publicación es <strong>real</strong>, no estimada, y la cifra es la que
                  se publicó entonces: si la empresa reexpresó sus cuentas después, aquí sigue la
                  original. Es lo que permite backtestear sin mirar al futuro.
                </>
              ) : (
                <>
                  La fecha de publicación está <strong>estimada</strong> ({f.origen_pit}) y la cifra
                  puede venir reexpresada. Se dice porque cambia lo que se puede concluir de ella.
                </>
              )}
            </p>
            {f.divisa_reporte ? (
              <p className="mono" style={{ fontSize: 10, color: "var(--tinta-4)", marginTop: 12 }}>
                DIVISA DE REPORTE: {f.divisa_reporte}
              </p>
            ) : null}
          </Panel>
        </div>
      )}
    </Bloque>
  );
}

function Tecnico({ a }: { a: Analisis }) {
  return (
    <Bloque titulo="Indicadores técnicos" bloque={a.tecnico}>
      {(t) => (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 14 }}>
          <Indicador k="RSI 14" v={numero(t.rsi_14)} nota="sobrecompra por encima de 70" />
          <Indicador k="Media 50" v={numero(t.sma_50)} nota="tendencia de medio plazo" />
          <Indicador k="Media 200" v={numero(t.sma_200)} nota="tendencia de fondo" />
          <Indicador k="ATR 14" v={numero(t.atr_14)} nota="recorrido medio diario" />
          <Indicador k="Beta" v={numero(t.beta)} nota="frente a su índice" />
          <Indicador k="Fuerza relativa" v={numero(t.fuerza_relativa)} nota="frente a su índice" />
        </div>
      )}
    </Bloque>
  );
}

function Fila({ k, v }: { k: string; v: string }) {
  return (
    <tr>
      <td style={{ color: "var(--tinta-2)" }}>{k}</td>
      <td className="num">{v}</td>
    </tr>
  );
}

function Indicador({ k, v, nota }: { k: string; v: string; nota: string }) {
  return (
    <div
      style={{
        background: "var(--superficie)",
        border: "1px solid var(--borde-2)",
        borderRadius: "var(--radio)",
        padding: "15px 18px",
      }}
    >
      <div className="mono" style={{ fontSize: 10, letterSpacing: "0.12em", color: "var(--tinta-3)" }}>
        {k.toUpperCase()}
      </div>
      <div className="mono" style={{ fontSize: 20, marginTop: 8 }}>
        {v}
      </div>
      <div style={{ fontSize: 11, color: "var(--tinta-4)", marginTop: 6 }}>{nota}</div>
    </div>
  );
}

/** La pestaña de IA. Pide la explicación con la sesión del usuario: el plan
 * decide si la hay y el cupo cuántas nuevas al día. */
async function AnalisisIA({ ticker, dentro }: { ticker: string; dentro: boolean }) {
  if (!dentro) {
    return (
      <p className="bloque-falta" style={{ maxWidth: "80ch" }}>
        <Link href="/entrar">Entra</Link> para ver la explicación con IA de este valor. Está
        incluida en los planes Pro y Premium.
      </p>
    );
  }

  let r: RespuestaExplicacion;
  try {
    r = await apiSesion<RespuestaExplicacion>(`/stocks/${encodeURIComponent(ticker)}/explanation`);
  } catch (e) {
    // 403 (plan) y 429 (cupo) traen un `detail` escrito para leerlo tal cual.
    const texto =
      e instanceof ApiError && (e.status === 403 || e.status === 429)
        ? e.message
        : "El servicio de explicaciones no ha respondido. Inténtalo de nuevo en un momento.";
    return (
      <p className="bloque-falta" style={{ maxWidth: "80ch" }}>
        {texto.charAt(0).toUpperCase() + texto.slice(1)}.
      </p>
    );
  }

  return (
    <Bloque titulo="Qué dicen los datos, explicado" bloque={r.explicacion}>
      {(e) => <Explicacion e={e} />}
    </Bloque>
  );
}

function Explicacion({ e }: { e: ExplicacionIA }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: "80ch" }}>
      <Frase texto={e.resumen} grande />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 22 }}>
        <Lista titulo="A favor" color="var(--sube)" items={e.a_favor} vacia="Nada destaca por encima del umbral." />
        <Lista titulo="En contra" color="var(--baja)" items={e.en_contra} vacia="Nada cae por debajo del umbral." />
      </div>

      <Lista titulo="Qué ha cambiado en 30 días" items={e.cambios} vacia={NO_DISPONIBLE} />
      <Lista titulo="Preguntas para seguir investigando" items={e.preguntas} vacia="—" />

      <details>
        <summary className="apunte" style={{ cursor: "pointer" }}>
          Los datos que recibió la IA: cada cifra del texto sale de aquí
        </summary>
        <pre
          className="mono"
          style={{
            fontSize: 11,
            lineHeight: 1.55,
            background: "var(--superficie)",
            border: "1px solid var(--borde-2)",
            borderRadius: "var(--radio)",
            padding: 14,
            overflowX: "auto",
            marginTop: 10,
          }}
        >
          {JSON.stringify(e.entrada, null, 2)}
        </pre>
      </details>

      {/* §44: esto es información general, no asesoramiento. */}
      <p className="apunte" style={{ margin: 0, lineHeight: 1.6 }}>
        Redactado por IA a partir del score del {e.fecha_score}. La IA no calcula: explica cifras
        que ya ha calculado el motor, y un validador descarta cualquier respuesta que cite una cifra
        que no esté en sus datos. No es asesoramiento financiero.
      </p>
      <div className="mono" style={{ fontSize: 10, color: "var(--tinta-4)", lineHeight: 1.7 }}>
        MODELO: {(e.modelo_llm ?? "—").toUpperCase()}
        <br />
        GENERADA: {e.generada.slice(0, 16).replace("T", " ")}
        {e.desde_cache ? " · DESDE CACHÉ" : null}
      </div>
    </div>
  );
}

/** Una frase de la IA. «Información no disponible» se pinta como hueco, no
 * como una afirmación más. */
function Frase({ texto, grande = false }: { texto: string; grande?: boolean }) {
  if (texto.trim() === NO_DISPONIBLE) {
    return <span className="bloque-falta" style={{ display: "block" }}>{NO_DISPONIBLE}.</span>;
  }
  return (
    <p style={{ margin: 0, fontSize: grande ? 15 : 13, lineHeight: 1.7, color: "var(--tinta-2)" }}>
      {texto}
    </p>
  );
}

function Lista({
  titulo,
  items,
  vacia,
  color,
}: {
  titulo: string;
  items: string[];
  vacia: string;
  color?: string;
}) {
  return (
    <div>
      <div className="rotulo" style={color ? { color } : undefined}>
        {titulo}
      </div>
      <ul style={{ margin: "10px 0 0", paddingLeft: 18, lineHeight: 1.7 }}>
        {items.length ? (
          items.map((t, i) =>
            t.trim() === NO_DISPONIBLE ? (
              <li key={i} className="apunte">
                {NO_DISPONIBLE}
              </li>
            ) : (
              <li key={i} style={{ fontSize: 13, color: "var(--tinta-2)" }}>
                {t}
              </li>
            ),
          )
        ) : (
          <li className="apunte">{vacia}</li>
        )}
      </ul>
    </div>
  );
}
