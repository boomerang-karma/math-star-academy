/**
 * main.js — entry point.
 *
 * Boots the app once the DOM is ready and registers the offline service worker.
 * Everything else lives behind App (the composition root), so this file stays a
 * two-liner on purpose.
 */
import App from './core/App.js';

function boot() {
  const mount = document.getElementById('app');
  // Expose for debugging in the console (e.g. window.lumi.ctx.progress).
  window.lumi = new App(mount);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();

// Register a service worker for true offline play (ignored on file://).
if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  });
}
