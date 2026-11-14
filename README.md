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

## Route maps and the safety video (v31.0)
The PDFs (`pdfs/`) and `videos/` moved to their own repo and Pages site, **titan-haul-routes-files**
(https://sgtwisecarver-cmyk.github.io/titan-haul-routes-files/, local clone C:\dev\titan-haul-routes-files), so this
site publishes ~20 MB instead of ~620 MB. Cards still say `pdfs/<customer>/<file>.pdf`: the service worker fetches
those from the files site and keeps each on the phone once opened (offline works as before); visitors without the
service worker are redirected by `404.html`; pad pages and the safety video link to the files site directly. To add
a route map, commit it to the files repo first, then point the card at `pdfs/...` here. To move the files site to a
titanenergytech.com subdomain later: add a CNAME record, set the custom domain on that repo, and change `FILES` in
sw.js, 404.html, info/safety-video.html and tools/build_pages.py. History was not rewritten (.git here still holds
the old PDFs; deploys only upload the current files).

## Shared road rules and alert end dates (v31.9)
Rules that apply to a group of pads live once in `data/rules.json` as named rule sets, not copied onto each card:
`{"eog-cutler-rd": {"name": "...", "rules": [{"t": "CUTLER RD: 25 MPH MAX, no exceptions.", "added": "2026-11-12",
"temp": false, "from": "EOG vendor call 11/12/2026"}, ...]}}`. Each rule has the same shape as a card alert, and
`from` must say where it came from (the vendor call, a route map PDF or a TCP). A card follows a set with
`"rules": ["eog-cutler-rd"]`. It can still have its own `"alert"` list for lines that fit only that pad. The card
(and its pad/ page) shows the set's rules first, then its own alerts, as the same ROAD ALERT boxes. Edit the sets
with `pads.load_rules` / `pads.save_rules`. The file is precached by sw.js and refreshed like the pad files.

Any alert or rule can carry `"until": "YYYY-MM-DD"`. It shows through that day, then drops off by itself. Every
`"temp": true` alert or rule must have an `until` date (use a review-by date if the real end is not known).

`python tools/pads.py check` (the publish job runs it) fails with exit 1 when:
- a card names a rule set that is not in `data/rules.json`
- a `"temp": true` alert or rule has no `until`
- a pad has a visible regular card and a visible frac card at the same time. While a frac runs, hide the regular
  card with `"hidden": true` and `"goto": "<frac card id>"`; its links, stars, search and old pad/ page then open
  the frac card (build_pages.py writes a forwarding page for it).
- cards following the same set give different speeds for the same thing (Cutler Rd, lease road, on pad, a
  10 MPH zone) in their own alerts, or a different speed than the set itself.
