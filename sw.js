// Titan Haul Routes service worker — offline support
const VER = 'titan-v15';
const CORE = 'titan-core-' + VER;
const PDFS = 'titan-pdfs-v1';
const SHELL = [
  './', './index.html', './manifest.json',
  './icon-192.png', './icon-512.png', './icon-180.png', './img/titan-logo.png', './img/favicon.png',
  './info/about.html', './info/contact.html', './info/calculator.html',
  './info/weather.html', './info/gulfport-kpa.html', './info/eog-reporting.html',
  './info/safety-video.html'
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CORE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k.startsWith('titan-core-') && k !== CORE).map(k => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;          // live weather/maps: network only
  if (e.request.method !== 'GET') return;

  // video: never cache (43MB + range/206 requests break Cache API) — let the browser stream it
  if (url.pathname.includes('/videos/')) return;

  if (url.pathname.includes('/pdfs/')) {
    // route maps: cache-first, cache as opened
    e.respondWith(
      caches.open(PDFS).then(c => c.match(e.request).then(hit => hit ||
        fetch(e.request).then(res => { if (res.ok) c.put(e.request, res.clone()); return res; })
      ))
    );
    return;
  }
  // app shell: network-first so updates land, cache fallback offline
  e.respondWith(
    fetch(e.request).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(CORE).then(c => c.put(e.request, copy)); }
      return res;
    }).catch(() =>
      caches.match(e.request, {ignoreSearch:true}).then(hit => hit || caches.match('./index.html'))
    )
  );
});
