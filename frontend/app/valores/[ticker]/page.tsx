import { notFound } from "next/navigation";

import {
  Bloque,
  InsigniaRegimen,
  InsigniaSenal,
  Medidor,
  millones,
  nombre,
  numero,
} from "@/components/piezas";
import { ApiError, api, type Analisis } from "@/lib/api";

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

export default async function Valor({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;

  let a: Analisis;
  try {
    a = await api<Analisis>(`/stocks/${encodeURIComponent(ticker)}/analysis`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    return (
      <div className="error">
        <h1>No se ha podido cargar {ticker.toUpperCase()}</h1>
        <p className="apunte">El motor no ha respondido. Inténtalo de nuevo en un momento.</p>
      </div>
    );
  }

  const v = a.valor;

  return (
    <>
      <h1>
        {v.ticker} <span style={{ color: "var(--tinta-2)", fontWeight: 400 }}>{v.name}</span>
      </h1>
      <p className="apunte">
        {v.market_id.toUpperCase()} · {v.currency_code} · {v.sector ? v.sector.replace(/_/g, " ") : "sector sin clasificar"}
        {v.is_primary_listing ? "" : " · línea secundaria (no es la cotización principal)"}
        {v.active ? "" : " · dado de baja"}
      </p>

      <div className="rejilla" style={{ marginTop: 18 }}>
        <div className="tarjeta">
          <div className="etiqueta">Score global</div>
          <div className="cifra">
            {a.score.datos ? a.score.datos.overall.toFixed(0) : "—"}
          </div>
          <div className="apunte">
            {a.score.datos
              ? `percentil dentro de ${a.score.datos.n_cohorte} comparables`
              : "sin puntuar"}
          </div>
        </div>
        <div className="tarjeta">
          <div className="etiqueta">Señal</div>
          <div style={{ margin: "8px 0 4px" }}>
            <InsigniaSenal senal={a.senal.datos?.senal ?? null} />
          </div>
          <div className="apunte">
            {a.senal.datos ? (MOTIVOS[a.senal.datos.motivo] ?? a.senal.datos.motivo) : "sin señal"}
          </div>
        </div>
        <div className="tarjeta">
          <div className="etiqueta">Régimen del mercado</div>
          <div style={{ margin: "8px 0 4px" }}>
            <InsigniaRegimen regimen={a.senal.datos?.regimen ?? null} />
          </div>
          <div className="apunte">tendencia, drawdown y volatilidad del índice</div>
        </div>
        <div className="tarjeta">
          <div className="etiqueta">Último cierre</div>
          <div className="cifra">
            {a.precio.datos ? numero(a.precio.datos.cierre) : "—"}
          </div>
          <div className="apunte">
            {a.precio.datos ? `${v.currency_code} · ${a.precio.datos.fecha}` : "sin precios"}
          </div>
        </div>
      </div>

      <Bloque titulo="Score por pilares" bloque={a.score}>
        {(s) => (
          <>
            <div className="desliza">
              <table>
                <thead>
                  <tr>
                    <th>Pilar</th>
                    <th style={{ width: "50%" }}>Percentil</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(s.pilares).map(([clave, valor]) => (
                    <tr key={clave}>
                      <td>{nombre(clave)}</td>
                      <td>
                        {valor === null ? (
                          <span className="apunte">
                            no disponible — {s.pilares_no_disponibles[clave] ?? "sin motivo"}
                          </span>
                        ) : (
                          <Medidor valor={valor} />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3 style={{ marginTop: 20 }}>Sub-scores</h3>
            <div className="desliza">
              <table>
                <tbody>
                  {Object.entries(s.subscores)
                    .filter(([, valor]) => valor !== null)
                    .map(([clave, valor]) => (
                      <tr key={clave}>
                        <td>{nombre(clave)}</td>
                        <td style={{ width: "50%" }}>
                          <Medidor valor={valor} />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <p className="apunte" style={{ marginTop: 10 }}>
              Cohorte: {s.cohorte} · modelo {s.modelo}. Un pilar ausente no se rellena
              con la media; se declara, y el peso se reparte entre los que sí están.
            </p>
          </>
        )}
      </Bloque>

      <Bloque titulo="Qué sostiene el score y qué lo lastra" bloque={a.explicacion}>
        {(e) => (
          <div className="rejilla" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
            <div className="tarjeta">
              <div className="etiqueta">A favor</div>
              {e.a_favor.length === 0 ? (
                <p className="vacio">Nada por encima del percentil 70.</p>
              ) : (
                <ul style={{ paddingLeft: 18, margin: "8px 0 0" }}>
                  {e.a_favor.map((f) => (
                    <li key={f.nombre}>
                      {nombre(f.nombre)} <strong>{f.valor.toFixed(0)}</strong>{" "}
                      <span className="apunte">({f.nivel})</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="tarjeta">
              <div className="etiqueta">En contra</div>
              {e.en_contra.length === 0 ? (
                <p className="vacio">Nada por debajo del percentil 30.</p>
              ) : (
                <ul style={{ paddingLeft: 18, margin: "8px 0 0" }}>
                  {e.en_contra.map((f) => (
                    <li key={f.nombre}>
                      {nombre(f.nombre)} <strong>{f.valor.toFixed(0)}</strong>{" "}
                      <span className="apunte">({f.nivel})</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="tarjeta">
              <div className="etiqueta">Cambio en 30 días</div>
              {Object.keys(e.cambio_30d).length === 0 ? (
                <p className="vacio">
                  No comparable: falta la foto de hace 30 días. Un cero diría «no se
                  movió», que es una afirmación sobre datos que no existen.
                </p>
              ) : (
                <ul style={{ paddingLeft: 18, margin: "8px 0 0" }}>
                  {Object.entries(e.cambio_30d).map(([clave, delta]) => (
                    <li key={clave}>
                      {nombre(clave)}{" "}
                      <strong style={{ fontVariantNumeric: "tabular-nums" }}>
                        {delta > 0 ? "+" : ""}
                        {delta.toFixed(1)}
                      </strong>
                    </li>
                  ))}
                </ul>
              )}
              {e.cambio_no_comparable.length > 0 && Object.keys(e.cambio_30d).length > 0 ? (
                <p className="apunte" style={{ marginTop: 8 }}>
                  Sin comparar: {e.cambio_no_comparable.map(nombre).join(", ")}.
                </p>
              ) : null}
            </div>
          </div>
        )}
      </Bloque>

      <Bloque titulo="Señal" bloque={a.senal}>
        {(s) => (
          <div className="tarjeta">
            <p style={{ marginTop: 0 }}>
              <InsigniaSenal senal={s.senal} />{" "}
              <span className="apunte">
                {MOTIVOS[s.motivo] ?? s.motivo}
                {s.horizonte_dias ? ` · horizonte ${s.horizonte_dias} días` : ""}
              </span>
            </p>
            {s.detalle ? (
              <p className="apunte" style={{ fontVariantNumeric: "tabular-nums" }}>
                {Object.entries(s.detalle)
                  .map(([k, val]) => `${nombre(k)}: ${String(val)}`)
                  .join(" · ")}
              </p>
            ) : null}
            {/* Metadatos que exige el Reglamento de Abuso de Mercado para
                publicar una recomendación de inversión general. */}
            <p className="apunte" style={{ marginBottom: 0 }}>
              Autor: {s.autor}
              {s.metodologia ? ` · Metodología: ${s.metodologia}` : ""}
              {s.confianza !== null
                ? ` · Cobertura de datos: ${(s.confianza * 100).toFixed(0)} %`
                : ""}
            </p>
          </div>
        )}
      </Bloque>

      <Bloque titulo="Fundamentales" bloque={a.fundamental}>
        {(f) => (
          <>
            <div className="desliza">
              <table>
                <tbody>
                  <tr><td>Ventas</td><td className="num">{millones(f.ventas)}</td></tr>
                  <tr><td>EBIT</td><td className="num">{millones(f.ebit)}</td></tr>
                  <tr><td>Beneficio neto</td><td className="num">{millones(f.beneficio_neto)}</td></tr>
                  <tr><td>Flujo de caja libre</td><td className="num">{millones(f.flujo_caja_libre)}</td></tr>
                  <tr><td>Patrimonio neto</td><td className="num">{millones(f.patrimonio_neto)}</td></tr>
                  <tr><td>Deuda neta</td><td className="num">{millones(f.deuda_neta)}</td></tr>
                  <tr><td>ROE</td><td className="num">{numero(f.roe)}</td></tr>
                  <tr><td>Margen operativo</td><td className="num">{numero(f.margen_operativo)}</td></tr>
                </tbody>
              </table>
            </div>
            <p className="apunte" style={{ marginTop: 10 }}>
              Ejercicio cerrado el {f.fin_periodo}, publicado el {f.fecha_publicacion}
              {f.divisa_reporte ? ` · cifras en ${f.divisa_reporte}` : ""}.{" "}
              {f.origen_pit === "captured"
                ? "Cifra capturada tal y como se publicó entonces."
                : "Cifra reconstruida a posteriori: puede llevar reexpresiones que no se conocían en su día."}
            </p>
          </>
        )}
      </Bloque>

      <Bloque titulo="Técnico" bloque={a.tecnico}>
        {(t) => (
          <div className="desliza">
            <table>
              <tbody>
                <tr><td>RSI 14</td><td className="num">{numero(t.rsi_14)}</td></tr>
                <tr><td>Media 50</td><td className="num">{numero(t.sma_50)}</td></tr>
                <tr><td>Media 200</td><td className="num">{numero(t.sma_200)}</td></tr>
                <tr><td>ATR 14</td><td className="num">{numero(t.atr_14)}</td></tr>
                <tr><td>Beta</td><td className="num">{numero(t.beta)}</td></tr>
                <tr><td>Fuerza relativa</td><td className="num">{numero(t.fuerza_relativa)}</td></tr>
              </tbody>
            </table>
          </div>
        )}
      </Bloque>

      <Bloque titulo="Predicción del modelo" bloque={a.prediccion}>
        {() => null}
      </Bloque>
    </>
  );
}
