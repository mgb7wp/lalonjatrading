import Link from "next/link";
import { redirect } from "next/navigation";

import { crearCartera } from "@/app/acciones";
import { Cabecera } from "@/components/armazon";
import { Formulario } from "@/components/formularios";
import { apiSesion, usuarioActual } from "@/lib/sesion";
import type { CarteraResumen } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata = { title: "Carteras · La Lonja" };

export default async function Carteras() {
  if (!(await usuarioActual())) redirect("/entrar?desde=/cartera");

  let carteras: CarteraResumen[] = [];
  let fallo: string | null = null;
  try {
    carteras = await apiSesion<CarteraResumen[]>("/portfolios");
  } catch (e) {
    fallo = e instanceof Error ? e.message : "no se han podido leer las carteras";
  }

  return (
    <>
      <Cabecera miga="Cartera" />
      <div className="pagina">
      <h1>Mis carteras</h1>

      {fallo ? <p className="bloque-falta">No disponible. {fallo}</p> : null}

      {carteras.length === 0 && !fallo ? (
        <p className="vacio">Todavía no tienes ninguna cartera.</p>
      ) : (
        <div className="rejilla">
          {carteras.map((c) => (
            <Link key={c.id} href={`/cartera/${c.id}`} className="tarjeta tarjeta-enlace">
              <div className="etiqueta">{c.divisa_base}</div>
              <div className="cifra">{c.nombre}</div>
              <span className="apunte">
                {c.transacciones} {c.transacciones === 1 ? "transacción" : "transacciones"}
              </span>
            </Link>
          ))}
        </div>
      )}

      <section>
        <h2>Crear una cartera</h2>
        <Formulario accion={crearCartera} etiquetaBoton="Crear">
          <label>
            Nombre
            <input type="text" name="nombre" required maxLength={120} placeholder="Largo plazo" />
          </label>
          <label>
            Divisa base
            <select name="divisa_base" defaultValue="EUR">
              <option value="EUR">EUR</option>
              <option value="USD">USD</option>
            </select>
          </label>
        </Formulario>
      </section>

      {/* El valor de la cartera se deriva de las transacciones en cada
          consulta: no hay nada guardado que se pueda quedar desfasado. Se dice
          porque explica por qué no existe un botón de "recalcular". */}
      <p className="apunte">
        El valor, el P&amp;L y los pesos se calculan a partir de tus transacciones cada
        vez que abres la cartera. Corregir una operación antigua corrige todo lo que
        depende de ella, sin recalcular nada a mano.
      </p>
      </div>
    </>
  );
}
