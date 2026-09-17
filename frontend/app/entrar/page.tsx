import Link from "next/link";
import { redirect } from "next/navigation";

import { entrar, registrar } from "@/app/acciones";
import { Formulario } from "@/components/formularios";
import { usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

export const metadata = { title: "Entrar · La Lonja" };

export default async function Entrar({
  searchParams,
}: {
  searchParams: Promise<{ modo?: string; desde?: string }>;
}) {
  const { modo } = await searchParams;
  if (await usuarioActual()) redirect("/cartera");

  const registro = modo === "registro";

  return (
    <>
      <h1>{registro ? "Crear una cuenta" : "Entrar"}</h1>

      <div className="tarjeta" style={{ maxWidth: 460 }}>
        <Formulario
          accion={registro ? registrar : entrar}
          etiquetaBoton={registro ? "Crear cuenta" : "Entrar"}
          className="formulario-vertical"
        >
          <label>
            Correo
            <input
              type="email"
              name="email"
              required
              autoComplete="email"
              placeholder="tu@correo.com"
            />
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
              <span className="apunte">Doce caracteres como mínimo.</span>
            ) : null}
          </label>
        </Formulario>
      </div>

      <p className="apunte" style={{ marginTop: 16 }}>
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

      {/* No es relleno: el plan decide cuántas carteras y listas caben, y
          enterarse al chocar con un 409 es peor que leerlo antes. */}
      <p className="apunte">
        Todas las cuentas empiezan en el plan gratuito: una cartera, una lista de
        seguimiento y diez valores en ella.
      </p>
    </>
  );
}
