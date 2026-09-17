"use client";

// Formularios que hablan con las acciones de servidor.
//
// Son clientes solo por una razon: ensenar el error que devuelve la accion y
// deshabilitar el boton mientras se envia. El token sigue sin pisar el
// navegador; lo que viaja es el FormData, igual que en un formulario de toda la
// vida. De hecho, sin JavaScript el formulario sigue enviando y funcionando: lo
// unico que se pierde es el mensaje en linea.

import { useFormState, useFormStatus } from "react-dom";
import type { ReactNode } from "react";

import type { Resultado } from "@/app/acciones";

function Boton({ children }: { children: ReactNode }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} aria-busy={pending}>
      {pending ? "Enviando…" : children}
    </button>
  );
}

/** Formulario con estado de error, sobre una accion de servidor. */
export function Formulario({
  accion,
  etiquetaBoton,
  children,
  className = "formulario",
}: {
  accion: (previo: Resultado, datos: FormData) => Promise<Resultado>;
  etiquetaBoton: string;
  children: ReactNode;
  className?: string;
}) {
  const [estado, enviar] = useFormState(accion, {});
  return (
    <form action={enviar} className={className}>
      {children}
      <Boton>{etiquetaBoton}</Boton>
      {estado.error ? (
        // `role="alert"` para que un lector de pantalla lo anuncie: un mensaje
        // que aparece sin avisar no existe para quien no lo esta mirando.
        <p className="error" role="alert">
          {mayuscula(estado.error)}
        </p>
      ) : null}
    </form>
  );
}

/** Boton suelto que dispara una accion sin datos que rellenar (borrar, salir). */
export function BotonAccion({
  accion,
  children,
  campos = {},
  confirmar,
}: {
  accion: (datos: FormData) => Promise<void>;
  children: ReactNode;
  campos?: Record<string, string | number>;
  confirmar?: string;
}) {
  return (
    <form
      action={accion}
      style={{ display: "inline" }}
      onSubmit={(e) => {
        // Borrar una cartera se lleva por delante todas sus transacciones. Se
        // pregunta antes; si no hay JavaScript, no se pregunta y se borra, que
        // es el comportamiento de un formulario normal.
        if (confirmar && !window.confirm(confirmar)) e.preventDefault();
      }}
    >
      {Object.entries(campos).map(([k, v]) => (
        <input key={k} type="hidden" name={k} value={String(v)} />
      ))}
      <button type="submit" className="enlace-boton">
        {children}
      </button>
    </form>
  );
}

function mayuscula(texto: string): string {
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}
