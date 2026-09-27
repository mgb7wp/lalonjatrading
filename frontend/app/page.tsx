// La portada publica (v2).
//
// Titular, un esquema de como se lee una ficha —sin cifras que parezcan reales—
// y tres numeros del universo. Esos numeros se leen de la API en lugar de
// escribirse: una portada que presume de datos no puede ser el unico sitio del
// producto donde los datos son de mentira. El que la API no sirve (anos de
// historico) se declara no disponible en vez de rellenarse.

import { redirect } from "next/navigation";

import { AvisoLegal } from "@/components/aviso-legal";
import { MarcaConNombre } from "@/components/marca";
import { Celdas, Esquinas } from "@/components/piezas";
import { api, intenta, type Market, type RespuestaRanking } from "@/lib/api";
import { fmtFecha } from "@/lib/fecha";
import { usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "LaLonja Trading — cada acción, medida contra sus iguales",
  description:
    "Análisis cuantitativo de acciones de cinco mercados sobre un motor determinista. La IA explica lo que el motor calculó; nunca produce una cifra.",
};

const LEYENDA: [string, string][] = [
  ["SEÑAL", "glifo + texto, nunca solo color"],
  ["MOTIVO", "por qué es esa y no otra"],
  ["RÉGIMEN", "alcista · lateral · bajista · desconocido"],
  ["CONFIANZA", "grado de acuerdo de los pilares, no probabilidad"],
  ["HORIZONTE", "90 días"],
  ["FECHA", "toda cifra dice de qué día es"],
];

export default async function Portada() {
  // Quien ya ha entrado no quiere la portada: quiere su panel.
  if (await usuarioActual()) redirect("/panel");

  const [mercados, mejores] = await Promise.all([
    intenta(api<Market[]>("/markets")),
    intenta(api<RespuestaRanking>("/rankings?tipo=mejor_score&n=1")),
  ]);
  const nValores = mercados?.reduce((t, m) => t + m.securities, 0) ?? null;

  return (
    <div className="grid-canvas">
      <header className="pub-header">
        <MarcaConNombre />
        <nav aria-label="Público">
          <a href="/mercados" className="desk-only">
            Mercados
          </a>
          <a href="/rankings" className="desk-only">
            Rankings
          </a>
          <a className="btn btn-secondary" href="/entrar">
            Entrar
          </a>
        </nav>
      </header>

      <main>
        <section className="hero">
          <div className="hero-main">
            <div className="kicker" style={{ letterSpacing: "0.16em" }}>
              ANÁLISIS CUANTITATIVO · {mercados ? `${mercados.length} MERCADOS` : "VARIOS MERCADOS"}
            </div>
            <h1>Cada acción, medida contra sus iguales.</h1>
            <p className="hero-lede">
              Un motor determinista puntúa cada valor de 0 a 100 dentro de su cohorte y emite señales con motivo, régimen
              y horizonte. La IA explica lo que el motor calculó; nunca produce una cifra.
            </p>
            <div className="actions">
              <a className="btn btn-primary blueprint btn-lg" href="/entrar?modo=registro">
                <Esquinas />
                Crear cuenta
              </a>
              <a className="btn btn-secondary btn-lg" href="/rankings">
                Ver el ranking de hoy
              </a>
            </div>
          </div>
          <div className="hero-side">
            <div className="label-mono">ESQUEMA · CÓMO SE LEE UNA FICHA</div>
            <div className="blueprint schema">
              <Esquinas />
              <div className="schema-row">
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                  <span>Score total</span>
                  <span className="mono" style={{ color: "var(--tinta-3)" }}>
                    0 — 100
                  </span>
                </div>
                <span aria-hidden="true">
                  <Celdas valor={100} alto={14} />
                </span>
                <div style={{ fontSize: 12, color: "var(--tinta-2)" }}>
                  Percentil dentro de su cohorte. Un tono, de claro a oscuro. Nunca semáforo.
                </div>
              </div>
              <dl className="schema-legend">
                {LEYENDA.map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </section>

        <section className="stats" aria-label="Universo analizado">
          {mercados ? (
            <>
              <div className="stat">
                <span className="stat-n">{mercados.length}</span>
                <span style={{ fontSize: 14 }}>mercados</span>
                <span className="stat-src">API · configuración de mercados</span>
              </div>
              <div className="stat">
                <span className="stat-n">{nValores}</span>
                <span style={{ fontSize: 14 }}>valores en catálogo</span>
                <span className="stat-src">
                  {mejores?.fecha_datos ? `API · scores del ${fmtFecha(mejores.fecha_datos)}` : "API · aún sin scores calculados"}
                </span>
              </div>
              <div className="stat">
                <span style={{ fontSize: 14 }}>
                  <strong>Años de histórico: no disponible.</strong> La API todavía no publica desde cuándo hay datos, y no
                  lo escribimos a mano.
                </span>
              </div>
            </>
          ) : (
            <div className="stats-none">
              <strong>Cifras del universo no disponibles.</strong> La API no ha respondido y no mostramos aproximaciones en
              su lugar.
            </div>
          )}
        </section>
      </main>

      <AvisoLegal fijo={false} />
    </div>
  );
}
