// Entrar y crear cuenta (v2): pantalla partida, con los principios del motor en
// un panel azul acero oscuro y el formulario al lado.
//
// El formulario va por accion de servidor: funciona aunque el JavaScript no
// haya cargado. El error que devuelve la API se ensena tal cual, porque suele
// decir exactamente que pasa.

import { redirect } from "next/navigation";

import { entrar, registrar } from "@/app/acciones";
import { AvisoLegal } from "@/components/aviso-legal";
import { Formulario } from "@/components/formularios";
import { MarcaConNombre } from "@/components/marca";
import { usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

export const metadata = { title: "Entrar" };

const PRINCIPIOS = [
  "Un dato que falta se declara, no se rellena.",
  "El score es un percentil, no una nota.",
  "La IA redacta; el motor calcula.",
  "Toda cifra dice de qué fecha es.",
];

export default async function Entrar({ searchParams }: { searchParams: Promise<{ modo?: string }> }) {
  const { modo } = await searchParams;
  if (await usuarioActual()) redirect("/panel");
  const registro = modo === "registro";

  return (
    <div className="grid-canvas">
      <header className="pub-header">
        <a href="/" style={{ color: "inherit", textDecoration: "none" }} aria-label="LaLonja Trading, inicio">
          <MarcaConNombre />
        </a>
        <nav aria-label="Público">
          <a href="/mercados" className="desk-only">
            Mercados
          </a>
          <a href="/rankings" className="desk-only">
            Rankings
          </a>
        </nav>
      </header>

      <main className="split">
        <div className="split-panel">
          <div className="mono" style={{ fontSize: 11, letterSpacing: "0.16em", color: "var(--color-accent-300)" }}>
            PRINCIPIOS DEL MOTOR
          </div>
          <ol className="principles">
            {PRINCIPIOS.map((t, i) => (
              <li key={t}>
                <span className="n">{String(i + 1).padStart(2, "0")}</span>
                <span className="t">{t}</span>
              </li>
            ))}
          </ol>
          <div style={{ fontSize: 12, color: "var(--color-accent-200)" }}>Esto no es asesoramiento financiero.</div>
        </div>

        <div className="split-form">
          <div className="auth-form">
            <h1>{registro ? "Crear cuenta" : "Entrar"}</h1>
            <nav className="seg" aria-label="Modo" style={{ justifySelf: "start" }}>
              <a className={`seg-opt${registro ? "" : " is-on"}`} href="/entrar" aria-current={registro ? undefined : "page"}>
                Entrar
              </a>
              <a className={`seg-opt${registro ? " is-on" : ""}`} href="/entrar?modo=registro" aria-current={registro ? "page" : undefined}>
                Crear cuenta
              </a>
            </nav>
            <Formulario
              accion={registro ? registrar : entrar}
              etiquetaBoton={registro ? "Crear cuenta" : "Entrar"}
              className="auth-form"
              claseBoton="btn btn-primary btn-tall"
            >
              <div className="field">
                <label htmlFor="email">Correo electrónico</label>
                <input className="input" id="email" type="email" name="email" required autoComplete="email" />
              </div>
              <div className="field">
                <label htmlFor="contrasena">Contraseña</label>
                <input
                  className="input"
                  id="contrasena"
                  type="password"
                  name="contrasena"
                  required
                  minLength={registro ? 12 : undefined}
                  autoComplete={registro ? "new-password" : "current-password"}
                  aria-describedby="pista-contrasena"
                />
                <div className="field-hint" id="pista-contrasena">
                  Mínimo 12 caracteres
                </div>
              </div>
            </Formulario>
            <a href="/restablecer" style={{ fontSize: 13 }}>
              ¿Has olvidado la contraseña?
            </a>
          </div>
        </div>
      </main>

      <AvisoLegal fijo={false} />
    </div>
  );
}
