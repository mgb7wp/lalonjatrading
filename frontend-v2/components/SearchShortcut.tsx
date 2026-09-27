'use client';
import { useEffect } from 'react';

/** Atajo «/» para enfocar la búsqueda. Mejora progresiva: sin JS, el campo sigue funcionando. */
export function SearchShortcut({ inputId }: { inputId: string }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return;
      e.preventDefault();
      document.getElementById(inputId)?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [inputId]);
  return null;
}
