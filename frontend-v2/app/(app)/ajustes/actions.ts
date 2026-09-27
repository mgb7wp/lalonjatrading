'use server';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { PERSONAL_COOKIE } from '@/lib/session';

export async function setPersonal(form: FormData) {
  const on = form.get('personal') === '1';
  cookies().set(PERSONAL_COOKIE, on ? '1' : '0', { httpOnly: true, sameSite: 'lax', path: '/', maxAge: 60 * 60 * 24 * 365 });
  redirect('/ajustes?guardado=1');
}
