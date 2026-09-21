import Link from "next/link";

import { InsigniaSenal, Medidor, nombre } from "@/components/piezas";
import { api, intenta, type Market, type RespuestaScreener } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Campos que se ofrecen en el formulario.
 *
 * La lista completa la publica la API en `/screener/campos`; aquí se enseñan
 * los que tienen sentido como filtro rápido. El resto sigue disponible por API
 * para quien la use directamente. */
const FILTRABLES = [
  "overall",
  "fundamental",
  "tecnico",
  "riesgo",
  "valoracion",
  "momentum",
  "calidad",
  "crecimiento",
];

const ETIQUETAS: Record<string, string> = {
  overall: "Score global",
  fundamental: "Fundamental",
  tecnico: "Técnico",
  riesgo: "Riesgo",
  valoracion: "Valoración",
  momentum: "Momentum",
  calidad: "Calidad",
  crecimiento: "Crecimiento",
};

export default async function Screener({
  searchParams,
}: {
  searchParams: Promise<{ campo?: string; minimo?: string; mercado?: string }>;
}) {
  const { campo = "overall", minimo = "70", mercado = "" } = await searchParams;

  const umbral = Number.parseFloat(minimo);
  const filtros: { campo: string; operador: string; valor: unknown }[] = [];
  if (Number.isFinite(umbral)) {
    filtros.push({ campo, operador: "gte", valor: umbral });
  }
  if (mercado) filtros.push({ campo: "mercado", operador: "eq", valor: mercado });

  const [datos, mercados] = await Promise.all([
    intenta(
      api<RespuestaScreener>("/screener", {
        method: "POST",
        body: JSON.stringify({ filtros, orden: campo, n: 50 }),
      }),
    ),
    intenta(api<Market[]>("/markets")),
  ]);

  return (
    <>
      <h1>Screener</h1>
      <p className="apunte">
        Filtra el universo por percentil. Recuerda que un 70 en «riesgo» significa
        estar entre los <strong>mejores</strong> de su cohorte en riesgo, no tener
        mucho: todos los percentiles van en la misma dirección, más alto es mejor.
      </p>

      <form className="formulario" style={{ margin: "18px 0" }}>
        <div>
          <label htmlFor="campo">Campo</label>
          <select id="campo" name="campo" defaultValue={campo}>
            {FILTRABLES.map((c) => (
              <option key={c} value={c}>
                {ETIQUETAS[c] ?? c}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="minimo">Percentil mínimo</label>
          <input
            id="minimo"
            name="minimo"
            type="number"
            min={0}
            max={100}
            step={5}
            defaultValue={minimo}
            style={{ width: 96 }}
          />
        </div>
        <div>
          <label htmlFor="mercado">Mercado</label>
          <select id="mercado" name="mercado" defaultValue={mercado}>
            <option value="">Todos</option>
            {(mercados ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.id.toUpperCase()} — {m.name}
              </option>
            ))}
          </select>
        </div>
        <button type="submit">Filtrar</button>
      </form>

      {!datos ? (
        <p className="bloque-falta">El motor no ha respondido.</p>
      ) : datos.filas.length === 0 ? (
        <p className="bloque-falta">
          Ningún valor cumple el filtro
          {datos.fecha_datos ? ` con los scores del ${datos.fecha_datos}` : ", y todavía no hay scores calculados"}.
        </p>
      ) : (
        <>
          <h2>
            {datos.n} de {datos.total} que cumplen
            <span className="frescura"> · scores del {datos.fecha_datos}</span>
          </h2>
          <div className="desliza">
            <table>
              <thead>
                <tr>
                  <th>Valor</th>
                  <th>Mercado</th>
                  <th>Sector</th>
                  <th>Señal</th>
                  <th style={{ minWidth: 150 }}>{ETIQUETAS[campo] ?? nombre(campo)}</th>
                  {/* Sin esto, filtrar por `overall` pinta la misma columna dos
                      veces con los mismos numeros. */}
                  {campo === "overall" ? null : (
                    <th style={{ minWidth: 150 }}>Score global</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {datos.filas.map((f) => (
                  <tr key={f.ticker}>
                    <td>
                      <Link href={`/valores/${f.ticker}`}>
                        <strong>{f.ticker}</strong>
                      </Link>
                      <br />
                      <span className="apunte">{f.nombre}</span>
                    </td>
                    <td className="apunte">{f.mercado.toUpperCase()}</td>
                    <td className="apunte">{f.sector ?? "—"}</td>
                    <td>
                      <InsigniaSenal senal={f.senal} />
                    </td>
                    <td>
                      <Medidor valor={f.campos[campo] ?? null} />
                    </td>
                    {campo === "overall" ? null : (
                      <td>
                        <Medidor valor={f.overall} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
