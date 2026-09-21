// Entrar y crear cuenta. Implementa la pantalla `login` del diseno: la mitad
// izquierda con el formulario y la derecha con lo que se obtiene.
//
// Las ventajas que enumera el diseno mencionan "20 preguntas al mes al AI
// Analyst" y "historico desde 2005". Ninguna de las dos es cierta hoy, asi que
// se sustituyen por las que si: los limites del plan gratuito salen de
// `backend/limites.py` y son los que de verdad se aplican.

import Link from "next/link";
import { redirect } from "next/navigation";

import { entrar, registrar } from "@/app/acciones";
import { Formulario } from "@/components/formularios";
import { MarcaConNombre } from "@/components/marca";
import { usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

export const metadata = { title: "Entrar · LaLonja" };

const VENTAJAS = [
  {
    n: "01",
    titulo: "Diez valores en seguimiento",
    texto: "Con score, variación a 30 días y señal, y el motivo escrito cuando algo no se puede calcular.",
  },
  {
    n: "02",
    titulo: "Una cartera, derivada de tus operaciones",
    texto:
      "Valor, P&L con FIFO y comisiones, exposición por sector y país. Corregir una compra antigua corrige todo lo que depende de ella.",
  },
  {
    n: "03",
    titulo: "Descubrir sin límite de consultas",
    texto: "Filtra el universo por score, crecimiento, rentabilidad, valoración o riesgo.",
  },
  {
    n: "04",
    titulo: "Cada número con su procedencia",
    texto:
      "De qué fecha es, de qué fuente sale y si la fecha de publicación es real o estimada. Lo que no se sabe, se dice.",
  },
];

export default async function Entrar({
  searchParams,
}: {
  searchParams: Promise<{ modo?: string; desde?: string }>;
}) {
  const { modo } = await searchParams;
  if (await usuarioActual()) redirect("/panel");
  const registro = modo === "registro";

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)",
        minHeight: "100vh",
        animation: "fadeUp .25s ease",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", padding: "60px 8vw" }}>
        <Link href="/" style={{ color: "inherit", width: "fit-content" }}>
          <MarcaConNombre tamano={24} />
        </Link>

        <h1 style={{ fontSize: 32, margin: "46px 0 0" }}>
          {registro ? "Crear cuenta" : "Entrar"}
        </h1>
        <p style={{ color: "var(--tinta-3)", margin: "10px 0 0" }}>
          {registro ? "Gratis para diez valores. Sin tarjeta." : "Con la cuenta que ya tienes."}
        </p>

        <div style={{ maxWidth: 400, marginTop: 32 }}>
          <Formulario
            accion={registro ? registrar : entrar}
            etiquetaBoton={registro ? "Crear cuenta" : "Entrar"}
            className="formulario-vertical"
          >
            <label>
              Email
              <input type="email" name="email" required autoComplete="email" placeholder="tu@email.com" />
            </label>
            <label>
              Contraseña
              <input
                type="password"
                name="contrasena"
                required
                minLength={registro ? 12 : undefined}
                autoComplete={registro ? "new-password" : "current-password"}
              />
              {registro ? (
                <span className="apunte" style={{ letterSpacing: "normal", textTransform: "none" }}>
                  Doce caracteres como mínimo.
                </span>
              ) : null}
            </label>
          </Formulario>

          <p className="apunte" style={{ marginTop: 18 }}>
            {registro ? (
              <>
                ¿Ya tienes cuenta? <Link href="/entrar">Entrar</Link>
              </>
            ) : (
              <>
                ¿No tienes cuenta? <Link href="/entrar?modo=registro">Crear una</Link>
              </>
            )}
          </p>
        </div>

        <Link href="/" className="apunte" style={{ marginTop: 40, width: "fit-content" }}>
          ← Volver a la web
        </Link>
      </div>

      <div
        style={{
          background: "var(--superficie)",
          borderLeft: "1px solid var(--borde)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "60px 6vw",
          gap: 26,
        }}
      >
        <div className="rotulo" style={{ letterSpacing: "0.2em", color: "var(--oro)" }}>
          Lo que obtienes
        </div>
        {VENTAJAS.map((v) => (
          <div key={v.n} style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
            <span className="mono" style={{ fontSize: 11, color: "var(--oro)", marginTop: 2 }}>
              {v.n}
            </span>
            <div>
              <div style={{ fontSize: 15 }}>{v.titulo}</div>
              <div
                style={{
                  fontSize: 13,
                  color: "var(--tinta-3)",
                  marginTop: 5,
                  lineHeight: 1.55,
                  maxWidth: "46ch",
                }}
              >
                {v.texto}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
