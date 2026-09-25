// La sesion del usuario, SIEMPRE en el servidor.
//
// ## Por que el token no pisa el navegador
//
// La alternativa habitual —guardar el JWT en `localStorage` y mandarlo desde
// JavaScript— convierte cualquier XSS en un robo de sesion: el token es legible
// por cualquier script que llegue a ejecutarse en la pagina, incluido el de una
// dependencia comprometida. Aqui el token va en una cookie `httpOnly`, que el
// JavaScript de la pagina NO PUEDE LEER, y las llamadas a la API las hace el
// servidor de Next. El navegador nunca ve un token.
//
// El coste es que todo lo que escribe pasa por una accion de servidor en lugar
// de por un `fetch` en el cliente. Para una aplicacion con formularios es un
// coste pequeno; para un token de sesion de una herramienta financiera, la
// diferencia no es pequena.
//
// `sameSite: lax` y no `strict` porque `strict` rompe la vuelta desde un enlace
// externo —el usuario aterriza sin sesion y parece que se ha cerrado sola—, y
// `lax` ya corta el CSRF en las peticiones que importan, que son las POST.

import { cookies } from "next/headers";

import { ApiError } from "./api";

export const COOKIE_ACCESO = "lonja_acceso";
export const COOKIE_REFRESCO = "lonja_refresco";

/** 30 dias. El token de refresco decide de verdad cuanto dura; la cookie solo
 * tiene que no caducar antes que el. */
export const DIAS_REFRESCO = 30;

const BASE = process.env.API_URL ?? "http://localhost:8000";

export type Tokens = {
  acceso: string;
  refresco: string;
  tipo: string;
  caduca_en: number;
};

export type Usuario = {
  id: number;
  email: string;
  plan: string;
  activo: boolean;
  perfil_riesgo: string | null;
  horizonte: string | null;
  ultimo_acceso: string | null;
};

export const opcionesCookie = {
  httpOnly: true,
  sameSite: "lax" as const,
  path: "/",
  // En desarrollo se sirve por http y una cookie `secure` no llegaria nunca,
  // con el efecto desconcertante de que el login "funciona" y la sesion no
  // aparece. En produccion va detras de Cloudflare, siempre https.
  secure: process.env.NODE_ENV === "production",
};

/** El token de acceso de esta peticion, si lo hay. */
export async function tokenActual(): Promise<string | null> {
  return (await cookies()).get(COOKIE_ACCESO)?.value ?? null;
}

/** Llama a la API con la sesion del usuario.
 *
 * Un 401 se propaga como `ApiError` en lugar de redirigir desde aqui: quien
 * pinta la pagina es el que sabe si conviene mandar al login o ensenar el
 * bloque vacio, y una redireccion escondida en la capa de red es de las cosas
 * que mas cuesta depurar despues. */
export async function apiSesion<T>(ruta: string, init?: RequestInit): Promise<T> {
  const token = await tokenActual();
  const res = await fetch(`${BASE}/api/v1${ruta}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(res.status, await mensaje(res));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** El `detail` que manda la API, que casi siempre dice exactamente que pasa.
 *
 * Sustituirlo por un "ha ocurrido un error" generico tira informacion que el
 * backend se ha molestado en redactar para quien la lee. */
export async function mensaje(res: Response): Promise<string> {
  try {
    const cuerpo = await res.json();
    const d = cuerpo?.detail;
    if (typeof d === "string") return d;
    // 422 de Pydantic: llega una lista de errores por campo.
    if (Array.isArray(d) && d.length) return d.map((e) => e.msg ?? "").join("; ");
  } catch {
    /* cuerpo no JSON */
  }
  return `la petición falló con un ${res.status}`;
}

/** Quien esta dentro, o `null`. No lanza: se usa en la cabecera de todas las
 * paginas y un fallo ahi no puede tumbar una pagina publica. */
export async function usuarioActual(): Promise<Usuario | null> {
  if (!(await tokenActual())) return null;
  try {
    return await apiSesion<Usuario>("/auth/me");
  } catch {
    return null;
  }
}
