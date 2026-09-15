import { api, type Health, type Market } from "@/lib/api";

// MVP: demuestra que el frontend habla con la API y que los mercados salen de
// la configuración del motor, no de una lista escrita aquí (§3).
export default async function Home() {
  let health: Health | null = null;
  let markets: Market[] = [];
  let error: string | null = null;

  try {
    [health, markets] = await Promise.all([
      api<Health>("/health"),
      api<Market[]>("/markets"),
    ]);
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <p>
        No se ha podido contactar con la API: <code>{error}</code>
        <br />
        ¿Está levantada? <code>docker compose up</code>
      </p>
    );
  }

  return (
    <>
      <h1>Estado</h1>
      <p>
        Servicio: <strong>{health?.estado}</strong> (v{health?.version},{" "}
        {health?.entorno})
      </p>
      <ul>
        {health?.dependencias.map((d) => (
          <li key={d.nombre}>
            {d.nombre}: {d.estado}
            {d.detalle ? ` — ${d.detalle}` : ""}
          </li>
        ))}
      </ul>

      <h2>Mercados</h2>
      <table cellPadding={6} style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th align="left">Mercado</th>
            <th align="left">Divisa</th>
            <th align="left">Clasificación</th>
            <th align="left">Calendario</th>
            <th align="left">Benchmark</th>
            <th align="right">Valores</th>
          </tr>
        </thead>
        <tbody>
          {markets.map((m) => (
            <tr key={m.id} style={{ borderTop: "1px solid #eee" }}>
              <td>{m.id.toUpperCase()}</td>
              <td>{m.currency}</td>
              <td>{m.classification}</td>
              <td>{m.trading_calendar}</td>
              <td>{m.benchmark ?? "—"}</td>
              <td align="right">{m.securities}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
