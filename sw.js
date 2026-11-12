// Titan Haul Routes service worker — offline support
const VER = 'titan-v62';
const CORE = 'titan-core-' + VER;
const PDFS = 'titan-pdfs-v1';
const SHELL = [
  './index.html', './manifest.json', './data/approaches.json',
  './vendor/maplibre-gl-4.7.1.js', './vendor/maplibre-gl-4.7.1.css', './vendor/goatcounter-count.js',
  // the pad cards (v30.6) - keep in step with tools/pads.py FILES
  './data/pads/index.json', './data/pads/ascent.json', './data/pads/eog.json', './data/pads/gulfport.json',
  './data/pads/infinity.json', './data/pads/expand.json', './data/pads/tiburon.json', './data/pads/frac.json',
  './data/pads/disposal.json',
  './icon-192.png', './icon-512.png', './icon-180.png', './img/titan-logo.png', './img/favicon.png',
  './info/about.html', './info/contact.html', './info/calculator.html',
  './info/weather.html', './info/gulfport-kpa.html', './info/eog-reporting.html',
  './info/safety-video.html', './info/project.html',
  './info/eog-loading-sop.html', './info/gulfport-loading-sop.html', './info/gulfport-offload-sop.html'
];
// one bar of signal doesn't fail a request, it hangs - after this long the phone's saved copy is shown
// and the fresh one still lands in the cache for next time
const SLOW_MS = 2500;
const ALERTS = 'https://titan-ohgo-alerts.titan-dispatch-board.workers.dev/alerts.json';

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

// several pad files can change at once: one message to the open pages (awaited, so the worker stays up for it)
let padsNote = null;
function padsChanged() {
  if (!padsNote) padsNote = new Promise(r => setTimeout(r, 800))
    .then(() => self.clients.matchAll({type: 'window'}))
    .then(cs => { cs.forEach(c => c.postMessage({type: 'pads-updated'})); padsNote = null; });
  return padsNote;
}

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // road alerts come from the Cloudflare alerts Worker (v30.5): same slow-signal rule and saved copy as the shell
  const alerts = url.origin + url.pathname === ALERTS;
  if (url.origin !== location.origin && !alerts) return;   // live weather/maps: network only
  if (e.request.method !== 'GET') return;

  // video: never cache (55MB + range/206 requests break Cache API) — let the browser stream it
  if (url.pathname.includes('/videos/')) return;

  if (url.pathname.includes('/data/pads/')) {
    // pad cards: stale-while-revalidate - the saved copy at once (no waiting on one bar of signal), a fresh one
    // fetched behind it; if it changed, the page is told so it can show it at a quiet moment
    const key = keyOf(e.request);
    e.respondWith(caches.open(CORE).then(c => c.match(key).then(hit => {
      const oldText = hit ? hit.clone().text() : null;     // read before `hit` goes to the page (its body is used then)
      const net = fetch(e.request, {cache: 'no-cache'}).then(async res => {
        if (res.ok) {
          const fresh = await res.clone().text();
          const old = oldText ? await oldText : null;
          await c.put(key, res.clone());
          if (old !== null && old !== fresh) await padsChanged();
        }
        return res;
      });
      if (hit) { e.waitUntil(net.catch(() => {})); return hit; }
      return net;
    })));
    return;
  }
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
