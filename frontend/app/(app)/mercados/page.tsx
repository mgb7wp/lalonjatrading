// Mercados. Implementa la pantalla `markets` del diseno.
//
// El diseno la llena de indices con su variacion del dia, sectores y mayores
// movimientos. Aqui se pinta lo que se sabe de verdad de cada mercado —su
// divisa, su calendario, su indice de referencia, cuantos valores tiene y si
// hay datos cargados— porque eso es lo que la API sirve hoy.
//
// El bloque de variacion diaria de los indices NO se inventa: los indices estan
// en el universo pero el endpoint de mercados no publica su cotizacion, y
// calcularla aqui a partir de otra llamada seria construir un numero en el
// frontend que el motor no ha validado.

import Link from "next/link";

import { Cabecera } from "@/components/armazon";
import { Panel, Tarjeta } from "@/components/piezas";
import { api, intenta, type Market, type RespuestaRanking } from "@/lib/api";
import { usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

export const metadata = { title: "Mercados · LaLonja" };

type Frescura = {
  dataset: string;
  market_id: string | null;
  last_data_date: string | null;
  source: string | null;
  securities_covered: number | null;
  securities_expected: number | null;
  coverage: number | null;
  days_behind: number | null;
  is_stale: boolean;
};

type SaludDatos = { estado: string; datasets: Frescura[] };

export default async function Mercados() {
  const dentro = (await usuarioActual()) !== null;
  const [mercados, salud, mejores] = await Promise.all([
    intenta(api<Market[]>("/markets")),
    intenta(api<SaludDatos>("/health/data")),
    intenta(api<RespuestaRanking>("/rankings?tipo=mejor_score&n=100")),
  ]);

  const porMercado = new Map<string, Frescura[]>();
  for (const d of salud?.datasets ?? []) {
    if (!d.market_id) continue;
    porMercado.set(d.market_id, [...(porMercado.get(d.market_id) ?? []), d]);
  }

  // Cuántos valores de cada mercado tienen score. Sale de un ranking amplio, que
  // ya viene deduplicado por empresa.
  const puntuados = new Map<string, number>();
  for (const p of mejores?.puestos ?? []) {
    puntuados.set(p.mercado, (puntuados.get(p.mercado) ?? 0) + 1);
  }

  const total = mercados?.reduce((t, m) => t + m.securities, 0) ?? 0;
  const conDatos = (mercados ?? []).filter((m) => (porMercado.get(m.id)?.length ?? 0) > 0).length;

  return (
    <>
      {dentro ? <Cabecera miga="Mercados" /> : null}

      <div style={{ padding: "30px 28px 60px" }}>
        <h1 style={{ fontSize: 28 }}>Mercados</h1>
        <p style={{ color: "var(--tinta-3)", margin: "8px 0 24px", maxWidth: "70ch" }}>
          Cada mercado tiene su calendario, su huso y su divisa. La cobertura de abajo es la real:
          un mercado dado de alta no es un mercado con datos.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(200px,1fr))", gap: 14, marginBottom: 28 }}>
          <Tarjeta rotulo="Mercados" cifra={mercados?.length ?? "—"} apunte="dados de alta" acento />
          <Tarjeta
            rotulo="Con datos cargados"
            cifra={mercados ? `${conDatos} de ${mercados.length}` : "—"}
            apunte="el resto está en catálogo pero vacío"
          />
          <Tarjeta rotulo="Valores" cifra={total || "—"} apunte="en catálogo" />
          <Tarjeta
            rotulo="Puntuados"
            cifra={mejores?.puestos.length ?? "—"}
            apunte={mejores?.fecha_datos ? `a ${mejores.fecha_datos}` : "sin scores"}
          />
        </div>

        {!mercados ? (
          <p className="bloque-falta">No disponible. El motor no ha respondido.</p>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(330px,1fr))", gap: 18 }}>
            {mercados.map((m) => {
              const conjuntos = porMercado.get(m.id) ?? [];
              const precios = conjuntos.find((c) => c.dataset === "precios");
              const fundamentales = conjuntos.find((c) => c.dataset === "fundamentales");
              return (
                <Panel
                  key={m.id}
                  titulo={m.name}
                  extra={
                    <span className="mono" style={{ fontSize: 10, color: "var(--tinta-4)" }}>
                      {m.id.toUpperCase()} · {m.currency}
                    </span>
                  }
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <Linea k="Valores en catálogo" v={String(m.securities)} />
                    <Linea k="Con score" v={String(puntuados.get(m.id) ?? 0)} />
                    <Linea k="Calendario" v={m.trading_calendar} />
                    <Linea
                      k="Índice de referencia"
                      v={
                        <>
                          {m.benchmark ?? "—"}
                          {m.benchmark && !m.benchmark_is_total_return ? (
                            <span className="apunte" style={{ marginLeft: 8 }}>
                              índice de precio
                            </span>
                          ) : null}
                        </>
                      }
                    />
                    <Cobertura titulo="Precios" f={precios} />
                    <Cobertura titulo="Fundamentales" f={fundamentales} />
                  </div>

                  {m.benchmark && !m.benchmark_is_total_return ? (
                    // D-5, y no es un detalle: importa a quien vaya a comparar.
                    <p className="apunte" style={{ marginTop: 14, lineHeight: 1.6 }}>
                      El índice no incluye dividendos y las acciones sí. Comparar uno contra otras
                      regala a cada acción la rentabilidad por dividendo del índice, así que sirve
                      para leer el régimen del mercado pero no para medir si un valor lo bate.
                    </p>
                  ) : null}
                </Panel>
              );
            })}
          </div>
        )}

        <p className="apunte" style={{ marginTop: 24 }}>
          ¿Buscas un valor concreto? <Link href="/buscar">Búscalo por nombre, ticker o ISIN</Link>.
        </p>
      </div>
    </>
  );
}

function Linea({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 14 }}>
      <span style={{ fontSize: 13, color: "var(--tinta-3)" }}>{k}</span>
      <span className="mono" style={{ fontSize: 13, textAlign: "right" }}>
        {v}
      </span>
    </div>
  );
}

function Cobertura({ titulo, f }: { titulo: string; f: Frescura | undefined }) {
  if (!f) {
    return (
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 14 }}>
        <span style={{ fontSize: 13, color: "var(--tinta-3)" }}>{titulo}</span>
        <span className="apunte" style={{ color: "var(--baja)" }}>
          sin cargar
        </span>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 14 }}>
      <span style={{ fontSize: 13, color: "var(--tinta-3)" }}>{titulo}</span>
      <span style={{ textAlign: "right" }}>
        <span className="mono" style={{ fontSize: 13 }}>
          {f.securities_covered}/{f.securities_expected}
        </span>
        <span className="apunte" style={{ display: "block", fontSize: 11 }}>
          {f.last_data_date}
          {f.is_stale ? " · rancio" : null}
        </span>
      </span>
    </div>
  );
}
