import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { anadirTransaccion, borrarCartera, borrarTransaccion } from "@/app/acciones";
import { BotonAccion, Formulario } from "@/components/formularios";
import { Medidor, numero } from "@/components/piezas";
import { ApiError, type TransaccionFila, type Valoracion } from "@/lib/api";
import { apiSesion, usuarioActual } from "@/lib/sesion";

export const dynamic = "force-dynamic";

/** Los importes llegan como cadena y se pintan como cadena formateada.
 *
 * NO se pasan por `Number`: el backend los calcula en Decimal justo para que no
 * arrastren el error de la coma flotante, y convertirlos aqui para formatearlos
 * lo reintroduce en el ultimo metro. `Intl` sabe formatear una cadena numerica.
 */
function dinero(v: string | null, divisa: string): string {
  if (v === null) return "—";
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: divisa,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number.parseFloat(v));
}

function porcentaje(v: number | null): string {
  return v === null ? "—" : `${(v * 100).toFixed(1)} %`;
}

/** Signo explicito y clase de color. El color nunca viaja solo: el signo va
 * delante para que se lea sin interpretarlo. */
function Resultado({ valor, divisa }: { valor: string | null; divisa: string }) {
  if (valor === null) return <span className="apunte">—</span>;
  const n = Number.parseFloat(valor);
  const clase = n > 0 ? "sube" : n < 0 ? "baja" : "";
  return (
    <span className={clase}>
      {n > 0 ? "+" : ""}
      {dinero(valor, divisa)}
    </span>
  );
}

export default async function Cartera({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!(await usuarioActual())) redirect(`/entrar?desde=/cartera/${id}`);

  let v: Valoracion;
  let transacciones: TransaccionFila[] = [];
  try {
    v = await apiSesion<Valoracion>(`/portfolios/${id}`);
    transacciones = await apiSesion<TransaccionFila[]>(`/portfolios/${id}/transactions`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  const d = v.divisa_base;
  const hoy = new Date().toISOString().slice(0, 10);

  return (
    <>
      <p className="apunte">
        <Link href="/cartera">← Mis carteras</Link>
      </p>
      <h1>{v.nombre}</h1>

      <div className="rejilla">
        <div className="tarjeta">
          <div className="etiqueta">Valor de mercado</div>
          <div className="cifra">{dinero(v.totales.valor, d)}</div>
          <div className="apunte">coste {dinero(v.totales.coste, d)}</div>
        </div>
        <div className="tarjeta">
          <div className="etiqueta">No realizado</div>
          <div className="cifra">
            <Resultado valor={v.totales.no_realizado} divisa={d} />
          </div>
        </div>
        <div className="tarjeta">
          <div className="etiqueta">Realizado</div>
          <div className="cifra">
            <Resultado valor={v.totales.realizado} divisa={d} />
          </div>
          <div className="apunte">dividendos {dinero(v.totales.dividendos, d)}</div>
        </div>
        <div className="tarjeta">
          <div className="etiqueta">Resultado total</div>
          <div className="cifra">
            <Resultado valor={v.totales.total} divisa={d} />
          </div>
          <div className="apunte">realizado + no realizado + dividendos − gastos</div>
        </div>
      </div>

      {v.sin_valorar.length ? (
        // No se valoran a coste, que fingiría que no se han movido. Se declaran.
        <p className="bloque-falta">
          Sin precio conocido, y por eso fuera de los totales de mercado:{" "}
          <strong>{v.sin_valorar.join(", ")}</strong>. No se valoran a coste, porque eso
          daría por hecho que no se han movido.
        </p>
      ) : null}

      <section>
        <h2>Posiciones</h2>
        {v.posiciones.length === 0 ? (
          <p className="vacio">Sin posiciones abiertas.</p>
        ) : (
          <div className="desliza">
            <table>
              <thead>
                <tr>
                  <th>Valor</th>
                  <th className="num">Cantidad</th>
                  <th className="num">Coste medio</th>
                  <th className="num">Precio</th>
                  <th className="num">Valor</th>
                  <th className="num">No realizado</th>
                  <th className="num">Peso</th>
                  <th>Score</th>
                </tr>
              </thead>
              <tbody>
                {v.posiciones.map((p) => (
                  <tr key={p.ticker}>
                    <td>
                      <Link href={`/valores/${encodeURIComponent(p.ticker)}`}>{p.ticker}</Link>
                      <div className="apunte">{p.nombre}</div>
                    </td>
                    <td className="num">{numero(Number.parseFloat(p.cantidad), 0)}</td>
                    <td className="num">{dinero(p.coste_medio, d)}</td>
                    <td className="num">{p.precio ? numero(Number.parseFloat(p.precio)) : "—"}</td>
                    <td className="num">{dinero(p.valor, d)}</td>
                    <td className="num">
                      <Resultado valor={p.no_realizado} divisa={d} />
                    </td>
                    <td className="num">
                      {porcentaje(p.peso)}
                      {p.objetivo !== null ? (
                        <div className="apunte">objetivo {porcentaje(p.objetivo)}</div>
                      ) : null}
                    </td>
                    <td>
                      <Medidor valor={p.score} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="rejilla">
        <section className="tarjeta">
          <h2>Diversificación</h2>
          <p>
            {v.diversificacion.posiciones}{" "}
            {v.diversificacion.posiciones === 1 ? "posición" : "posiciones"}, pero{" "}
            <strong>
              {v.diversificacion.posiciones_efectivas === null
                ? "—"
                : numero(v.diversificacion.posiciones_efectivas, 2)}
            </strong>{" "}
            efectivas.
          </p>
          {/* El número de posiciones miente en cuanto una pesa mucho más que las
              otras. Las efectivas (1/HHI) dicen la verdad, y se explica para que
              no sea un número esotérico. */}
          <p className="apunte">
            Las efectivas son el inverso del índice de concentración: cuatro posiciones
            iguales dan 4; cuatro con el 85 % en una dan 1,35. La mayor pesa{" "}
            {porcentaje(v.diversificacion.mayor_peso)}.
          </p>
        </section>

        <section className="tarjeta">
          <h2>Score medio</h2>
          <p>
            <Medidor valor={v.score_medio.valor} />
          </p>
          {/* La cobertura no es un detalle: sin ella, una media sobre el 20 % del
              valor se lee como la media de toda la cartera. */}
          <p className="apunte">
            Ponderado por peso, sobre el {porcentaje(v.score_medio.cobertura)} del valor de
            la cartera. Lo que no tiene score se queda fuera en lugar de contarse como
            un 50 neutro.
          </p>
        </section>
      </div>

      <div className="rejilla">
        <Exposicion titulo="Por sector" datos={v.exposicion_sector} />
        <Exposicion titulo="Por país" datos={v.exposicion_pais} />
      </div>

      <section>
        <h2>Registrar una operación</h2>
        <Formulario accion={anadirTransaccion} etiquetaBoton="Registrar">
          <input type="hidden" name="cartera" value={id} />
          <label>
            Ticker
            <input type="text" name="ticker" required placeholder="AAPL" />
          </label>
          <label>
            Tipo
            <select name="tipo" defaultValue="buy">
              <option value="buy">Compra</option>
              <option value="sell">Venta</option>
              <option value="dividend">Dividendo</option>
              <option value="fee">Comisión</option>
            </select>
          </label>
          <label>
            Cantidad
            <input type="text" inputMode="decimal" name="cantidad" required placeholder="100" />
          </label>
          <label>
            Precio
            <input type="text" inputMode="decimal" name="precio" required placeholder="150" />
          </label>
          <label>
            Comisiones
            <input type="text" inputMode="decimal" name="comisiones" placeholder="0" />
          </label>
          <label>
            Fecha
            <input type="date" name="fecha" required defaultValue={hoy} max={hoy} />
          </label>
          <label>
            Cambio a {d}
            <input type="text" inputMode="decimal" name="fx" placeholder="el del día" />
          </label>
        </Formulario>
        {/* Se explica por qué pedimos el cambio: el del extracto del broker es
            el que se pagó de verdad, y el de referencia es una aproximación. */}
        <p className="apunte">
          Si dejas el cambio en blanco se usa el tipo de referencia de ese día. Si lo
          rellenas manda el tuyo, que es lo que de verdad te cobró el bróker.
        </p>
      </section>

      <section>
        <h2>Operaciones</h2>
        {transacciones.length === 0 ? (
          <p className="vacio">Todavía no has registrado ninguna.</p>
        ) : (
          <div className="desliza">
            <table>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Valor</th>
                  <th>Tipo</th>
                  <th className="num">Cantidad</th>
                  <th className="num">Precio</th>
                  <th className="num">Comisiones</th>
                  <th className="num">Cambio</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {transacciones.map((t) => (
                  <tr key={t.id}>
                    <td>{t.fecha}</td>
                    <td>{t.ticker}</td>
                    <td>{TIPOS[t.tipo] ?? t.tipo}</td>
                    <td className="num">{numero(Number.parseFloat(t.cantidad), 0)}</td>
                    <td className="num">
                      {numero(Number.parseFloat(t.precio))} {t.divisa}
                    </td>
                    <td className="num">{numero(Number.parseFloat(t.comisiones))}</td>
                    <td className="num">{t.fx ? numero(Number.parseFloat(t.fx), 4) : "—"}</td>
                    <td>
                      <BotonAccion
                        accion={borrarTransaccion}
                        campos={{ cartera: id, id: t.id }}
                        confirmar="¿Borrar esta operación? La cartera se recalcula entera."
                      >
                        Borrar
                      </BotonAccion>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* En un <div> y no en un <p>: `BotonAccion` pinta un <form>, y el HTML
          no permite un <form> dentro de un <p> — el navegador cierra el párrafo
          por su cuenta y construye un DOM distinto del que escribimos. Aquí no
          llegó a romper nada (lo comprobé volviendo a ponerlo y no aparece
          ningún error), pero es markup inválido y el navegador que lo arregle
          por nosotros no es una garantía. */}
      <div className="apunte" style={{ marginTop: 28 }}>
        <BotonAccion
          accion={borrarCartera}
          campos={{ id }}
          confirmar="¿Borrar la cartera entera, con todas sus operaciones?"
        >
          Borrar esta cartera
        </BotonAccion>
      </div>
    </>
  );
}

const TIPOS: Record<string, string> = {
  buy: "Compra",
  sell: "Venta",
  dividend: "Dividendo",
  fee: "Comisión",
};

function Exposicion({ titulo, datos }: { titulo: string; datos: Record<string, number> }) {
  const filas = Object.entries(datos);
  return (
    <section className="tarjeta">
      <h2>{titulo}</h2>
      {filas.length === 0 ? (
        <p className="vacio">Sin posiciones valoradas.</p>
      ) : (
        <table>
          <tbody>
            {filas.map(([clave, peso]) => (
              <tr key={clave}>
                <td>{clave}</td>
                <td className="num">{porcentaje(peso)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
