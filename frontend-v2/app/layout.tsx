import type { Metadata, Viewport } from 'next';
// Fuentes autoalojadas (sin peticiones a Google Fonts).
import '@fontsource/barlow/400.css';
import '@fontsource/barlow/500.css';
import '@fontsource/barlow/700.css';
import '@fontsource/barlow-condensed/400.css';
import '@fontsource/barlow-condensed/600.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import '@fontsource/ibm-plex-mono/600.css';
import './industry.css';
import './app.css';

export const metadata: Metadata = {
  title: { default: 'LaLonja Trading', template: '%s · LaLonja Trading' },
  description: 'Análisis cuantitativo de acciones de cinco mercados. Esto no es asesoramiento financiero.',
};

export const viewport: Viewport = { width: 'device-width', initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es-ES">
      <body>{children}</body>
    </html>
  );
}
