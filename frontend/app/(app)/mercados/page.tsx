// Mercados (v2): los cinco, con su bloque, divisa, indice, numero de valores y
// la frescura de precios y fundamentales de cada uno.
//
// La cobertura es la real: un mercado dado de alta no es un mercado con datos.
// El REGIMEN, que el diseno pide aqui, no lo publica la API por mercado, y se
// declara asi en lugar de deducirlo en el frontend.

import { ErrorCarga, PrimerUso } from "@/components/estados";
import { Encabezado } from "@/components/piezas";
import { api, frescuraPorMercado, intenta, screener, type FrescuraDatos, type Market, type SaludDatos } from "@/lib/api";
import { fechaConsulta } from "@/lib/consulta";
import { conFecha, fmtFecha } from "@/lib/fecha";

export const dynamic = "force-dynamic";

export const metadata = { title: "Mercados" };

const BLOQUE: Record<string, string> = {
  developed: "Desarrollado",
  desarrollado: "Desarrollado",
  emerging: "Emergente",
  emergente: "Emergente",
};

function Frescura({ f, clave }: { f: FrescuraDatos | undefined; clave: string }) {
  if (!f || !f.last_data_date) {
    return (
      <span className="fresh is-none" title={`${clave}: sin cargar`}>
        ⊘ sin cargar
      </span>
    );
  }
  const cobertura = f.securities_expected ? ` · ${f.securities_covered ?? 0}/${f.securities_expected}` : "";
  if (f.is_stale) {
    return (
      <span className="fresh is-late">
        ◷ {fmtFecha(f.last_data_date, false)} · {f.days_behind ?? "?"} d tarde{cobertura}
      </span>
    );
  }
  return (
    <span className="fresh">
      ✓ {fmtFecha(f.last_data_date, false)}
      {cobertura}
    </span>
  );
}

export default async function Mercados() {
  const fecha = fechaConsulta();
  const [mercados, salud, universo] = await Promise.all([
    intenta(api<Market[]>("/markets")),
    intenta(api<SaludDatos>("/health/data")),
    intenta(screener({ orden: "overall", n: 200, ...(fecha ? { fecha } : {}) })),
  ]);

  const total = mercados?.reduce((t, m) => t + m.securities, 0) ?? null;
  const encabezado = (
    <Encabezado
      rotulo="02 · MERCADOS"
      titulo={mercados ? `${mercados.length === 5 ? "Cinco" : mercados.length} mercados` : "Mercados"}
      meta={total !== null ? `${total} valores · precios y fundamentales por mercado` : undefined}
    />
  );

  if (!mercados) {
    return (
      <div className="page">
        {encabezado}
        <ErrorCarga que="los mercados" detalle="la API no responde" reintentar={conFecha("/mercados", fecha)} />
      </div>
    );
  }
  if (!mercados.length) {
    return (
      <div className="page">
        {encabezado}
        <PrimerUso titulo="Ningún mercado cargado" texto="Los mercados aparecerán cuando se carguen desde la configuración." />
      </div>
    );
  }

  const precios = frescuraPorMercado(salud, "precios");
  const fundamentales = frescuraPorMercado(salud, "fundamentales");
  const puntuados = new Map<string, number>();
  for (const f of universo?.filas ?? []) puntuados.set(f.mercado, (puntuados.get(f.mercado) ?? 0) + 1);
  const conteoCompleto = universo !== null && universo.total <= universo.n;

  return (
    <div className="page">
      {encabezado}
      <section className="mk-table" aria-label="Mercados">
        <div className="mk-headrow desk-only" aria-hidden="true">
          <span>Mercado</span>
          <span>Bloque</span>
          <span>Divisa</span>
          <span>Índice</span>
          <span>Valores</span>
          <span>Régimen</span>
          <span>Precios</span>
          <span>Fundamentales</span>
        </div>
        {mercados.map((m) => (
          <div key={m.id} className="mk-row">
            <span className="name">{m.name}</span>
            <span>
              <span className="tag tag-neutral">{BLOQUE[m.classification?.toLowerCase()] ?? m.classification}</span>
            </span>
            <span className="mono">
              <span className="k">Divisa</span>
              {m.currency}
            </span>
            <span className="mono">
              <span className="k">Índice</span>
              {m.benchmark ?? "sin índice"}
            </span>
            <span className="mono" title={conteoCompleto ? undefined : "recuento de puntuados no disponible"}>
              {m.securities} valores
              {conteoCompleto ? (
                <span style={{ display: "block", fontSize: 11, color: "var(--tinta-3)" }}>{puntuados.get(m.id) ?? 0} con score</span>
              ) : null}
            </span>
            <span title="la API no publica el régimen por mercado">
              <span className="k">Régimen</span>
              <span className="mono" aria-hidden="true">
                ?
              </span>{" "}
              n/d
            </span>
            <span className="wide">
              <span className="k">Precios</span>
              <Frescura f={precios.get(m.id)} clave="precios" />
            </span>
            <span className="wide">
              <span className="k">Fundamentales</span>
              <Frescura f={fundamentales.get(m.id)} clave="fundamentales" />
            </span>
          </div>
        ))}
      </section>
      <p className="explainer">
        El régimen se calcula sobre el índice de referencia de cada mercado y limita las señales de sus valores; la API
        todavía no lo publica por mercado, así que aquí se declara «n/d» en lugar de deducirlo. Los cinco índices de
        referencia son de precio, sin dividendos: sirven para leer el régimen del mercado, no para medir si un valor lo
        bate.
      </p>
      {!salud ? (
        <p className="bloque-falta">
          <strong>NO DISPONIBLE</strong>Frescura de los datos: la API no ha respondido.
        </p>
      ) : null}
    </div>
  );
}
