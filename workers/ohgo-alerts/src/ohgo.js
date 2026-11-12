// OHGO -> alerts.json, ported line for line from ohgo/ohgo_alerts.py (v4) so the site gets the same answers.
// Pure functions only (no Worker APIs): the Worker (index.js) and the parity test (test/parity.mjs) both use it.
//
// Output: alerts (per-pad closure/incident text - the only part the site reads today), padx (per-pad work
// zones, road-surface hazards, nearest camera) and corridors (I-77 / I-70 boards).

export const OHGO_BASE = 'https://publicapi.ohgo.com/api/v1';
const PROX_MI = 6.0, FRAC_SITE_MI = 1.0, INTERSTATE_MI = 1.5, APPROACH_STEPS = 3, WX_MI = 15.0, CAM_MI = 12.0;
const CLOSE_RE = /clos|detour|blocked|restrict|ramp closed|road closed|lane closed/i;
const CATEGORY_LABEL = { construction: 'Closure/construction', incidents: 'Incident' };
const CORRIDORS = [
  { id: 'i77', num: 77, name: 'I-77', label: 'I-77 · Marietta to Canton (MM 1–101)', mm: [1, 101], axis: 'lat',
    re: /\b(?:I|IR)\s*-?\s*77\b(?!\d)/i,
    cal: [[0.66, 39.413], [17.01, 39.6286], [36.53, 39.8958], [47, 40.001], [60.05, 40.2204], [83, 40.574], [95.11, 40.6649], [101, 40.7508], [109.63, 40.8594], [120.94, 40.9973], [150.02, 41.3171], [156.64, 41.4115]] },
  { id: 'i70', num: 70, name: 'I-70', label: 'I-70 · Norwich to St. Clairsville (MM 164–216)', mm: [164, 216], axis: 'lon',
    re: /\b(?:I|IR)\s*-?\s*70\b(?!\d)/i,
    cal: [[143.52, -82.2112], [152, -82.0403], [156, -81.9718], [178, -81.545], [198.07, -81.24], [216, -80.8613], [219, -80.76]] },
];
const MM_SLOP = 2.0;
const ROUTE_TYPE_RE = /\b(SR|OH|US|I|IR|CR|TR|TWP)\s*-?\s*(\d{1,4})\b/gi;
const NAME_RE = /\b([A-Z][A-Za-z\.]+(?:\s+[A-Z][A-Za-z\.]+){0,3}\s+(?:Rd|Road|Ln|Lane|Ave|Avenue|St|Street|Dr|Drive|Pike|Hwy|Highway|Ridge|Run|Hill|Creek|Hollow|Church))\b/g;
export const CAMHOST = 'https://itscameras.dot.state.oh.us';

// ---------- Python-compatible helpers ----------
// round(): Python rounds the exact binary value, ties to even
export function pyRound(x, nd = 0) {
  const p = 10 ** nd, lo = Math.floor(x * p);
  if ((lo + 0.5) / p === x) return (lo % 2 === 0 ? lo : lo + 1) / p;
  return nd ? Number(x.toFixed(nd)) : Math.round(x);
}
const fmtG = (x) => String(Number(x.toPrecision(6)));                 // f'{x:g}' for the values OHGO sends
const isUpper = (s) => /[A-Za-z]/.test(s) && s === s.toUpperCase();
const pyTitle = (s) => s.toLowerCase().replace(/(^|[^a-z])([a-z])/g, (m, a, b) => a + b.toUpperCase());
const clean = (s) => String(s ? s : '').replace(/\s+/g, ' ').trim();   // Python: str(s or '')
function pyFloat(v) {
  if (v === null || v === undefined || typeof v === 'boolean') return null;
  if (typeof v === 'number') return v;
  const t = String(v).trim(); if (!t) return null;
  const n = Number(t); return Number.isNaN(n) ? null : n;
}
const key = (t, n) => { t = t.toUpperCase(); if (t === 'OH') t = 'SR'; if (t === 'IR') t = 'I'; return t + '|' + n; };
const routesIn = (text) => { const s = new Set(); for (const m of text.matchAll(ROUTE_TYPE_RE)) s.add(key(m[1], m[2])); return s; };
const isInterstate = (r) => r.startsWith('I|');
const inter = (a, b) => new Set([...a].filter((x) => b.has(x)));

function toks(text) {
  const routes = routesIn(text), names = new Set();
  for (const m of text.matchAll(NAME_RE)) {
    let nm = m[1].replace(/\s+/g, ' ').trim().toLowerCase(); nm = nm.replace(/\broad\b/g, 'rd');
    if (nm.length >= 6) names.add(nm);
  }
  return [routes, names];
}

export function haversineMi(aLat, aLon, bLat, bLon) {
  const R = 3958.8, r = Math.PI / 180, p1 = aLat * r, p2 = bLat * r, dp = (bLat - aLat) * r, dl = (bLon - aLon) * r;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// ---------- pads ----------
const normid = (s) => (s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim().replace(/ /g, '-');
export function loadPads(data) {
  const pads = [];
  for (const d of data) {
    if (!(d.lat && d.lon)) continue;
    const seqs = [];
    if (d.steps && d.steps.length) seqs.push(d.steps);
    for (const g of d.segs || []) if (g.s && g.s.length) seqs.push(g.s);
    const appr = new Set(), names = new Set(), all = new Set();
    for (const s of seqs) {
      for (const r of toks(s.slice(-APPROACH_STEPS).join(' '))[0]) appr.add(r);
      const [r2, n] = toks(s.join(' '));
      n.forEach((x) => names.add(x)); r2.forEach((x) => all.add(x));
    }
    pads.push({ id: d.id || normid(d.src + '-' + d.pad), pad: d.pad, src: d.src || '', lat: d.lat, lon: d.lon,
                appr, names, routes: all, has_route: seqs.length > 0 });
  }
  return pads;
}
// DATA out of index.html (until the pads live in their own file)
export function dataFromIndex(html) {
  const m = html.match(/const DATA\s*=\s*(\[.*?\]);/s);
  return JSON.parse(m[1]);
}

// ---------- OHGO fetch ----------
function thin(pl, n = 8) {
  if (!pl || pl.length <= n) return pl;
  const step = (pl.length - 1) / (n - 1); const out = [];
  for (let i = 0; i < n; i++) out.push(pl[pyRound(i * step)]);
  return out;
}
export async function fetchAllLive(apiKey, fetchImpl = fetch) {
  const get = async (ep) => {
    const r = await fetchImpl(`${OHGO_BASE}/${ep}${ep.includes('?') ? '&' : '?'}page-all=true`, { headers: { Authorization: 'APIKEY ' + apiKey } });
    if (!r.ok) throw new Error(`OHGO ${ep}: HTTP ${r.status}`);
    const j = await r.json(); return j.results || j.Results || [];
  };
  const [inc, con, del, slo, wx, cam, sig] = await Promise.all(['incidents', 'construction', 'travel-delays', 'dangerous-slowdowns',
    'weather-sensor-sites', 'cameras', 'digital-signs'].map(get));
  const v0 = (x) => (x.cameraViews || [{}])[0] || {};
  return {
    incidents: inc.map((x) => ({ id: x.id, lat: x.latitude, lon: x.longitude, loc: x.location, desc: x.description, cat: x.category,
      dir: x.direction, route: x.routeName, status: x.roadStatus, pl: thin((x.roadClosureDetails || {}).polyline) })),
    construction: con.map((x) => ({ id: x.id, lat: x.latitude, lon: x.longitude, loc: x.location, desc: x.description, cat: x.category,
      dir: x.direction, route: x.routeName, status: x.status, start: x.startDate, end: x.endDate,
      pl: (x.workZones || []).map((w) => thin(w.polyline)) })),
    delays: del.map((x) => ({ id: x.id, lat: x.latitude, lon: x.longitude, loc: x.location, desc: x.description, dir: x.direction,
      route: x.routeName, mm0: x.startMileMarker, mm1: x.endMileMarker, delay: x.delayTime, travel: x.travelTime,
      cur: x.currentAvgSpeed, normal: x.normalAvgSpeed })),
    slowdowns: slo.map((x) => ({ id: x.id, lat: x.latitude, lon: x.longitude, loc: x.location, desc: x.description, dir: x.direction,
      route: x.routeName, cur: x.currentMPH, normal: x.normalMPH })),
    weather: wx.map((x) => ({ id: x.id, lat: x.latitude, lon: x.longitude, loc: x.location, severe: x.severe, cond: x.condition,
      air: x.averageAirTemperature,
      atm: (x.atmosphericSensors || []).slice(0, 1).map((a) => ({ t: a.airTemperature, precip: a.precipitation, pint: a.precipitationintensity,
        vis: a.visibility, wind: a.averageWindSpeed, gust: a.maximumWindSpeed, upd: a.lastUpdate })),
      surf: (x.surfaceSensors || []).map((s) => ({ n: s.name, st: s.status, t: s.surfaceTemperature, upd: s.lastUpdate })) })),
    cameras: cam.map((x) => ({ id: x.id, lat: x.latitude, lon: x.longitude, loc: x.location, u: v0(x).smallUrl, d: v0(x).direction })),
    signs: sig.map((x) => ({ id: x.id, lat: x.latitude, lon: x.longitude, loc: x.location, type: x.signTypeName, msgs: x.messages || [] })),
  };
}

// ---------- helpers ----------
// naive datetimes, read as wall-clock (Python drops any offset with replace(tzinfo=None)) -> ms on a UTC scale
export function parseDt(s) {
  if (!s) return null;
  s = String(s).trim().replace(/Z/g, '');
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?(?:[+-]\d{2}:?\d{2})?$/);
  if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0), m[7] ? Math.floor(+('0.' + m[7]) * 1000) : 0);
  m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?: (\d{1,2}):(\d{2}):(\d{2})(?: ?([AP]M))?)?$/i);
  if (m) {
    let h = +(m[4] || 0); const ap = (m[7] || '').toUpperCase();
    if (ap === 'PM' && h < 12) h += 12; if (ap === 'AM' && h === 12) h = 0;
    return Date.UTC(+m[3], +m[1] - 1, +m[2], h, +(m[5] || 0), +(m[6] || 0));
  }
  return null;
}
const isActive = (ev, now) => { const st = parseDt(ev.start), en = parseDt(ev.end); if (en !== null && en < now) return false; if (st !== null && st > now) return false; return true; };
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const fmtDate = (s) => { const d = parseDt(s); if (d === null) return ''; const x = new Date(d); return MON[x.getUTCMonth()] + ' ' + x.getUTCDate(); };
const saneTemp = (t) => { const v = pyFloat(t); return v !== null && v >= -60 && v <= 150 ? v : null; };

function parseMm(text, routenum) {
  const t = text || '';
  let m = t.match(/mile\s*markers?\s+([\d.]+)\s+(?:and|to|-|through)\s+([\d.]+)/i);
  if (m) { const a = parseFloat(m[1]), b = parseFloat(m[2]); return [Math.min(a, b), Math.max(a, b)]; }
  m = t.match(/\bMM:?\s*([\d.]+)/i);
  if (m) { const v = parseFloat(m[1]); return [v, v]; }
  if (routenum) {
    m = t.match(new RegExp('\\b(?:IR|I)\\s*-?\\s*' + routenum + '\\s+(\\d{1,3}\\.\\d{1,2})\\b'));
    if (m) { const v = parseFloat(m[1]); return [v, v]; }
  }
  return [null, null];
}
function mmFromPoint(cor, lat, lon) {
  const x = cor.axis === 'lat' ? lat : lon, cal = cor.cal;
  let a, b;
  if (x <= cal[0][1]) { a = cal[0]; b = cal[1]; }
  else if (x >= cal[cal.length - 1][1]) { a = cal[cal.length - 2]; b = cal[cal.length - 1]; }
  else { for (let i = 0; i < cal.length - 1; i++) { a = cal[i]; b = cal[i + 1]; if (a[1] <= x && x <= b[1]) break; } }
  if (b[1] === a[1]) return a[0];
  return a[0] + (x - a[1]) * (b[0] - a[0]) / (b[1] - a[1]);
}
function inCorridor(cor, text, lat, lon) {
  if (!cor.re.test(text || '')) return null;
  let [lo, hi] = parseMm(text, cor.num), slop;
  if (lo === null) {
    if (lat === null || lat === undefined || lon === null || lon === undefined) return null;
    const v = mmFromPoint(cor, lat, lon); lo = hi = pyRound(v, 1); slop = MM_SLOP;
  } else slop = 0.0;
  const [a, b] = cor.mm;
  if (hi < a - slop || lo > b + slop) return null;
  return [lo, hi];
}
const DIRS = { northbound: 'NB', southbound: 'SB', eastbound: 'EB', westbound: 'WB', n: 'NB', s: 'SB', e: 'EB', w: 'WB', 'both directions': 'Both', both: 'Both' };
const dirShort = (d) => { d = (d || '').trim(); return DIRS[d.toLowerCase()] || d.slice(0, 12); };

function signLegs(msg) {
  const t = (msg || '').replace(/\s+/g, ' ').trim(), legs = [];
  for (const m of t.matchAll(/([A-Z][A-Z0-9\-/ .]{1,24}?)\s*\/\s*(\d{1,3})\s*MI\s+(\d{1,3})\b/g)) legs.push([m[1].trim(), +m[2], +m[3]]);
  if (!legs.length && t.includes('MILES MIN')) {
    const rest = t.split('MILES MIN').slice(1).join('MILES MIN');
    for (const m of rest.matchAll(/([A-Z][A-Z0-9\-]{1,12})\s+(\d{1,3})\s+(\d{1,3})\b/g)) legs.push([m[1], +m[2], +m[3]]);
  }
  const out = [];
  for (const [to, mi, mn] of legs) {
    if (mi <= 0 || mn <= 0) continue;
    const mph = pyRound(mi / (mn / 60.0));
    out.push({ to: isUpper(to) && !to.includes('-') ? pyTitle(to) : to, mi, min: mn, mph, pace: mph >= 55 ? 'ok' : (mph >= 40 ? 'slow' : 'jam') });
  }
  return out;
}
function wxSummary(w) {
  const surf = (w.surf || []).filter((s) => s.st && s.st !== 'Unknown' && s.st !== 'No description available');
  const statuses = [...new Set(surf.map((s) => s.st))].sort();
  const temps = surf.map((s) => saneTemp(s.t)).filter((t) => t !== null);
  const atm = (w.atm || [{}])[0] || {}, air = saneTemp(atm.t);
  let vis = pyFloat(atm.vis); const precip = clean(atm.precip);
  if (vis !== null && vis < 0) vis = null;
  const why = [];
  const bad = statuses.filter((s) => /ice|icy|snow|frost|slush|freez/i.test(s));
  if (bad.length) why.push(bad.join('/').toUpperCase() + ' surface');
  if (w.severe) why.push(w.cond ? 'ODOT severe: ' + clean(w.cond) : 'ODOT severe weather flag');
  if (/snow|ice|sleet|freez|hail/i.test(precip)) why.push(precip);
  if (vis !== null && vis > 0 && vis < 1) why.push(`visibility ${fmtG(vis)} mi`);
  const stMin = temps.length ? Math.min(...temps) : null;
  if (stMin !== null && stMin <= 34 && statuses.includes('Wet')) why.push(`wet pavement ${pyRound(stMin)}°F — freeze risk`);
  else if (stMin !== null && stMin <= 30) why.push(`pavement ${pyRound(stMin)}°F`);
  return { surface: statuses.join('/') || null, surf_t: stMin !== null ? pyRound(stMin) : null, air_t: air !== null ? pyRound(air) : null,
           precip: precip && precip.toLowerCase() !== 'none' ? precip : null, vis, hazard: why.length > 0,
           why: why.length ? why.join('; ') : null, upd: atm.upd };
}
function wxLoc(loc) {
  let s = clean(loc);
  s = s.replace(/^D\d+\s+\w+\s+\w{3}\s+/, ''); s = s.replace(/^IR(\d+)\s+[\d.]+\s*-\s*/, '');
  s = s.replace(/\bIR(\d+)\b/g, 'I-$1').replace(/\bSR(\d+)\b/g, 'SR-$1').replace(/\bUS(\d+)\b/g, 'US-$1');
  return s.replace(/^[ -]+|[ -]+$/g, '');
}
const pick = (o, ks) => Object.fromEntries(ks.map((k) => [k, o[k]]));
const polyPts = (c) => [[c.lat, c.lon]].concat((c.pl || []).flatMap((pl) => (pl || []).filter((q) => q && q.length === 2).map((q) => [q[1], q[0]])));

// ---------- per-pad ----------
function matchAlerts(pads, events, cat, now) {
  const hits = {};
  for (const e of events) {
    const text = ['route', 'desc', 'loc'].map((k) => clean(e[k])).join(' ').toLowerCase();
    if (cat === 'construction') { if (!CLOSE_RE.test(text)) continue; if (!isActive(e, now)) continue; }
    if (e.lat === null || e.lat === undefined) continue;
    const eroutes = routesIn(clean(e.route));
    for (const p of pads) {
      const dist = haversineMi(p.lat, p.lon, e.lat, e.lon);
      if (dist > PROX_MI) continue;
      let matched = false;
      for (const nm of p.names) if (text.includes(nm)) { matched = true; break; }
      if (!matched && eroutes.size) {
        const common = inter(p.appr, eroutes), nonI = [...common].filter((r) => !isInterstate(r));
        if (nonI.length) matched = true; else if (common.size && dist <= INTERSTATE_MI) matched = true;
      }
      if (matched) {
        let txt = `${CATEGORY_LABEL[cat] || cat}: ${clean(e.desc) || clean(e.route)}`.trim();
        const rn = clean(e.route);
        if (rn && !txt.toLowerCase().includes(rn.toLowerCase())) txt += ` (${rn})`;
        (hits[p.id] = hits[p.id] || []).push(txt.slice(0, 240));
      }
    }
  }
  return hits;
}
function padExtras(pads, fx, now) {
  const padx = {};
  const cons = fx.construction.filter((c) => isActive(c, now) && c.lat !== null && c.lat !== undefined);
  for (const p of pads) {
    const x = {};
    const wz = [];
    if (p.has_route) {
      for (const c of cons) {
        const text = ['route', 'desc', 'loc'].map((k) => clean(c[k])).join(' ').toLowerCase();
        const croutes = routesIn(clean(c.route) + ' ' + clean(c.loc));
        const nonIcommon = [...inter(croutes, p.routes)].filter((r) => !isInterstate(r));
        const onRoute = [...p.names].some((nm) => text.includes(nm)) || nonIcommon.length > 0;
        if (!onRoute) continue;
        const dmin = Math.min(...polyPts(c).map(([a, b]) => haversineMi(p.lat, p.lon, a, b)));
        if (dmin > PROX_MI) continue;
        wz.push({ t: clean(c.desc).slice(0, 160) || clean(c.route), road: clean(c.route).slice(0, 40), status: clean(c.status),
                  start: fmtDate(c.start), end: fmtDate(c.end), mi: pyRound(dmin, 1) });
      }
    }
    if (wz.length) x.wz = wz.sort((a, b) => a.mi - b.mi).slice(0, 3);
    let best = null;
    for (const w of fx.weather) {
      if (w.lat === null || w.lat === undefined) continue;
      const d = haversineMi(p.lat, p.lon, w.lat, w.lon);
      if (d > WX_MI) continue;
      const s = wxSummary(w);
      if (!s.hazard) continue;
      if (best === null || d < best[0]) best = [d, w, s];
    }
    if (best) { const [d, w, s] = best; x.wx = { loc: wxLoc(w.loc), mi: pyRound(d, 1), ...pick(s, ['surface', 'surf_t', 'air_t', 'precip', 'vis', 'why']) }; }
    if (p.has_route) {
      let bestc = null;
      for (const c of fx.cameras) {
        if (c.lat === null || c.lat === undefined || !c.u) continue;
        const d = haversineMi(p.lat, p.lon, c.lat, c.lon);
        if (d > CAM_MI) continue;
        const cl = clean(c.loc).toLowerCase(), croutes = routesIn(clean(c.loc));
        if (!([...p.names].some((nm) => cl.includes(nm)) || inter(croutes, p.routes).size)) continue;
        if (bestc === null || d < bestc[0]) bestc = [d, c];
      }
      if (bestc) { const [d, c] = bestc; x.cam = { loc: clean(c.loc).slice(0, 60), url: c.u, mi: pyRound(d, 1) }; }
    }
    if (Object.keys(x).length) padx[p.id] = x;
  }
  return padx;
}

// ---------- corridors ----------
function buildCorridors(fx, now) {
  const out = [];
  for (const cor of CORRIDORS) {
    const C = { id: cor.id, name: cor.name, label: cor.label, mm: cor.mm, traffic: { delays: [], slowdowns: [], pace: [] },
                incidents: [], workzones: [], weather: [], cameras: [] };
    for (const e of fx.delays) {
      const text = clean(e.route) + ' ' + clean(e.loc) + ' ' + clean(e.desc);
      let mm = null;
      if (e.mm0 !== null && e.mm0 !== undefined && e.mm1 !== null && e.mm1 !== undefined && cor.re.test(text)) {
        const [lo, hi] = [pyFloat(e.mm0), pyFloat(e.mm1)].sort((a, b) => a - b), [a, b] = cor.mm;
        if (!(hi < a || lo > b)) mm = [lo, hi];
      } else mm = inCorridor(cor, text, e.lat, e.lon);
      if (mm) C.traffic.delays.push({ mm: [pyRound(mm[0], 1), pyRound(mm[1], 1)], dir: dirShort(e.dir), delay: pyRound(pyFloat(e.delay) || 0),
                                       cur: e.cur, normal: e.normal, desc: clean(e.desc).slice(0, 140) });
    }
    for (const e of fx.slowdowns) {
      const text = clean(e.route) + ' ' + clean(e.loc), mm = inCorridor(cor, text, e.lat, e.lon);
      if (mm) C.traffic.slowdowns.push({ mm: pyRound(mm[0], 1), dir: dirShort(e.dir), cur: e.cur, normal: e.normal, loc: clean(e.loc).slice(0, 60) });
    }
    for (const s of fx.signs) {
      const text = clean(s.loc), mm = inCorridor(cor, text, s.lat, s.lon);
      if (!mm) continue;
      const legs = (s.msgs || []).flatMap(signLegs);
      if (legs.length) {
        const d = /\bEB\b|east/i.test(text) ? 'EB' : /\bWB\b|west/i.test(text) ? 'WB' : /\bNB\b|north/i.test(text) ? 'NB' : /\bSB\b|south/i.test(text) ? 'SB' : '';
        C.traffic.pace.push({ mm: pyRound(mm[0], 1), dir: d, loc: text.replace(/^QWS:\s*/, '').slice(0, 50), legs: legs.slice(0, 4) });
      }
    }
    for (const e of fx.incidents) {
      const rt = clean(e.route) + ' ' + clean(e.loc);
      if (!cor.re.test(rt)) continue;
      const mm = inCorridor(cor, rt + ' ' + clean(e.desc), e.lat, e.lon);
      if (mm) C.incidents.push({ mm: pyRound(mm[0], 1), dir: dirShort(e.dir), cat: clean(e.cat), status: clean(e.status), desc: clean(e.desc).split('\n')[0].slice(0, 160) });
    }
    for (const c of fx.construction) {
      if (!isActive(c, now)) continue;
      const rt = clean(c.route) + ' ' + clean(c.loc), text = rt + ' ' + clean(c.desc);
      if (!cor.re.test(rt)) continue;
      const mms = polyPts(c).filter(([a, b]) => a !== null && a !== undefined && b !== null && b !== undefined).map(([a, b]) => mmFromPoint(cor, a, b));
      let [lo, hi] = parseMm(text, cor.num);
      if (lo === null && mms.length) { lo = Math.min(...mms); hi = Math.max(...mms); }
      if (lo === null) continue;
      const [a, b] = cor.mm;
      if (hi < a - MM_SLOP || lo > b + MM_SLOP) continue;
      C.workzones.push({ mm: [pyRound(Math.max(lo, a), 1), pyRound(Math.min(hi, b), 1)], dir: dirShort(c.dir), status: clean(c.status),
                         desc: clean(c.desc).slice(0, 170), start: fmtDate(c.start), end: fmtDate(c.end),
                         closure: clean(c.status).toLowerCase() === 'closed' || CLOSE_RE.test(clean(c.desc)) });
    }
    for (const w of fx.weather) {
      const text = clean(w.loc), mm = inCorridor(cor, text, w.lat, w.lon);
      if (!mm) continue;
      const s = wxSummary(w);
      if (s.surface === null && s.air_t === null) continue;
      C.weather.push({ mm: pyRound(mm[0], 1), loc: wxLoc(text).slice(0, 50), ...pick(s, ['surface', 'surf_t', 'air_t', 'precip', 'vis', 'hazard', 'why']) });
    }
    for (const c of fx.cameras) {
      const text = clean(c.loc), mm = inCorridor(cor, text, c.lat, c.lon);
      if (mm && c.u) C.cameras.push({ mm: pyRound(mm[0], 1), loc: text.slice(0, 60), url: c.u });
    }
    const k0 = (r) => (Array.isArray(r.mm) ? r.mm[0] : r.mm);
    for (const k of ['incidents', 'workzones', 'weather', 'cameras']) C[k].sort((a, b) => k0(a) - k0(b));
    C.traffic.delays.sort((a, b) => a.mm[0] - b.mm[0]); C.traffic.slowdowns.sort((a, b) => a.mm - b.mm); C.traffic.pace.sort((a, b) => a.mm - b.mm);
    C.summary = { delays: C.traffic.delays.length, slowdowns: C.traffic.slowdowns.length, incidents: C.incidents.length,
                  closures: C.workzones.filter((z) => z.closure).length, workzones: C.workzones.length,
                  wx_hazards: C.weather.filter((w) => w.hazard).length, cameras: C.cameras.length };
    out.push(C);
  }
  return out;
}

// ---------- the whole job ----------
export function buildAlerts(data, fx, nowMs = Date.now()) {
  const pads = loadPads(data), allhits = {};
  for (const [cat, rows] of [['construction', fx.construction], ['incidents', fx.incidents]]) {
    const h = matchAlerts(pads, rows, cat, nowMs);
    for (const [k, v] of Object.entries(h)) (allhits[k] = allhits[k] || []).push(...v);
  }
  // a frac is the same physical site as its pad card: alerts on a pad within FRAC_SITE_MI apply to the frac too
  const fracs = pads.filter((p) => p.src === 'Frac');
  for (const f of fracs) for (const p of pads) {
    if (p.src === 'Frac' || !(p.id in allhits)) continue;
    if (haversineMi(f.lat, f.lon, p.lat, p.lon) <= FRAC_SITE_MI) (allhits[f.id] = allhits[f.id] || []).push(...allhits[p.id]);
  }
  for (const k of Object.keys(allhits)) allhits[k] = [...new Set(allhits[k])].slice(0, 4);
  const padx = padExtras(pads, fx, nowMs), corridors = buildCorridors(fx, nowMs);
  const shorten = (u) => (u || '').replace(/^https:\/\/itscameras\.dot\.state\.oh\.us(?::443)?/, '');
  for (const x of Object.values(padx)) if (x.cam) x.cam.url = shorten(x.cam.url);
  for (const C of corridors) for (const c of C.cameras) c.url = shorten(c.url);
  return { updated: new Date(nowMs).toISOString(), source: 'OHGO (ODOT)', camhost: CAMHOST, alerts: allhits, padx, corridors };
}
