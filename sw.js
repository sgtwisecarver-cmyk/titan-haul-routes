// Titan Haul Routes service worker — offline support
const VER = 'titan-v65';
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

// ===== v30.8: offline map tiles =====
// Street map (OpenFreeMap: tiles, fonts, sprites, styles) and the satellite view (USGS The National Map imagery,
// public domain - v30.9 uses it everywhere, no Esri) are kept as they're viewed or saved with "Save this area",
// cache-first, in their own cache that survives version bumps. Past TILE_CAP the least-recently-used tiles go first
// (an IndexedDB index of url/size/last use).
const TILES = 'titan-tiles-v1';
const TILE_CAP = 150 * 1024 * 1024;            // bytes
const TILE_HOSTS = ['tiles.openfreemap.org', 'basemap.nationalmap.gov'];
const CLEAR_PNG = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='), c => c.charCodeAt(0));
// no tile and no signal: an empty tile instead of an error (nothing drawn there, no red console)
function emptyTile(url) {
  return /\.pbf(\?|$)/.test(url)
    ? new Response(new Uint8Array(0), {status: 200, headers: {'Content-Type': 'application/x-protobuf'}})
    : new Response(CLEAR_PNG, {status: 200, headers: {'Content-Type': 'image/png'}});
}

let tdb = null;
function tileDb() {
  return tdb || (tdb = new Promise((res, rej) => {
    const r = indexedDB.open('titan-tiles', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('t', {keyPath: 'u'});
    r.onsuccess = () => res(r.result); r.onerror = () => { tdb = null; rej(r.error); };
  }));
}
function idb(mode, fn) {
  return tileDb().then(db => new Promise((res, rej) => {
    const tx = db.transaction('t', mode), out = fn(tx.objectStore('t'));
    tx.oncomplete = () => res(out && 'result' in out ? out.result : out); tx.onerror = () => rej(tx.error);
  }));
}
const touched = new Map(); let touchTimer = null;
function touch(u) {                               // last use, written in batches
  touched.set(u, Date.now());
  if (!touchTimer) touchTimer = new Promise(r => setTimeout(r, 1500)).then(() => {
    const batch = [...touched]; touched.clear(); touchTimer = null;
    return idb('readwrite', st => batch.forEach(([u, t]) => { const g = st.get(u); g.onsuccess = () => { if (g.result) { g.result.t = t; st.put(g.result); } }; }));
  }).catch(() => {});
  return touchTimer;
}
let evictTimer = null;
function evictSoon() {
  if (!evictTimer) evictTimer = new Promise(r => setTimeout(r, 4000)).then(evict).catch(() => {}).then(() => { evictTimer = null; });
  return evictTimer;
}
async function evict() {
  const all = await idb('readonly', st => st.getAll());
  let total = all.reduce((a, r) => a + (r.size || 0), 0);
  if (total <= TILE_CAP) return total;
  all.sort((a, b) => a.t - b.t);
  const c = await caches.open(TILES), gone = [];
  for (const r of all) { if (total <= TILE_CAP * 0.9) break; total -= r.size || 0; gone.push(r.u); await c.delete(r.u); }
  await idb('readwrite', st => gone.forEach(u => st.delete(u)));
  return total;
}
async function tileUsage() {
  const all = await idb('readonly', st => st.getAll());
  return {bytes: all.reduce((a, r) => a + (r.size || 0), 0), tiles: all.length, cap: TILE_CAP};
}
async function clearTiles() {
  await caches.delete(TILES);
  await idb('readwrite', st => st.clear());
}
async function keepTile(url, res) {
  const blob = await res.blob();
  const c = await caches.open(TILES);
  await c.put(url, new Response(blob, {status: 200, headers: {'Content-Type': res.headers.get('Content-Type') || ''}}));
  await idb('readwrite', st => st.put({u: url, size: blob.size, t: Date.now()}));
  return evictSoon();
}
// tiles, fonts, sprites: saved copy first. Styles and the tile index (they change): network first, saved copy offline.
function tileFetch(e, url) {
  const key = url.href;
  const mutable = url.hostname === 'tiles.openfreemap.org' && !/\.(pbf|png|jpg|jpeg|webp|json)$/.test(url.pathname) && !url.pathname.includes('/sprites/')
               || /\/styles\//.test(url.pathname);
  return caches.open(TILES).then(c => c.match(key).then(hit => {
    if (hit && !mutable) { e.waitUntil(touch(key)); return hit; }
    return fetch(e.request).then(res => {
      if (res.ok) e.waitUntil(keepTile(key, res.clone()).catch(() => {}));
      return res;
    }).catch(() => hit || emptyTile(key));
  }));
}
self.addEventListener('message', e => {
  const d = e.data || {}, port = e.ports && e.ports[0];
  const reply = p => e.waitUntil(p.then(v => port && port.postMessage(v), err => port && port.postMessage({error: String(err)})));
  if (d.type === 'tiles-usage') reply(tileUsage());
  else if (d.type === 'tiles-clear') reply(clearTiles().then(() => ({ok: true})));
  else if (d.type === 'tiles-evict') reply(evict().then(bytes => ({bytes})));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // road alerts come from the Cloudflare alerts Worker (v30.5): same slow-signal rule and saved copy as the shell
  const alerts = url.origin + url.pathname === ALERTS;
  if (e.request.method === 'GET' && TILE_HOSTS.includes(url.hostname)) { e.respondWith(tileFetch(e, url)); return; }
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
