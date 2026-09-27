'use server';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

// Acciones de servidor de autenticación. Funcionan sin JavaScript: validan, llaman a la API
// y redirigen con ?error=<código> para que la página muestre el aviso.
// Contrato supuesto: POST {API}/auth/login|register|reset-request|reset → 200 { token } / 4xx.

const MIN_PASSWORD = 12;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SESSION_COOKIE = 'lalonja_sesion';

async function post(path: string, body: unknown): Promise<{ ok: boolean; status: number; json: any }> {
  const base = process.env.LALONJA_API_URL?.replace(/\/$/, '');
  if (!base) return { ok: false, status: 0, json: null };
  try {
    const res = await fetch(base + path, { method: 'POST', cache: 'no-store', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    return { ok: res.ok, status: res.status, json: await res.json().catch(() => null) };
  } catch {
    return { ok: false, status: -1, json: null };
  }
}

function setSession(token: string) {
  cookies().set(SESSION_COOKIE, token, { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/' });
}

export async function authenticate(form: FormData) {
  const mode = form.get('modo') === 'registro' ? 'registro' : 'entrar';
  const email = String(form.get('email') ?? '').trim();
  const password = String(form.get('password') ?? '');
  const back = (error: string) => redirect(`/entrar?modo=${mode}&error=${error}`);

  if (!EMAIL_RE.test(email)) back('correo');
  if (password.length < MIN_PASSWORD) back(mode === 'registro' ? 'corta' : 'credenciales');

  const r = await post(mode === 'registro' ? '/auth/register' : '/auth/login', { email, password });
  if (r.status === 0) back('no_configurado');
  if (r.status === -1 || r.status >= 500) back('servicio');
  if (!r.ok) back(mode === 'registro' && r.status === 409 ? 'existe' : 'credenciales');
  if (typeof r.json?.token === 'string') setSession(r.json.token);
  redirect('/panel');
}

export async function requestReset(form: FormData) {
  const email = String(form.get('email') ?? '').trim();
  if (!EMAIL_RE.test(email)) redirect('/restablecer?error=correo');
  const r = await post('/auth/reset-request', { email });
  if (r.status === 0) redirect('/restablecer?error=no_configurado');
  if (r.status === -1 || r.status >= 500) redirect('/restablecer?error=servicio');
  // Misma respuesta exista o no la cuenta.
  redirect('/restablecer?enviado=1');
}

export async function resetPassword(form: FormData) {
  const token = String(form.get('token') ?? '');
  const password = String(form.get('password') ?? '');
  const repeat = String(form.get('repeat') ?? '');
  const back = (e: string) => redirect(`/restablecer?token=${encodeURIComponent(token)}&error=${e}`);
  if (password.length < MIN_PASSWORD) back('corta');
  if (password !== repeat) back('distintas');
  const r = await post('/auth/reset', { token, password });
  if (r.status === 0) back('no_configurado');
  if (r.status === -1 || r.status >= 500) back('servicio');
  if (!r.ok) back('caducado');
  redirect('/entrar?restablecida=1');
}
