"use server";

// Todo lo que ESCRIBE pasa por aqui.
//
// Son acciones de servidor, no `fetch` desde el navegador, y esa es la
// consecuencia directa de guardar el token en una cookie `httpOnly`: si el
// JavaScript de la pagina no puede leer el token, tampoco puede llamar a la API
// con el. Llama el servidor.
//
// El efecto secundario es bueno: no hay estado de sesion duplicado en el
// cliente que se pueda desincronizar, y los formularios funcionan aunque el
// JavaScript no haya cargado todavia.
//
// **Ninguna accion lanza una excepcion hacia la pagina.** Devuelven
// `{ error }` con el texto que manda la API, porque «has alcanzado el maximo de
// 1 carteras de tu plan» es exactamente lo que el usuario necesita leer, y una
// pantalla de error generica lo tira a la basura.

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import {
  COOKIE_ACCESO,
  COOKIE_REFRESCO,
  DIAS_REFRESCO,
  apiSesion,
  mensaje,
  opcionesCookie,
  type Tokens,
} from "@/lib/sesion";

const BASE = process.env.API_URL ?? "http://localhost:8000";

export type Resultado = { error?: string };

/** Traduce cualquier fallo a `{ error }` con el texto de la API. */
async function intentar(f: () => Promise<unknown>): Promise<Resultado> {
  try {
    await f();
    return {};
  } catch (e) {
    return { error: e instanceof Error ? e.message : "no se ha podido completar" };
  }
}

async function guardarSesion(tokens: Tokens) {
  const tarro = await cookies();
  // La cookie de acceso caduca CON el token: asi, cuando desaparece, el
  // middleware sabe que toca refrescar en lugar de mandar a la API un token
  // muerto y recibir un 401 por cada bloque de la pagina.
  tarro.set(COOKIE_ACCESO, tokens.acceso, { ...opcionesCookie, maxAge: tokens.caduca_en });
  tarro.set(COOKIE_REFRESCO, tokens.refresco, {
    ...opcionesCookie,
    maxAge: DIAS_REFRESCO * 24 * 3600,
  });
}

async function credenciales(ruta: string, datos: FormData): Promise<Resultado> {
  const email = String(datos.get("email") ?? "").trim();
  const contrasena = String(datos.get("contrasena") ?? "");
  if (!email || !contrasena) return { error: "hacen falta el correo y la contraseña" };

  const res = await fetch(`${BASE}/api/v1${ruta}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, contrasena }),
    cache: "no-store",
  });
  if (!res.ok) return { error: await mensaje(res) };
  await guardarSesion((await res.json()) as Tokens);
  return {};
}

export async function entrar(_previo: Resultado, datos: FormData): Promise<Resultado> {
  const r = await credenciales("/auth/login", datos);
  if (r.error) return r;
  redirect("/cartera");
}

export async function registrar(_previo: Resultado, datos: FormData): Promise<Resultado> {
  const r = await credenciales("/auth/register", datos);
  if (r.error) return r;
  redirect("/cartera");
}

export async function salir(): Promise<void> {
  const tarro = await cookies();
  const refresco = tarro.get(COOKIE_REFRESCO)?.value;
  // Se avisa a la API para que REVOQUE el token. Borrar la cookie sin revocar
  // deja un token valido suelto: quien lo tenga sigue dentro aunque el usuario
  // crea que ha cerrado sesion.
  if (refresco) {
    await fetch(`${BASE}/api/v1/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresco }),
      cache: "no-store",
    }).catch(() => undefined);
  }
  tarro.delete(COOKIE_ACCESO);
  tarro.delete(COOKIE_REFRESCO);
  redirect("/");
}

// --- Carteras --------------------------------------------------------------

export async function crearCartera(_previo: Resultado, datos: FormData): Promise<Resultado> {
  const r = await intentar(() =>
    apiSesion("/portfolios", {
      method: "POST",
      body: JSON.stringify({
        nombre: String(datos.get("nombre") ?? "").trim(),
        divisa_base: String(datos.get("divisa_base") ?? "EUR"),
      }),
    }),
  );
  revalidatePath("/cartera");
  return r;
}

export async function borrarCartera(datos: FormData): Promise<void> {
  const id = String(datos.get("id") ?? "");
  await apiSesion(`/portfolios/${id}`, { method: "DELETE" }).catch(() => undefined);
  revalidatePath("/cartera");
  redirect("/cartera");
}

export async function anadirTransaccion(
  _previo: Resultado,
  datos: FormData,
): Promise<Resultado> {
  const id = String(datos.get("cartera") ?? "");
  // Los importes viajan como TEXTO, no como numero de JavaScript. El backend
  // los lee en Decimal; convertirlos aqui a `number` los pasaria por coma
  // flotante y un 0,1 + 0,2 acabaria descuadrando el P&L por unos centimos que
  // nadie sabria de donde salen.
  const cuerpo: Record<string, unknown> = {
    ticker: String(datos.get("ticker") ?? "").trim().toUpperCase(),
    tipo: String(datos.get("tipo") ?? "buy"),
    cantidad: String(datos.get("cantidad") ?? "0"),
    precio: String(datos.get("precio") ?? "0"),
    comisiones: String(datos.get("comisiones") || "0"),
    impuestos: String(datos.get("impuestos") || "0"),
    fecha: String(datos.get("fecha") ?? ""),
  };
  const fx = String(datos.get("fx") ?? "").trim();
  if (fx) cuerpo.fx = fx;

  const r = await intentar(() =>
    apiSesion(`/portfolios/${id}/transactions`, {
      method: "POST",
      body: JSON.stringify(cuerpo),
    }),
  );
  revalidatePath(`/cartera/${id}`);
  return r;
}

export async function borrarTransaccion(datos: FormData): Promise<void> {
  const cartera = String(datos.get("cartera") ?? "");
  const id = String(datos.get("id") ?? "");
  await apiSesion(`/portfolios/${cartera}/transactions/${id}`, { method: "DELETE" }).catch(
    () => undefined,
  );
  revalidatePath(`/cartera/${cartera}`);
}

// --- Seguimiento -----------------------------------------------------------

export async function crearLista(_previo: Resultado, datos: FormData): Promise<Resultado> {
  const r = await intentar(() =>
    apiSesion("/watchlists", {
      method: "POST",
      body: JSON.stringify({ nombre: String(datos.get("nombre") || "Seguimiento") }),
    }),
  );
  revalidatePath("/seguimiento");
  return r;
}

export async function anadirASeguimiento(
  _previo: Resultado,
  datos: FormData,
): Promise<Resultado> {
  const ticker = String(datos.get("ticker") ?? "").trim().toUpperCase();
  const r = await intentar(async () => {
    // Si no hay ninguna lista todavia, se crea una en vez de obligar a pasar
    // por otra pantalla: "anadir a seguimiento" tiene que funcionar a la
    // primera, y la lista es un detalle de organizacion, no una decision.
    let lista = String(datos.get("lista") ?? "");
    if (!lista) {
      const listas = await apiSesion<{ id: number }[]>("/watchlists");
      lista = String(
        listas[0]?.id ??
          (
            await apiSesion<{ id: number }>("/watchlists", {
              method: "POST",
              body: JSON.stringify({ nombre: "Seguimiento" }),
            })
          ).id,
      );
    }
    await apiSesion(`/watchlists/${lista}/items`, {
      method: "POST",
      body: JSON.stringify({ ticker }),
    });
  });
  revalidatePath("/seguimiento");
  revalidatePath(`/valores/${ticker}`);
  return r;
}

export async function quitarDeSeguimiento(datos: FormData): Promise<void> {
  const lista = String(datos.get("lista") ?? "");
  const ticker = String(datos.get("ticker") ?? "");
  await apiSesion(`/watchlists/${lista}/items/${encodeURIComponent(ticker)}`, {
    method: "DELETE",
  }).catch(() => undefined);
  revalidatePath("/seguimiento");
}

export async function borrarLista(datos: FormData): Promise<void> {
  const id = String(datos.get("id") ?? "");
  await apiSesion(`/watchlists/${id}`, { method: "DELETE" }).catch(() => undefined);
  revalidatePath("/seguimiento");
  redirect("/seguimiento");
}
