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

/** Envuelve una llamada para que un fallo de red no tumbe la pagina entera.
 *
 * Una pagina con cuatro bloques en la que uno no responde tiene que enseñar los
 * otros tres y decir que falta el cuarto. Tirar los cuatro por uno es perder
 * informacion que si tenemos. */
export async function intenta<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch {
    return null;
  }
}

export type Market = {
  id: string;
  name: string;
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

// --- Bloques del analisis (§27) -------------------------------------------

export type Frescura = { as_of: string; dias: number };

export type Bloque<T> = {
  disponible: boolean;
  motivo: string | null;
  frescura: Frescura | null;
  datos: T | null;
};

export type Valor = {
  ticker: string;
  name: string;
  market_id: string;
  currency_code: string;
  sector: string | null;
  active: boolean;
  is_primary_listing: boolean;
};

export type Precio = {
  fecha: string;
  cierre: number;
  apertura: number | null;
  maximo: number | null;
  minimo: number | null;
  volumen: number | null;
  fuente: string | null;
};

export type Fundamental = {
  fin_periodo: string;
  fecha_publicacion: string;
  origen_pit: string;
  periodo: string;
  ventas: number | null;
  ebit: number | null;
  beneficio_neto: number | null;
  patrimonio_neto: number | null;
  deuda_neta: number | null;
  flujo_caja_libre: number | null;
  roe: number | null;
  margen_operativo: number | null;
  divisa_reporte: string | null;
};

export type Tecnico = {
  fecha: string;
  rsi_14: number | null;
  sma_50: number | null;
  sma_200: number | null;
  atr_14: number | null;
  beta: number | null;
  fuerza_relativa: number | null;
};

export type Puntuacion = {
  fecha: string;
  modelo: string;
  overall: number;
  cohorte: string;
  n_cohorte: number;
  pilares: Record<string, number | null>;
  pilares_no_disponibles: Record<string, string>;
  subscores: Record<string, number | null>;
};

export type Senal = {
  fecha: string;
  senal: string;
  motivo: string;
  detalle: Record<string, unknown> | null;
  regimen: string | null;
  confianza: number | null;
  horizonte_dias: number | null;
  autor: string;
  metodologia: string | null;
};

export type Factor = { nombre: string; valor: number; nivel: string };

export type Explicacion = {
  a_favor: Factor[];
  en_contra: Factor[];
  cambio_30d: Record<string, number>;
  cambio_no_comparable: string[];
};

export type Analisis = {
  ticker: string;
  fecha_corte: string;
  valor: Valor;
  precio: Bloque<Precio>;
  fundamental: Bloque<Fundamental>;
  tecnico: Bloque<Tecnico>;
  score: Bloque<Puntuacion>;
  senal: Bloque<Senal>;
  explicacion: Bloque<Explicacion>;
  prediccion: Bloque<Record<string, unknown>>;
};

// --- Rankings (§32) y screener (§31) --------------------------------------

export type Puesto = {
  posicion: number;
  ticker: string;
  nombre: string;
  mercado: string;
  sector: string | null;
  valor: number;
  overall: number | null;
  anterior: number | null;
};

export type RespuestaRanking = {
  ranking: string;
  fecha: string;
  fecha_datos: string | null;
  modelo: string;
  mercado: string | null;
  n: number;
  puestos: Puesto[];
};

export type FilaScreener = {
  ticker: string;
  nombre: string;
  mercado: string;
  sector: string | null;
  overall: number | null;
  senal: string | null;
  campos: Record<string, number | null>;
};

export type RespuestaScreener = {
  fecha: string;
  fecha_datos: string | null;
  modelo: string;
  n: number;
  total: number;
  filas: FilaScreener[];
};

export type Filtro = { campo: string; operador: string; valor: unknown };

export function screener(cuerpo: Record<string, unknown>): Promise<RespuestaScreener> {
  return api<RespuestaScreener>("/screener", {
    method: "POST",
    body: JSON.stringify(cuerpo),
  });
}
