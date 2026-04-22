// Polly Connect Service Worker — enables PWA install + offline assets
const CACHE_NAME = 'polly-v3';

// Auth pages bake a CSRF token into the HTML tied to the current session
// cookie, so they must never be served stale. Always hit the network.
const NO_CACHE_PATHS = [
  '/web/login',
  '/web/logout',
  '/web/signup',
  '/web/forgot-password',
  '/web/reset-password',
  '/web/join',
];

function isNoCache(url) {
  return NO_CACHE_PATHS.some(p => url.pathname === p || url.pathname.startsWith(p + '/'));
}

// Cache only static assets on install — not auth pages
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      cache.addAll([
        '/static/icon.svg',
        '/static/manifest.json',
      ])
    )
  );
  self.skipWaiting();
});

// Clean old caches on activate
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Network-first strategy: try network, fall back to cache.
// Auth pages bypass the service worker entirely.
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);
  if (isNoCache(url)) return; // let the browser handle it directly

  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response.ok && url.pathname.startsWith('/web/')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
