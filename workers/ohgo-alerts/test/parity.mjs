// Parity check: the JS port vs ohgo/ohgo_alerts.py on the same OHGO snapshot and the same pads.
//   node workers/ohgo-alerts/test/parity.mjs <fixtures.json> <site root> <python-output.json> [nowISO]
// Prints every difference (ignoring "updated"); exits 1 if there are any.
import { readFileSync } from 'node:fs';
import { buildAlerts, mergePads } from '../src/ohgo.js';

const [fxPath, root, pyPath, nowIso] = process.argv.slice(2);
const fx = JSON.parse(readFileSync(fxPath, 'utf8'));
const rd = (f) => JSON.parse(readFileSync(`${root}/data/pads/${f}`, 'utf8'));
const manifest = rd('index.json');
const data = mergePads(manifest, manifest.files.map((f) => rd(f + '.json')));
const now = nowIso ? Date.parse(nowIso + 'Z') : Date.now();
const js = buildAlerts(data, fx, now);
const py = JSON.parse(readFileSync(pyPath, 'utf8'));
delete js.updated; delete py.updated;

const diffs = [];
function cmp(a, b, path) {
  if (diffs.length > 40) return;
  if (typeof a === 'number' && typeof b === 'number') { if (a !== b) diffs.push(`${path}: js ${a} | py ${b}`); return; }
  if (a === null || b === null || typeof a !== 'object' || typeof b !== 'object') { if (a !== b) diffs.push(`${path}: js ${JSON.stringify(a)} | py ${JSON.stringify(b)}`); return; }
  if (Array.isArray(a) !== Array.isArray(b)) { diffs.push(`${path}: type`); return; }
  const ka = Object.keys(a), kb = Object.keys(b);
  if (!Array.isArray(a) && ka.join('\u0001') !== kb.join('\u0001')) diffs.push(`${path}: keys js [${ka.slice(0, 8)}] | py [${kb.slice(0, 8)}]`);
  for (const k of new Set([...ka, ...kb])) cmp(a[k], b[k], path + '.' + k);
}
cmp(js, py, '$');
console.log(`alerts: js ${Object.keys(js.alerts).length} pads | py ${Object.keys(py.alerts).length} pads; padx js ${Object.keys(js.padx).length} | py ${Object.keys(py.padx).length}`);
console.log(diffs.length ? diffs.join('\n') : 'IDENTICAL (apart from "updated")');
process.exit(diffs.length ? 1 : 0);
