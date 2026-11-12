# Titan Energy — Haul Route Lookup
Mobile lookup site (titanenergytech.com) for approved haul routes across EOG, Ascent, Gulfport, Infinity and Expand pads, active frac TCPs, and Class II disposal sites — with ODNR well/API lists, customer SOPs, Good Catch / KPA reporting, live ODOT (OHGO) road alerts, and offline support.
Built and maintained via Claude — to update, process new route packets through a Claude session.

## Road alerts (v30.5)
The Cloudflare Worker `titan-ohgo-alerts` (code in `workers/ohgo-alerts`) pulls OHGO every 10 minutes, matches
events to each pad's route and serves `alerts.json` at
https://titan-ohgo-alerts.titan-dispatch-board.workers.dev/alerts.json (`/health` shows the last run).
The site asks the Worker first, then its own `alerts.json` (the publish job copies the Worker's latest into the
site), and the service worker keeps the last copy of each for no signal. Alerts never redeploy the site.
`ohgo/ohgo_alerts.py` is the original Python job, kept as the reference: `node workers/ohgo-alerts/test/parity.mjs`
compares the two on the same OHGO snapshot. Deploy the Worker from a folder outside OneDrive (wrangler's bundler
can't read the OneDrive parent folders): copy `src/`, `wrangler.jsonc`, `package.json` to C:\dev and run
`npx wrangler deploy`. The OHGO key is a Worker secret (`npx wrangler secret put OHGO_API_KEY`), never in git.

## Pad cards (v30.6)
The cards live in `data/pads/<customer>.json` (one card per line) plus `data/pads/index.json` (the list order),
not inside index.html. `tools/pads.py` loads and saves them (`load_cards` / `save_cards`) and `python tools/pads.py
check` makes the manifest agree with the files (the publish job runs it too). The page paints at once and starts
the downloads from `<head>`; the service worker precaches the files and serves them stale-while-revalidate,
telling the page when a file changed so it reloads at a quiet moment. A one-pad edit costs phones one customer
file (EOG ~80 KB gzipped, fracs ~5 KB) instead of the whole 300 KB page. If you add a customer file, add it to
`FILES` in tools/pads.py, `KNOWN` in index.html's head loader and the sw.js SHELL.
