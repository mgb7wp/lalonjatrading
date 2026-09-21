// La portada publica. Implementa la pantalla `landing` del diseno.
//
// ## La tarjeta de muestra trae datos DE VERDAD
//
// El diseno lleva ASML dentro, con su precio y su Score escritos a mano. Aqui se
// pide a la API el valor mejor puntuado del dia y se pinta ese. Cuesta una
// llamada y cambia dos cosas:
//
// - Lo que se ensena en la portada es lo que el motor dice hoy, no una captura.
// - Si el motor no responde, la tarjeta lo dice en lugar de mostrar un numero
//   bonito y falso. Una portada que presume de datos no puede ser el unico sitio
//   del producto donde los datos son de mentira.
//
// ## Las cifras del diseno estan corregidas
//
// El diseno anuncia "48.000 EMPRESAS", "4 MERCADOS" y "DATOS DESDE 2005". El
// universo real son 140 valores en 5 mercados. Se leen de `/markets` en lugar de
// escribirse, para que no vuelvan a quedarse desfasadas.

import Link from "next/link";
import { redirect } from "next/navigation";

import { Marca, MarcaConNombre } from "@/components/marca";
import { api, intenta, type Market, type RespuestaRanking } from "@/lib/api";
import { usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "LaLonja Trading — todo el mercado, ya ordenado",
  description:
    "Análisis cuantitativo de mercados: fundamentales, técnico y valoración en una sola lectura, sobre un motor determinista y reproducible.",
};

const CARACTERISTICAS = [
  {
    n: "01",
    titulo: "Entiende una empresa en un minuto",
    texto:
      "Score, qué lo sostiene y qué lo lastra antes de cualquier tabla. Los fundamentales están debajo, cuando los necesites.",
  },
  {
    n: "02",
    titulo: "Descubre en lugar de buscar",
    texto:
      "Filtra por crecimiento, rentabilidad, valoración o riesgo y recibe una lista corta con el motivo por el que cada empresa aparece.",
  },
  {
    n: "03",
    titulo: "Vigila solo lo que cambia",
    texto:
      "El seguimiento no repite precios: destaca lo que se ha movido en el score, en la señal y en el precio.",
  },
  {
    n: "04",
    titulo: "Cada hueco dice por qué está vacío",
    texto:
      "Cuando un dato no existe, LaLonja lo declara con su motivo en lugar de rellenarlo. Un número inventado es peor que un hueco.",
  },
];

const ORO = "var(--oro)";

function Boton({
  href,
  children,
  principal = false,
  grande = false,
}: {
  href: string;
  children: React.ReactNode;
  principal?: boolean;
  grande?: boolean;
}) {
  return (
    <Link
      href={href}
      style={{
        background: principal ? ORO : "transparent",
        color: principal ? "var(--fondo)" : "var(--tinta)",
        border: principal ? "none" : "1px solid var(--borde-2)",
        borderRadius: "var(--radio)",
        padding: grande ? "14px 26px" : "10px 18px",
        fontSize: grande ? 15 : 13,
        fontWeight: principal ? 700 : 400,
        display: "inline-block",
      }}
    >
      {children}
    </Link>
  );
}

export default async function Portada() {
  // Quien ya ha entrado no quiere la portada: quiere su panel.
  if (await usuarioActual()) redirect("/panel");

  const [mercados, mejores] = await Promise.all([
    intenta(api<Market[]>("/markets")),
    intenta(api<RespuestaRanking>("/rankings?tipo=mejor_score&n=1")),
  ]);

  const nMercados = mercados?.length ?? null;
  const nValores = mercados?.reduce((t, m) => t + m.securities, 0) ?? null;
  const destacado = mejores?.puestos?.[0] ?? null;

  return (
    <div style={{ minHeight: "100vh", background: "var(--fondo)" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          padding: "18px 48px",
          borderBottom: "1px solid var(--borde)",
        }}
      >
        <MarcaConNombre />
        <nav style={{ display: "flex", gap: 26, marginLeft: 20 }}>
          <a href="#producto" style={{ color: "var(--tinta-2)", fontSize: 13 }}>
            Producto
          </a>
          <a href="#datos" style={{ color: "var(--tinta-2)", fontSize: 13 }}>
            Datos
          </a>
          <a href="#empezar" style={{ color: "var(--tinta-2)", fontSize: 13 }}>
            Empezar
          </a>
        </nav>
        <div style={{ flex: 1 }} />
        <Link href="/entrar" style={{ color: "var(--tinta-2)", fontSize: 13 }}>
          Entrar
        </Link>
        <Boton href="/entrar?modo=registro" principal>
          Probar LaLonja
        </Boton>
      </header>

      <section style={{ padding: "88px 48px 70px", maxWidth: 1240 }}>
        <div className="rotulo" style={{ letterSpacing: "0.2em", color: ORO }}>
          Análisis cuantitativo de mercados
          {nValores !== null ? ` · ${nValores} empresas` : null}
        </div>
        <h1
          style={{
            fontWeight: 600,
            fontSize: 64,
            lineHeight: 1.06,
            letterSpacing: "-0.03em",
            margin: "24px 0 0",
            maxWidth: "19ch",
          }}
        >
          Todo el mercado, ya ordenado.
        </h1>
        <p
          style={{
            fontSize: 19,
            color: "var(--tinta-3)",
            lineHeight: 1.6,
            margin: "26px 0 0",
            maxWidth: "60ch",
          }}
        >
          Invertir no falla por falta de datos: falla porque están dispersos en veinte pestañas.
          LaLonja reúne fundamentales, técnico y valoración en una sola lectura, y te dice de dónde
          sale cada número.
        </p>
        <div style={{ display: "flex", gap: 12, marginTop: 34, flexWrap: "wrap" }}>
          <Boton href="/rankings" principal grande>
            Explorar LaLonja
          </Boton>
          <Boton href="/entrar?modo=registro" grande>
            Crear cuenta gratis
          </Boton>
        </div>
        <div
          className="mono"
          style={{
            display: "flex",
            gap: 34,
            marginTop: 30,
            fontSize: 11,
            letterSpacing: "0.1em",
            color: "var(--tinta-4)",
            flexWrap: "wrap",
          }}
        >
          <span>SIN TARJETA</span>
          {nMercados !== null ? <span>{nMercados} MERCADOS</span> : null}
          <span>MOTOR REPRODUCIBLE</span>
        </div>
      </section>

      <section id="producto" style={{ padding: "0 48px 80px" }}>
        <div
          style={{
            border: "1px solid var(--borde-2)",
            borderRadius: 10,
            background: "var(--superficie)",
            overflow: "hidden",
            maxWidth: 1240,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "12px 16px",
              borderBottom: "1px solid var(--borde)",
            }}
          >
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                style={{ width: 9, height: 9, borderRadius: "50%", background: "var(--borde-2)" }}
              />
            ))}
            <span className="mono" style={{ fontSize: 10, color: "var(--tinta-4)", marginLeft: 12 }}>
              lalonja-trading.com/valores/{destacado?.ticker ?? "…"}
            </span>
          </div>

          {destacado ? (
            <MuestraReal puesto={destacado} fecha={mejores?.fecha_datos ?? null} />
          ) : (
            // El motor no ha respondido. Se dice; no se pinta una captura.
            <div style={{ padding: "48px 34px", color: "var(--tinta-3)" }}>
              <div className="rotulo" style={{ color: ORO }}>Muestra no disponible</div>
              <p style={{ margin: "12px 0 0", maxWidth: "70ch", lineHeight: 1.6 }}>
                Esta tarjeta enseña el valor mejor puntuado del día, tomado del motor en el momento
                de cargar la página. Ahora mismo el motor no responde, así que no hay nada que
                enseñar — y preferimos decirlo a poner una captura antigua.
              </p>
            </div>
          )}
        </div>
      </section>

      <section id="datos" style={{ padding: "0 48px 90px", maxWidth: 1240 }}>
        <h2 style={{ fontWeight: 600, fontSize: 34, margin: "0 0 12px" }}>
          Cuatro trabajos, una herramienta
        </h2>
        <p style={{ color: "var(--tinta-3)", fontSize: 16, maxWidth: "62ch", margin: "0 0 40px" }}>
          Cada pantalla responde a una pregunta concreta. Si no responde a ninguna, no existe.
        </p>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit,minmax(250px,1fr))",
            gap: 34,
          }}
        >
          {CARACTERISTICAS.map((f) => (
            <div key={f.n}>
              <div className="mono" style={{ fontSize: 11, letterSpacing: "0.14em", color: ORO }}>
                {f.n}
              </div>
              <div style={{ fontWeight: 600, fontSize: 19, marginTop: 14 }}>{f.titulo}</div>
              <p
                style={{
                  color: "var(--tinta-3)",
                  fontSize: 14,
                  lineHeight: 1.65,
                  margin: "10px 0 0",
                }}
              >
                {f.texto}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section id="empezar" style={{ padding: "0 48px 100px" }}>
        <div
          style={{
            borderTop: "1px solid var(--borde)",
            paddingTop: 60,
            maxWidth: 1240,
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "space-between",
            gap: 40,
            flexWrap: "wrap",
          }}
        >
          <div>
            <h2 style={{ fontWeight: 600, fontSize: 38, margin: 0, maxWidth: "18ch" }}>
              Empieza por una empresa que ya sigas.
            </h2>
            <p style={{ color: "var(--tinta-3)", fontSize: 16, margin: "16px 0 0", maxWidth: "54ch" }}>
              Gratis para diez valores en seguimiento. Sin tarjeta y sin periodo de prueba que
              caduca.
            </p>
          </div>
          <div style={{ display: "flex", gap: 12 }}>
            <Boton href="/rankings" principal grande>
              Explorar LaLonja
            </Boton>
            <Boton href="/entrar?modo=registro" grande>
              Crear cuenta
            </Boton>
          </div>
        </div>

        <footer
          className="mono"
          style={{
            maxWidth: 1240,
            marginTop: 70,
            paddingTop: 26,
            borderTop: "1px solid var(--borde)",
            display: "flex",
            justifyContent: "space-between",
            gap: 20,
            flexWrap: "wrap",
            fontSize: 10,
            letterSpacing: "0.12em",
            color: "var(--tinta-4)",
          }}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Marca tamano={12} /> © 2026 LALONJA TRADING
          </span>
          {/* §44. No es letra pequeña de relleno: determina cómo se puede
              presentar el producto. */}
          <span style={{ maxWidth: "80ch", lineHeight: 1.7 }}>
            INFORMACIÓN Y ANÁLISIS DE CARÁCTER GENERAL. NO ES ASESORAMIENTO FINANCIERO NI UNA
            RECOMENDACIÓN PERSONALIZADA. RENTABILIDADES PASADAS NO GARANTIZAN RENTABILIDADES
            FUTURAS.
          </span>
        </footer>
      </section>
    </div>
  );
}

/** La tarjeta de muestra, con el valor mejor puntuado de hoy. */
function MuestraReal({
  puesto,
  fecha,
}: {
  puesto: { ticker: string; nombre: string; mercado: string; sector: string | null; valor: number };
  fecha: string | null;
}) {
  return (
    <div
      style={{
        padding: "30px 34px",
        display: "grid",
        gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr)",
        gap: 30,
        alignItems: "center",
      }}
    >
      <div>
        <div className="rotulo" style={{ fontSize: 10, letterSpacing: "0.14em" }}>
          {puesto.mercado.toUpperCase()}
          {puesto.sector ? ` · ${puesto.sector.replace(/_/g, " ")}` : null}
        </div>
        <div style={{ fontWeight: 600, fontSize: 26, marginTop: 10 }}>{puesto.nombre}</div>
        <div className="mono" style={{ fontSize: 32, marginTop: 14 }}>
          {puesto.ticker}
        </div>
        <p style={{ color: "var(--tinta-3)", fontSize: 14, lineHeight: 1.6, margin: "22px 0 0" }}>
          El valor mejor puntuado del universo{fecha ? ` a ${fecha}` : null}. El score es un
          percentil dentro de su cohorte comparable, no una nota absoluta.
        </p>
        <Link href={`/valores/${encodeURIComponent(puesto.ticker)}`} style={{ fontSize: 14 }}>
          Ver su análisis completo →
        </Link>
      </div>
      <div
        style={{
          background: "var(--fondo)",
          border: "1px solid var(--borde-2)",
          borderLeft: `2px solid ${ORO}`,
          borderRadius: "var(--radio)",
          padding: 20,
        }}
      >
        <div className="rotulo" style={{ letterSpacing: "0.16em", color: ORO }}>
          Score LaLonja · {puesto.valor.toFixed(0)}
        </div>
        <p style={{ fontSize: 14, lineHeight: 1.6, margin: "12px 0 0", color: "var(--tinta-2)" }}>
          Mejor que el {puesto.valor.toFixed(0)}% de su cohorte —mismo mercado y mismo sector— en la
          última fecha calculada.
        </p>
      </div>
    </div>
  );
}
