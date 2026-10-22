// Titan Haul Routes service worker — offline support
const VER = 'titan-v30';
const CORE = 'titan-core-' + VER;
const PDFS = 'titan-pdfs-v1';
const SHELL = [
  './index.html', './manifest.json', './data/approaches.json',
  './icon-192.png', './icon-512.png', './icon-180.png', './img/titan-logo.png', './img/favicon.png',
  './info/about.html', './info/contact.html', './info/calculator.html',
  './info/weather.html', './info/gulfport-kpa.html', './info/eog-reporting.html',
  './info/safety-video.html', './info/project.html',
  './info/eog-loading-sop.html', './info/gulfport-loading-sop.html', './info/gulfport-offload-sop.html'
];
// one bar of signal doesn't fail a request, it hangs - after this long the phone's saved copy is shown
// and the fresh one still lands in the cache for next time
const SLOW_MS = 2500;

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

// cache key without the query string: alerts.json?cb=<time> and calculator.html?buffer=42 keep one copy each
function keyOf(req){
  const u = new URL(req.url);
  u.search = '';
  if (u.pathname.endsWith('/')) u.pathname += 'index.html';
  return u.href;
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;          // live weather/maps: network only
  if (e.request.method !== 'GET') return;

  // video: never cache (55MB + range/206 requests break Cache API) — let the browser stream it
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
  // app shell: the network copy if it comes within SLOW_MS, otherwise the saved copy; offline -> saved copy.
  // cache:'no-cache' = always ask GitHub "is there a newer copy?" (cheap 304 if not), so a phone never
  // shows a stale page for the ~10 min GitHub Pages lets browsers reuse it
  const key = keyOf(e.request);
  const net = fetch(e.request, {cache: 'no-cache'}).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(CORE).then(c => c.put(key, copy)); }
    return res;
  });
  e.waitUntil(net.catch(() => {}));                     // keep the worker alive until the fresh copy is saved
  const saved = () => caches.match(key, {ignoreSearch: true})
    .then(hit => hit || (e.request.mode === 'navigate' ? caches.match(new URL('./index.html', location).href) : undefined));
  e.respondWith(new Promise(resolve => {
    let done = false;
    const give = r => { if (!done && r) { done = true; resolve(r); } };
    const timer = setTimeout(() => saved().then(give), SLOW_MS);
    net.then(res => { clearTimeout(timer); give(res); })
       .catch(() => { clearTimeout(timer); saved().then(hit => { give(hit); if (!done) { done = true; resolve(Response.error()); } }); });
  }));
});
