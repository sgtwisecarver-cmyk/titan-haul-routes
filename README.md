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
