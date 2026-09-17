// Renueva el token de acceso cuando caduca, sin que el usuario se entere.
//
// ## Por que aqui y no al pintar la pagina
//
// Un componente de servidor puede LEER cookies pero no escribirlas. Si el
// refresco se intentara al renderizar, el token nuevo no se podria guardar y
// habria que refrescar otra vez en la peticion siguiente, y en la siguiente. El
// middleware si puede escribir en la respuesta, asi que es el unico sitio donde
// esto funciona de verdad.
//
// ## Cuando refresca
//
// Solo cuando la cookie de acceso ha DESAPARECIDO —caduca sola, con el mismo
// plazo que el token que lleva dentro— y todavia hay cookie de refresco. No se
// refresca "por si acaso" en cada peticion: el refresco ROTA, asi que cada uno
// invalida el anterior, y renovar sin necesidad multiplica las ocasiones de
// pisarse a si mismo.
//
// **Limitacion conocida, y no la escondo:** si dos navegaciones caen a la vez
// justo cuando el acceso acaba de caducar, las dos intentan refrescar y la
// segunda usa un token que la primera ya ha revocado; el usuario sale a la
// pantalla de entrada. Se mitiga excluyendo del middleware todo lo que no sea
// una navegacion de documento —los estaticos y los datos de Next no pasan por
// aqui—, con lo que en la practica queda una peticion por navegacion. La
// solucion completa es un candado compartido, y eso es una pieza de
// infraestructura que no toca en esta fase.

import { NextResponse, type NextRequest } from "next/server";

const COOKIE_ACCESO = "lonja_acceso";
const COOKIE_REFRESCO = "lonja_refresco";
const DIAS_REFRESCO = 30;

const BASE = process.env.API_URL ?? "http://localhost:8000";

export async function middleware(peticion: NextRequest) {
  const acceso = peticion.cookies.get(COOKIE_ACCESO)?.value;
  const refresco = peticion.cookies.get(COOKIE_REFRESCO)?.value;
  if (acceso || !refresco) return NextResponse.next();

  const opciones = {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    secure: process.env.NODE_ENV === "production",
  };

  try {
    const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresco }),
      cache: "no-store",
    });
    if (!res.ok) {
      // El refresco ya no vale (caducado, revocado o robado y rotado). Se
      // borran las dos cookies: dejar la de refresco haria que cada navegacion
      // reintentara un token muerto.
      const fuera = NextResponse.next();
      fuera.cookies.delete(COOKIE_ACCESO);
      fuera.cookies.delete(COOKIE_REFRESCO);
      return fuera;
    }
    const tokens = (await res.json()) as {
      acceso: string;
      refresco: string;
      caduca_en: number;
    };

    // La cookie se escribe en la respuesta Y en la peticion: sin lo segundo, el
    // componente que se renderiza en ESTA misma peticion sigue leyendo la
    // cookie vieja y la pagina sale sin sesion aunque el refresco haya ido bien.
    // El ORDEN importa: primero se escribe en la peticion, y solo despues se
    // construye la respuesta a partir de sus cabeceras. Al reves, la copia de
    // cabeceras se hace antes de la mutacion y no lleva la cookie nueva.
    peticion.cookies.set(COOKIE_ACCESO, tokens.acceso);
    const siguiente = NextResponse.next({
      request: { headers: peticion.headers },
    });
    siguiente.cookies.set(COOKIE_ACCESO, tokens.acceso, {
      ...opciones,
      maxAge: tokens.caduca_en,
    });
    siguiente.cookies.set(COOKIE_REFRESCO, tokens.refresco, {
      ...opciones,
      maxAge: DIAS_REFRESCO * 24 * 3600,
    });
    return siguiente;
  } catch {
    // Si la API no responde, seguir sin sesion es mejor que devolver un error:
    // las paginas publicas siguen funcionando.
    return NextResponse.next();
  }
}

export const config = {
  // Solo navegaciones de documento. Los estaticos y los assets de Next no
  // necesitan sesion, y hacerlos pasar por aqui multiplicaria por veinte los
  // intentos de refresco de una sola carga de pagina.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg|.*\\.(?:png|jpg|svg|css|js)$).*)"],
};
