import { Corners } from '@/components/Blueprint';
import { authenticate } from '@/lib/auth-actions';

export const metadata = { title: 'Entrar' };

const PRINCIPLES = [
  'Un dato que falta se declara, no se rellena.',
  'El score es un percentil, no una nota.',
  'La IA redacta; el motor calcula.',
  'Toda cifra dice de qué fecha es.',
];

const ERRORS: Record<string, [string, string]> = {
  credenciales: ['No hemos podido entrar.', 'Correo o contraseña incorrectos; por seguridad no indicamos cuál.'],
  correo: ['Revisa el correo.', 'No parece una dirección de correo válida.'],
  corta: ['Contraseña demasiado corta.', 'Necesita al menos 12 caracteres.'],
  existe: ['No hemos podido crear la cuenta.', 'Ya hay una cuenta con ese correo. Entra o restablece la contraseña.'],
  servicio: ['El servicio no responde.', 'Inténtalo de nuevo en unos minutos.'],
  no_configurado: ['Acceso no disponible.', 'El servicio de autenticación no está configurado en este entorno.'],
};

export default function Entrar({ searchParams }: { searchParams: { modo?: string; error?: string; restablecida?: string } }) {
  const registro = searchParams.modo === 'registro';
  const err = searchParams.error ? ERRORS[searchParams.error] ?? ERRORS.servicio : null;
  return (
    <main className="split">
      <div className="split-panel">
        <div className="mono" style={{ fontSize: 11, letterSpacing: '.16em', color: 'var(--color-accent-300)' }}>PRINCIPIOS DEL MOTOR</div>
        <ol className="principles">
          {PRINCIPLES.map((t, i) => (
            <li key={t}>
              <span className="n">{String(i + 1).padStart(2, '0')}</span>
              <span className="t">{t}</span>
            </li>
          ))}
        </ol>
        <div style={{ fontSize: 12, color: 'var(--color-accent-200)' }}>Esto no es asesoramiento financiero.</div>
      </div>
      <div className="split-form">
        <form className="auth-form" action={authenticate}>
          <h1>{registro ? 'Crear cuenta' : 'Entrar'}</h1>
          <nav className="seg" aria-label="Modo" style={{ justifySelf: 'start' }}>
            <a className={`seg-opt${registro ? '' : ' is-on'}`} href="/entrar" aria-current={registro ? undefined : 'page'}>Entrar</a>
            <a className={`seg-opt${registro ? ' is-on' : ''}`} href="/entrar?modo=registro" aria-current={registro ? 'page' : undefined}>Crear cuenta</a>
          </nav>
          <input type="hidden" name="modo" value={registro ? 'registro' : 'entrar'} />
          {searchParams.restablecida && (
            <div role="status" className="alert alert-ok">
              <strong>Contraseña guardada.</strong> Ya puedes entrar con la nueva.
            </div>
          )}
          {err && (
            <div role="alert" className="alert">
              <strong>{err[0]}</strong> {err[1]}
            </div>
          )}
          <div className="field">
            <label htmlFor="email">Correo electrónico</label>
            <input className="input" id="email" type="email" name="email" autoComplete="email" required />
          </div>
          <div className="field">
            <label htmlFor="password">Contraseña</label>
            <input
              className="input"
              id="password"
              type="password"
              name="password"
              minLength={12}
              required
              autoComplete={registro ? 'new-password' : 'current-password'}
              aria-describedby="pw-hint"
              style={searchParams.error === 'corta' ? { borderColor: 'var(--color-text)' } : undefined}
            />
            <div className="field-hint" id="pw-hint">Mínimo 12 caracteres</div>
          </div>
          <button className="btn btn-primary blueprint btn-tall" type="submit">
            <Corners />
            {registro ? 'Crear cuenta' : 'Entrar'}
          </button>
          <a href="/restablecer" style={{ fontSize: 13 }}>¿Has olvidado la contraseña?</a>
        </form>
      </div>
    </main>
  );
}
