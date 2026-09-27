// Restablecer la contrasena (v2), en dos pasos.
//
// Paso 1: pedir el enlace. Paso 2 (`?token=`): fijar la contrasena nueva desde
// el enlace del correo. El backend aun no envia correos (FASE 15), y la pagina
// lo dice en lugar de prometer un correo que no va a llegar.

import { confirmarReinicio, pedirReinicio } from "@/app/acciones";
import { AvisoLegal } from "@/components/aviso-legal";
import { Formulario } from "@/components/formularios";
import { MarcaConNombre } from "@/components/marca";
import { Esquinas } from "@/components/piezas";

export const dynamic = "force-dynamic";

export const metadata = { title: "Restablecer contraseña" };

export default async function Restablecer({ searchParams }: { searchParams: Promise<{ token?: string; enviado?: string }> }) {
  const { token, enviado } = await searchParams;
  const paso2 = Boolean(token);

  return (
    <div className="grid-canvas">
      <header className="pub-header">
        <a href="/" style={{ color: "inherit", textDecoration: "none" }} aria-label="LaLonja Trading, inicio">
          <MarcaConNombre />
        </a>
        <nav aria-label="Público">
          <a className="btn btn-secondary" href="/entrar">
            Entrar
          </a>
        </nav>
      </header>

      <main className="reset-wrap">
        <div className="blueprint reset-card">
          <Esquinas />
          <div className="kicker">{paso2 ? "PASO 2 · DESDE EL ENLACE" : "PASO 1"}</div>
          <h2>{paso2 ? "Nueva contraseña" : "Pide un enlace"}</h2>
          {enviado && !paso2 ? (
            <div role="status" className="alert alert-ok">
              <strong>Petición recibida.</strong> Si existe una cuenta con ese correo, se genera un enlace válido durante
              30 minutos. El envío por correo todavía no está activo.
            </div>
          ) : null}
          {paso2 ? (
            <Formulario accion={confirmarReinicio} etiquetaBoton="Guardar contraseña" className="reset-form" claseBoton="btn btn-primary btn-tall">
              <input type="hidden" name="token" value={token} />
              <div className="field">
                <label htmlFor="contrasena">Nueva contraseña (mínimo 12 caracteres)</label>
                <input className="input" id="contrasena" type="password" name="contrasena" minLength={12} required autoComplete="new-password" />
              </div>
              <div className="field">
                <label htmlFor="repetida">Repítela</label>
                <input className="input" id="repetida" type="password" name="repetida" minLength={12} required autoComplete="new-password" />
              </div>
            </Formulario>
          ) : (
            <Formulario accion={pedirReinicio} etiquetaBoton="Enviar enlace" className="reset-form" claseBoton="btn btn-primary btn-tall">
              <div className="field">
                <label htmlFor="email">Correo electrónico</label>
                <input className="input" id="email" type="email" name="email" required autoComplete="email" />
              </div>
            </Formulario>
          )}
          <p style={{ fontSize: 13, margin: 0, color: "var(--tinta-3)" }}>
            {paso2 ? "Al guardarla entrarás con la contraseña nueva." : "Por seguridad, la respuesta es la misma exista o no la cuenta."}
          </p>
        </div>
      </main>

      <AvisoLegal fijo={false} />
    </div>
  );
}
