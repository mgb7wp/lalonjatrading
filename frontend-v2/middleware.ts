import { NextResponse, type NextRequest } from 'next/server';

// Los layouts de App Router no reciben searchParams: reenviamos ?fecha= como cabecera
// para que la cabecera, la franja de consulta pasada y la navegación la conozcan.
export function middleware(req: NextRequest) {
  const h = new Headers(req.headers);
  h.delete('x-lalonja-fecha');
  const fecha = req.nextUrl.searchParams.get('fecha');
  if (fecha) h.set('x-lalonja-fecha', fecha);
  return NextResponse.next({ request: { headers: h } });
}

export const config = { matcher: ['/((?!_next/|icon.png|favicon.ico).*)'] };
