export default function NotFound() {
  return (
    <main style={{ padding: 48, display: 'grid', gap: 12 }}>
      <span className="kicker">404</span>
      <h1 style={{ margin: 0, textTransform: 'uppercase' }}>Página no encontrada</h1>
      <a href="/panel">Ir al panel</a>
      <p style={{ fontSize: 12 }}><strong>Esto no es asesoramiento financiero.</strong></p>
    </main>
  );
}
