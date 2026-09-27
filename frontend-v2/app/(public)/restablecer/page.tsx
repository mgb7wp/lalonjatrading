import { Corners } from '@/components/Blueprint';
import { requestReset, resetPassword } from '@/lib/auth-actions';

export const metadata = { title: 'Restablecer contraseña' };

const ERRORS: Record<string, [string, string]> = {
  caducado: ['El enlace ha caducado.', 'Pide uno nuevo.'],
  corta: ['Contraseña demasiado corta.', 'Necesita al menos 12 caracteres.'],
  distintas: ['Las contraseñas no coinciden.', 'Escribe la misma en los dos campos.'],
  correo: ['Revisa el correo.', 'No parece una dirección de correo válida.'],
  servicio: ['El servicio no responde.', 'Inténtalo de nuevo en unos minutos.'],
  no_configurado: ['No disponible.', 'El servicio de autenticación no está configurado en este entorno.'],
};

export default function Restablecer({ searchParams }: { searchParams: { token?: string; error?: string; enviado?: string } }) {
  const step2 = !!searchParams.token;
  const err = searchParams.error ? ERRORS[searchParams.error] ?? ERRORS.servicio : null;
  return (
    <main className="reset-wrap">
      <form className="blueprint reset-card" action={step2 ? resetPassword : requestReset}>
        <Corners />
        <div className="kicker">{step2 ? 'PASO 2 · DESDE EL ENLACE' : 'PASO 1'}</div>
        <h2>{step2 ? 'Nueva contraseña' : 'Pide un enlace'}</h2>
        {err && (
          <div role="alert" className="alert">
            <strong>{err[0]}</strong> {err[1]}
          </div>
        )}
        {searchParams.enviado && !step2 && (
          <div role="status" className="alert alert-ok">
            <strong>Enviado.</strong> Revisa tu correo.
          </div>
        )}
        {step2 ? (
          <>
            <input type="hidden" name="token" value={searchParams.token} />
            <div className="field">
              <label htmlFor="password">Nueva contraseña (mínimo 12 caracteres)</label>
              <input className="input" id="password" type="password" name="password" minLength={12} required autoComplete="new-password" />
            </div>
            <div className="field">
              <label htmlFor="repeat">Repítela</label>
              <input className="input" id="repeat" type="password" name="repeat" minLength={12} required autoComplete="new-password" />
            </div>
          </>
        ) : (
          <div className="field">
            <label htmlFor="email">Correo electrónico</label>
            <input className="input" id="email" type="email" name="email" required autoComplete="email" />
          </div>
        )}
        <button className="btn btn-primary blueprint btn-tall" type="submit">
          <Corners />
          {step2 ? 'Guardar contraseña' : 'Enviar enlace'}
        </button>
        <p style={{ fontSize: 13, margin: 0, color: 'var(--color-neutral-700)' }}>
          {step2 ? 'Se cerrarán las demás sesiones abiertas.' : 'Si existe una cuenta con ese correo, recibirás un enlace válido durante 30 minutos.'}
        </p>
      </form>
    </main>
  );
}
