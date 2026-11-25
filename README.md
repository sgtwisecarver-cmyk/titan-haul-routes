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

## Navigate ends at the pad gate (v32.0)

Rick, 11/15, after truck 141 went half a mile past the Gulfport Robert turn-off: Navigate used to end at the mined entrance (where trucks leave the OpenStreetMap road network), so Google said "arrived" at the lease-road turn and never announced it. `tools/route-miner/gate_test.py` (titan-dispatch) asks Google to drive each pad from ~800 m before the entrance; when Google passes the entrance, follows our trucks' own GPS (90%+) and ends at the pad's edge, the card gets `gate` in data/approaches.json and Navigate (`pinUrl`, `truckUrl`) ends there. `nav_to` (private-road cuts) still wins. 68 of 165 cards have a gate. The daily Google task tests new or moved pads.

## Truck-road route, pilot on Shula (v32.6)

Rick, 11/25: navigation inside the app, on the roads Titan trucks actually drive. `data/trucknet.json` (~1 MB, 0.3 MB
gzipped) is every road piece trucks drove on 2+ truck-days since 9/27, joined into links between junctions, built by
`tools/route-miner/truck_net.py` in titan-dispatch from the map-matched truck GPS - never edit it by hand. On the map,
a pad in `TNAV_CARDS` (index.html; only `eog-shula` for now) gets **Truck route from here**: the phone works out the
cheapest route to the pad's mined entrance on that network (busier roads cost less, service roads / tracks 3x more),
draws it green (dashed from you to the nearest truck road when you're off it) and lists the roads with miles (voice
directions: v32.7 below). Rick's Shula test (155 real trips since 10/25, routes built only from earlier GPS):
the route matched the driver's own roads 89% vs Google 40-50%, and never used a road no Titan truck drives.
`python truck_net.py --check eog-shula` re-checks a card against the last month's trips. Not precached yet: the
file is saved by the service worker the first time someone asks for a truck route.

## Voice directions on the truck route (v32.7)

**Start voice directions** under the green line reads the turns out loud with the phone's own voice
(`speechSynthesis`, so it plays through the truck's Bluetooth like any phone audio; nothing leaves the phone). It keeps
the screen on (Wake Lock), follows the truck on the map (moving the map leaves it alone for 20 s) and shows the next
turn in a green banner with Voice on/off and Stop.
- Turns are where the road changes name, worked out from `trucknet.json`'s road names. A state / US route that turns a
  corner in town is said ("turn left to stay on State Route 39"); the same route straight on under a new street name
  is not. Roads are called by their SR / US / I number when they have one (the one the route carries on along, not a
  Business loop), else their name without the NW/SE tail. Pieces under 160 m are connectors: the turn is said where
  the connector begins. Unnamed ramps: "keep right toward State Route 259".
- For each turn: "in 1 mile" (45+ mph only), "in half a mile", and the turn itself about 12 s out (120 m at least);
  after a turn with 1+ mile to the next, "stay on X for N miles". It ends at the pad's entrance: "the Shula lease road
  is on the right" (the side the pad is on), then the blue line and route card take over.
- Leaving the route (60 m+ for 6 s, or 200 m back the way you came) works it out again from where you are, at most
  every 20 s. A U-turn costs 5 km extra in that new route (`UTURN_COST`, tRoute), so it carries on ahead unless turning
  back saves real distance. It talks only when it matters: "off the truck roads" (150 m+ from them; every 90 s at
  most), "back on the truck roads", "turn around when it's safe" (every 2 min at most), "new truck route".
- Checked on four real Shula trips replayed as GPS (11/25): from the yard it gave 15 lines in 16 miles, every turn
  matching the card (SR 39 → left on Beaver Ave staying on SR 39 → left on Cutler Rd → lease road on the right); on
  trips where the driver went his own way it settled down within about a mile.
- v32.8 (Rick, 11/25: "I have Shula opened, I see nothing"): the Shula card itself now has **Truck route + voice
  directions** under Navigate. It opens the map with `TNAV_AUTO` set, and `selectPad` runs the truck route as soon as
  the pad's map sheet is up. Before, the button was only on the map pop-up.
- The page calls `vnTick` on every GPS fix (`watchMe`); the GPS only runs with the map open and on screen.

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
