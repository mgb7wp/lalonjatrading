import 'server-only';
import { cookies, headers } from 'next/headers';
import { parsePastDate } from './format';

export const PERSONAL_COOKIE = 'lalonja_uso_personal';

/** Uso personal: desactivado salvo que el usuario lo active en Ajustes. */
export function isPersonal(): boolean {
  return cookies().get(PERSONAL_COOKIE)?.value === '1';
}

/** Fecha de consulta pasada (?fecha=YYYY-MM-DD), reenviada por el middleware para que la lean los layouts. */
export function pastDate(): string | null {
  return parsePastDate(headers().get('x-lalonja-fecha'));
}
