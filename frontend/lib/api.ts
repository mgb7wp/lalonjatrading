// Unico punto por el que el frontend habla con la API.
//
// Un `fetch` suelto en un componente es como empieza a haber tres formas
// distintas de tratar un 401 y dos URLs base distintas en produccion.

// La URL base no es la misma segun quien haga la peticion, y confundirlas es el
// fallo clasico de un Next en Docker:
//
// - En el servidor (componentes de servidor, que es lo que usamos hoy) hablamos
//   con la API por la red interna de Docker: `http://api:8000`. Se lee en
//   tiempo de ejecucion, asi que la misma imagen vale para cualquier despliegue.
// - En el navegador esa URL no existe. Ahi vamos a mismo origen (`""`) y es el
//   proxy inverso el que enruta `/api/...` a la API. De paso no hay CORS.
//
// `NEXT_PUBLIC_*` se incrusta al construir la imagen; `API_URL` no. Por eso lo
// de servidor NO lleva ese prefijo.
const BASE =
  typeof window === "undefined"
    ? (process.env.API_URL ?? "http://localhost:8000")
    : (process.env.NEXT_PUBLIC_API_URL ?? "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(ruta: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${ruta}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(res.status, `${init?.method ?? "GET"} ${ruta} -> ${res.status}`);
  }
  return (await res.json()) as T;
}

export type Market = {
  id: string;
  currency: string;
  classification: string;
  ticker_suffix: string;
  trading_calendar: string;
  benchmark: string | null;
  securities: number;
};

export type Health = {
  estado: "ok" | "degradado" | "caido";
  version: string;
  entorno: string;
  dependencias: { nombre: string; estado: string; detalle: string }[];
};
