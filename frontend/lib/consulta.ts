// La consulta de una fecha pasada, en el servidor.
//
// Modulo aparte para que `api.ts` y `sesion.ts` la compartan sin importarse el
// uno al otro.

import { headers } from "next/headers";

import { CABECERA_FECHA, fechaPasada } from "./fecha";

/** La fecha de consulta pasada de esta peticion (`?fecha=`), o `null` si es hoy. */
export function fechaConsulta(): string | null {
  try {
    return fechaPasada(headers().get(CABECERA_FECHA));
  } catch {
    return null;
  }
}

/** Añade `fecha` a una ruta GET de la API cuando se consulta una fecha pasada.
 *
 * Los endpoints con corte temporal (rankings, analisis, carteras, listas)
 * aceptan `?fecha=`; los que no lo tienen lo ignoran. Hacerlo aqui y no en cada
 * pagina evita que una pantalla se olvide y mezcle cifras de hoy en una vista
 * que dice ser del 31 de marzo. */
export function rutaConFecha(ruta: string, init?: RequestInit): string {
  const fecha = fechaConsulta();
  if (!fecha || (init?.method && init.method !== "GET") || /[?&]fecha=/.test(ruta)) return ruta;
  return `${ruta}${ruta.includes("?") ? "&" : "?"}fecha=${fecha}`;
}
