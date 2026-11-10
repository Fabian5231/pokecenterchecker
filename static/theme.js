'use strict';
// Hell/Dunkel-Umschalter. Läuft im <head> (ohne defer), damit die gespeicherte Wahl vor dem
// ersten Zeichnen greift. Ohne gespeicherte Wahl gilt die Systemeinstellung.
// Knöpfe: jedes Element mit [data-theme-toggle]. Gespeichert wird in localStorage "theme".
(() => {
  const KEY = 'theme';
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === 'dark' || saved === 'light') root.setAttribute('data-theme', saved);
  } catch { /* kein Speicher: Systemeinstellung */ }

  const current = () => {
    const set = root.getAttribute('data-theme');
    if (set === 'dark' || set === 'light') return set;
    return media && media.matches ? 'dark' : 'light';
  };

  const sync = () => {
    const label = current() === 'dark' ? 'Zu hellem Modus wechseln' : 'Zu dunklem Modus wechseln';
    for (const button of document.querySelectorAll('[data-theme-toggle]')) {
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
    }
    // Browser-/Statusleiste in der Farbe des Seitenhintergrunds
    if (document.body) {
      const color = getComputedStyle(document.body).backgroundColor;
      for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
        meta.removeAttribute('media');
        meta.setAttribute('content', color);
      }
    }
  };

  const toggle = () => {
    const next = current() === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem(KEY, next); } catch { /* nur für diese Sitzung */ }
    sync();
  };

  document.addEventListener('DOMContentLoaded', () => {
    for (const button of document.querySelectorAll('[data-theme-toggle]')) button.addEventListener('click', toggle);
    sync();
  });
  if (media && media.addEventListener) media.addEventListener('change', sync);
})();
