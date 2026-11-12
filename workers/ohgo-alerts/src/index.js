// titan-ohgo-alerts: road alerts for titanenergytech.com, off the site's deploy path (Phase 3, v30.5).
//   cron (every 10 min): pull OHGO + the site's pad list -> build alerts.json (src/ohgo.js) -> KV
//   GET /alerts.json   the latest copy, CORS open, cached 60 s at the edge and in browsers
//   GET /health        when it last ran, how it went
// A failed run keeps serving the last good copy. Secret: OHGO_API_KEY (wrangler secret put). Vars: PADS_URL.
import { buildAlerts, dataFromIndex, fetchAllLive } from './ohgo.js';

const KEY = 'alerts.json', META = 'meta';
const CORS = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS' };

async function loadPadData(env) {
  const r = await fetch(env.PADS_URL, { cf: { cacheTtl: 300 } });
  if (!r.ok) throw new Error(`pads ${env.PADS_URL}: HTTP ${r.status}`);
  const text = await r.text();
  // data/pads.json (an array, or {pads:[...]}) once the site splits its data out; index.html until then
  if (/^\s*[\[{]/.test(text)) { const j = JSON.parse(text); return Array.isArray(j) ? j : j.pads; }
  return dataFromIndex(text);
}

async function run(env) {
  const t0 = Date.now();
  try {
    if (!env.OHGO_API_KEY) throw new Error('OHGO_API_KEY not set');
    const [fx, data] = await Promise.all([fetchAllLive(env.OHGO_API_KEY), loadPadData(env)]);
    const out = buildAlerts(data, fx, Date.now());
    const body = JSON.stringify(out);
    await env.ALERTS.put(KEY, body);
    const meta = { ok: true, updated: out.updated, ms: Date.now() - t0, pads_flagged: Object.keys(out.alerts).length,
                   feeds: Object.fromEntries(Object.entries(fx).map(([k, v]) => [k, v.length])), bytes: body.length };
    await env.ALERTS.put(META, JSON.stringify(meta));
    console.log('ohgo alerts', JSON.stringify(meta));
    return meta;
  } catch (e) {
    const prev = JSON.parse((await env.ALERTS.get(META)) || '{}');
    const meta = { ...prev, ok: false, error: String(e && e.message || e), failed_at: new Date().toISOString() };
    await env.ALERTS.put(META, JSON.stringify(meta));
    console.error('ohgo alerts FAILED', meta.error);
    return meta;
  }
}

export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(run(env)); },
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: { ...CORS, 'Access-Control-Max-Age': '86400' } });
    if (req.method !== 'GET' && req.method !== 'HEAD') return new Response('method not allowed', { status: 405, headers: CORS });
    if (url.pathname === '/alerts.json') {
      const body = await env.ALERTS.get(KEY);
      if (!body) return new Response('{"error":"no alerts yet"}', { status: 503, headers: { ...CORS, 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
      return new Response(req.method === 'HEAD' ? null : body, { headers: { ...CORS, 'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'public, max-age=60', 'X-Content-Type-Options': 'nosniff' } });
    }
    if (url.pathname === '/health') {
      return new Response((await env.ALERTS.get(META)) || '{}', { headers: { ...CORS, 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } });
    }
    return new Response('titan-ohgo-alerts: GET /alerts.json', { status: 404, headers: CORS });
  },
};
