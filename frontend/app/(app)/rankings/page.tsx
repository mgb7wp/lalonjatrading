import Link from "next/link";

import { Medidor } from "@/components/piezas";
import { api, intenta, type Market, type RespuestaRanking } from "@/lib/api";

export const dynamic = "force-dynamic";

const NOMBRES: Record<string, string> = {
  mejor_score: "Mejor puntuados",
  peor_score: "Peor puntuados",
  mas_mejorado: "Los que más han mejorado",
  mayor_caida: "Los que más han caído",
  mejor_fundamental: "Mejor fundamental",
  mejor_tecnico: "Mejor técnico",
  mejor_momentum: "Mejor momentum",
  menor_riesgo: "Menor riesgo",
  mejor_valoracion: "Mejor valoración",
  mejor_calidad: "Mejor calidad",
};

const VARIACION = new Set(["mas_mejorado", "mayor_caida"]);

export default async function Rankings({
  searchParams,
}: {
  searchParams: Promise<{ tipo?: string; mercado?: string }>;
}) {
  const { tipo = "mejor_score", mercado = "" } = await searchParams;
  const consulta = new URLSearchParams({ tipo, n: "20" });
  if (mercado) consulta.set("mercado", mercado);

  const [datos, mercados, catalogo] = await Promise.all([
    intenta(api<RespuestaRanking>(`/rankings?${consulta}`)),
    intenta(api<Market[]>("/markets")),
    intenta(api<string[]>("/rankings/catalogo")),
  ]);

  const esVariacion = VARIACION.has(tipo);

  return (
    <>
      <h1>Rankings</h1>
      <p className="apunte">
        Una empresa, una fila: cuando un ADR y su acción local conviven en el
        universo, se conserva la línea principal. Contarlas dos veces concentra una
        cartera sin que se note.
      </p>

      {/* Filtros en una sola fila sobre la tabla, sin JavaScript: enlaces. Una
          página que solo lee no necesita estado en el cliente. */}
      <form className="formulario" style={{ margin: "18px 0" }}>
        <div>
          <label htmlFor="tipo">Ranking</label>
          <select id="tipo" name="tipo" defaultValue={tipo}>
            {(catalogo ?? Object.keys(NOMBRES)).map((r) => (
              <option key={r} value={r}>
                {NOMBRES[r] ?? r}
              </option>
            ))}
          </select>
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
        <button type="submit">Ver</button>
      </form>

      <h2>
        {NOMBRES[tipo] ?? tipo}
        {datos?.fecha_datos ? <span className="frescura"> del {datos.fecha_datos}</span> : null}
      </h2>

      {!datos || datos.puestos.length === 0 ? (
        <p className="bloque-falta">
          {esVariacion
            ? "Sin dos fotos del score no se puede medir una variación. Hacen falta al menos dos cálculos separados en el tiempo."
            : "Todavía no hay valores puntuados. Ejecuta calculate_scores.py."}
        </p>
      ) : (
        <div className="desliza">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Valor</th>
                <th>Mercado</th>
                <th>Sector</th>
                <th>{esVariacion ? "Cambio 30d" : "Valor"}</th>
                {esVariacion ? <th className="num">Antes</th> : null}
                {esVariacion ? <th>Score actual</th> : null}
              </tr>
            </thead>
            <tbody>
              {datos.puestos.map((p) => (
                <tr key={p.ticker}>
                  <td className="apunte">{p.posicion}</td>
                  <td>
                    <Link href={`/valores/${p.ticker}`}>
                      <strong>{p.ticker}</strong>
                    </Link>
                    <br />
                    <span className="apunte">{p.nombre}</span>
                  </td>
                  <td className="apunte">{p.mercado.toUpperCase()}</td>
                  <td className="apunte">{p.sector ?? "—"}</td>
                  <td>
                    {esVariacion ? (
                      <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 640 }}>
                        {p.valor > 0 ? "+" : ""}
                        {p.valor.toFixed(1)} pts
                      </span>
                    ) : (
                      <Medidor valor={p.valor} />
                    )}
                  </td>
                  {esVariacion ? <td className="num apunte">{p.anterior?.toFixed(1) ?? "—"}</td> : null}
                  {esVariacion ? (
                    <td>
                      <Medidor valor={p.overall} />
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
