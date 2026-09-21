import Link from "next/link";

import { Cabecera } from "@/components/armazon";
import { usuarioActual } from "@/lib/sesion";

import { api, intenta, type Encontrado } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata = { title: "Buscar · La Lonja" };

export default async function Buscar({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q = "" } = await searchParams;
  const aguja = q.trim();

  const filas = aguja
    ? ((await intenta(
        api<Encontrado[]>(`/stocks?q=${encodeURIComponent(aguja)}&n=30`),
      )) ?? null)
    : [];

  const dentro = (await usuarioActual()) !== null;

  return (
    <>
      {dentro ? <Cabecera miga="Buscar" /> : null}
      <div className="pagina">
      <h1>Buscar un valor</h1>

      <form className="formulario" method="get">
        <label>
          Ticker, nombre o ISIN
          <input type="search" name="q" defaultValue={aguja} placeholder="ACS, Inditex, US0378…" />
        </label>
        <button type="submit">Buscar</button>
      </form>

      {filas === null ? (
        <p className="bloque-falta">No disponible. El buscador no ha respondido.</p>
      ) : !aguja ? (
        <p className="apunte">Escribe algo para buscar.</p>
      ) : filas.length === 0 ? (
        <p className="vacio">Ningún valor coincide con «{aguja}».</p>
      ) : (
        <div className="desliza">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Nombre</th>
                <th>Mercado</th>
                <th>Sector</th>
                <th>Divisa</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((f) => (
                <tr key={`${f.mercado}-${f.ticker}`}>
                  <td>
                    <Link href={`/valores/${encodeURIComponent(f.ticker)}`}>{f.ticker}</Link>
                    {/* D-12: entre la acción local y su ADR, la principal es la
                        que de verdad se puede operar. Se marca en lugar de
                        esconder la otra. */}
                    {f.linea_principal ? null : (
                      <span className="apunte"> · línea secundaria</span>
                    )}
                  </td>
                  <td>{f.nombre}</td>
                  <td>{f.mercado.toUpperCase()}</td>
                  <td>{f.sector ?? "—"}</td>
                  <td>{f.divisa}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      </div>
    </>
  );
}
