// Unico punto por el que el frontend habla con la API.
//
// Un `fetch` suelto en un componente es como empieza a haber tres formas
// distintas de tratar un 401 y dos URLs base distintas en produccion.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
