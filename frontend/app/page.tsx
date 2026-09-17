import Link from "next/link";

import { Medidor } from "@/components/piezas";
import { api, intenta, type Health, type Market, type RespuestaRanking } from "@/lib/api";

export const dynamic = "force-dynamic";

function Tabla({ titulo, datos, sufijo }: { titulo: string; datos: RespuestaRanking | null; sufijo?: string }) {
  if (!datos || datos.puestos.length === 0) {
    return (
      <section>
        <h2>{titulo}</h2>
        <p className="bloque-falta">
          Todavía no hay datos. Hace falta ejecutar <code>calculate_scores.py</code>
          {sufijo === "Δ" ? " en dos fechas separadas, para poder comparar." : "."}
        </p>
      </section>
    );
  }
  return (
    <section>
      <h2>
        {titulo}
        <span className="frescura"> del {datos.fecha_datos}</span>
      </h2>
      <div className="desliza">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Valor</th>
              <th>Mercado</th>
              <th>{sufijo === "Δ" ? "Cambio 30d" : "Score"}</th>
            </tr>
          </thead>
          <tbody>
            {datos.puestos.slice(0, 8).map((p) => (
              <tr key={p.ticker}>
                <td className="apunte">{p.posicion}</td>
                <td>
                  <Link href={`/valores/${p.ticker}`}>{p.ticker}</Link>{" "}
                  <span className="apunte">{p.nombre}</span>
                </td>
                <td className="apunte">{p.mercado.toUpperCase()}</td>
                <td>
                  {sufijo === "Δ" ? (
                    <span className="num" style={{ fontVariantNumeric: "tabular-nums" }}>
                      {p.valor > 0 ? "+" : ""}
                      {p.valor.toFixed(1)} pts
                    </span>
                  ) : (
                    <Medidor valor={p.valor} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default async function Panel() {
  const [salud, mercados, mejores, mejorados, caidas] = await Promise.all([
    intenta(api<Health>("/health")),
    intenta(api<Market[]>("/markets")),
    intenta(api<RespuestaRanking>("/rankings?tipo=mejor_score&n=8")),
    intenta(api<RespuestaRanking>("/rankings?tipo=mas_mejorado&n=8")),
    intenta(api<RespuestaRanking>("/rankings?tipo=mayor_caida&n=8")),
  ]);

  if (!salud && !mercados) {
    return (
      <div className="error">
        <h1>La API no responde</h1>
        <p>
          El motor está caído o todavía arrancando. Si acabas de desplegar, dale un
          minuto; si no, revisa <code>docker compose logs api</code>.
        </p>
      </div>
    );
  }

  const valores = (mercados ?? []).reduce((a, m) => a + m.securities, 0);

  return (
    <>
      <h1>Panel</h1>
      <p className="apunte">
        Los scores son <strong>percentiles dentro de una cohorte comparable</strong>,
        no notas absolutas: un 80 significa «mejor que el 80&nbsp;% de sus
        comparables», no «vale 80 sobre 100».
      </p>

      <div className="rejilla" style={{ marginTop: 18 }}>
        <div className="tarjeta">
          <div className="etiqueta">Servicio</div>
          <div className="cifra">{salud?.estado ?? "?"}</div>
          <div className="apunte">
            v{salud?.version ?? "—"} · {salud?.entorno ?? "—"}
          </div>
        </div>
        <div className="tarjeta">
          <div className="etiqueta">Mercados</div>
          <div className="cifra">{mercados?.length ?? "—"}</div>
          <div className="apunte">configurados</div>
        </div>
        <div className="tarjeta">
          <div className="etiqueta">Valores</div>
          <div className="cifra">{valores || "—"}</div>
          <div className="apunte">en el universo</div>
        </div>
        <div className="tarjeta">
          <div className="etiqueta">Puntuados</div>
          <div className="cifra">{mejores?.puestos.length ? "sí" : "no"}</div>
          <div className="apunte">
            {mejores?.fecha_datos ? `último cálculo: ${mejores.fecha_datos}` : "sin scores"}
          </div>
        </div>
      </div>

      <Tabla titulo="Mejor puntuados" datos={mejores} />
      <Tabla titulo="Los que más han mejorado" datos={mejorados} sufijo="Δ" />
      <Tabla titulo="Los que más han caído" datos={caidas} sufijo="Δ" />

      <h2>Mercados</h2>
      <div className="desliza">
        <table>
          <thead>
            <tr>
              <th>Mercado</th>
              <th>Divisa</th>
              <th>Clasificación</th>
              <th>Calendario</th>
              <th>Índice</th>
              <th className="num">Valores</th>
            </tr>
          </thead>
          <tbody>
            {(mercados ?? []).map((m) => (
              <tr key={m.id}>
                <td>
                  <strong>{m.id.toUpperCase()}</strong> <span className="apunte">{m.name}</span>
                </td>
                <td>{m.currency}</td>
                <td className="apunte">{m.classification}</td>
                <td className="apunte">{m.trading_calendar}</td>
                <td className="apunte">{m.benchmark ?? "—"}</td>
                <td className="num">{m.securities}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
