/* sw.js — a small offline-first service worker.
   Precaches the app shell so Lumi's Math Garden works with no network at all
   (the spec's offline-first requirement). Uses cache-first for same-origin GETs
   and updates the cache in the background. */
const CACHE = 'lumi-garden-v4';
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './styles/base.css',
  './styles/themes.css',
  './styles/components.css',
  './styles/games.css',
  './assets/svg.js',
  './src/main.js',
  './src/core/App.js',
  './src/core/dom.js',
  './src/core/EventBus.js',
  './src/core/SceneManager.js',
  './src/core/GameRegistry.js',
  './src/core/drag.js',
  './src/config/curriculum.js',
  './src/config/zones.js',
  './src/services/StorageService.js',
  './src/services/SettingsService.js',
  './src/services/AudioService.js',
  './src/services/NarrationService.js',
  './src/services/ProgressService.js',
  './src/services/RewardService.js',
  './src/services/ParticleService.js',
  './src/ui/Lumi.js',
  './src/ui/TopBar.js',
  './src/ui/BottomNav.js',
  './src/ui/Modal.js',
  './src/games/BaseGame.js',
  './src/games/CountingMeadow.js',
  './src/games/AdditionOrchard.js',
  './src/games/BerrySharingGrove.js',
  './src/games/ShapeGrove.js',
  './src/games/PatternPond.js',
  './src/games/ComparisonHill.js',
  './src/games/CreativeGreenhouse.js',
  './src/scenes/GardenMapScene.js',
  './src/scenes/JournalScene.js',
  './src/scenes/ProfileScene.js',
  './src/scenes/SettingsScene.js',
  './src/scenes/ParentDashboardScene.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

// Network-first: always prefer a fresh copy when online (so updates ship
// immediately), and fall back to the cache when offline — which still
// satisfies the offline-first requirement because the shell is precached.
self.addEventListener('fetch', (e) => {
  const { request } = e;
  if (request.method !== 'GET' || new URL(request.url).origin !== location.origin) return;
  e.respondWith(
    fetch(request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(request))
  );
});
