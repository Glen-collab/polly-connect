// Polly Connect Service Worker — enables PWA install + offline login page
const CACHE_NAME = 'polly-v2';

// Cache the login page and key assets on install
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache =>
      cache.addAll([
        '/web/login',
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

// Network-first strategy: try network, fall back to cache
self.addEventListener('fetch', event => {
  // Only handle GET requests for our pages
  if (event.request.method !== 'GET') return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Cache successful page loads for offline
        if (response.ok && event.request.url.includes('/web/')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
