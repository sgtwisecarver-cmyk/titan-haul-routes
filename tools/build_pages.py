"""Build one plain HTML page per pad card so Google can list every pad, plus an A-Z pad list and sitemap.xml.

The route lookup (index.html) builds its cards in the browser from data/pads/ (tools/pads.py), so Google sees
it as one page. This script reads the same cards and writes:
  pad/<card id>.html   one page per card: directions, route map, wells, tanks, nearby pads, "Open in the lookup"
  pad/index.html       every pad A-Z, grouped by county
  sitemap.xml          home + info pages + pad list + every pad page

It runs in the "Publish site" GitHub Action before each upload (and once a day, so frac cards whose "until"
date has passed drop off). Nothing here is committed: pad/ and sitemap.xml are in .gitignore.
Run it locally to preview:  python tools/build_pages.py   (then serve the repo and open /pad/)
"""
import datetime
import html
import json
import math
import os
import re
import sys

SITE = 'https://titanenergytech.com'
FILES = 'https://sgtwisecarver-cmyk.github.io/titan-haul-routes-files/'   # route-map PDFs + safety video: their own Pages site
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'pad')
APPLY = 'https://tetransports.com/careers?utm_source=titanroutes&amp;utm_medium=pad-page&amp;utm_campaign=apply#apply'

try:
    from zoneinfo import ZoneInfo
    TODAY = datetime.datetime.now(ZoneInfo('America/New_York')).date().isoformat()
except Exception:   # no tz database: Eastern standard time is close enough for a date
    TODAY = (datetime.datetime.utcnow() - datetime.timedelta(hours=5)).date().isoformat()

OPERATOR_NAMES = {'EOG': 'EOG Resources', 'Ascent': 'Ascent Resources', 'Gulfport': 'Gulfport Energy',
                  'Infinity': 'Infinity Natural Resources', 'Expand': 'Expand Energy', 'Tiburon': 'Tiburon'}


def norm(s):
    s = re.sub(r'[^a-z0-9 ]+', ' ', (s or '').lower())
    return re.sub(r'\s+', ' ', s).strip()


def slug(s):
    return norm(s).replace(' ', '-')


def e(s):
    return html.escape(str(s if s is not None else ''), quote=True)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pads   # data/pads/*.json in the site's list order (v30.6) + shared rule sets in data/rules.json (v31.9)
RULESETS = pads.load_rules(ROOT)


def load_all():
    data = pads.load_cards(ROOT)
    for d in data:
        d['_id'] = d.get('id') or slug(d['src'] + '-' + d['pad'])
    return data


def shown(d):
    # same rule as the lookup: hidden cards and cards past their "until" date are off the list
    return not d.get('hidden') and not (d.get('until') and TODAY > d['until'])


def load_data():
    return [d for d in load_all() if shown(d)]


def operator(d):
    if d['src'] in ('Frac', 'Disposal'):
        return d.get('operator') or ''
    return d['src']


def state_of(d):
    if ', WV' in (d.get('county') or ''):
        return 'West Virginia', 'WV'
    if d.get('lon') and d['lon'] > -80.519:      # east of the Ohio-Pennsylvania line (Infinity's PA sites)
        return 'Pennsylvania', 'PA'
    return 'Ohio', 'OH'


def place_bits(d):
    """'Warren Township, Tuscarawas County, Ohio'"""
    bits = []
    if d.get('township'):
        bits.append(d['township'] + ' Township')
    if d.get('county'):
        bits.append(d['county'].replace(', WV', ''))
    bits.append(state_of(d)[0])
    return ', '.join(bits)


def kind(d):
    if d['src'] == 'Frac':
        return 'frac'
    if d['src'] == 'Disposal':
        return 'disposal'
    return 'pad'


def title_of(d):
    op = operator(d)
    if kind(d) == 'frac':
        return f"{d['pad']} — traffic control plan, staging & directions"
    if kind(d) == 'disposal':
        return f"{d['pad']} — disposal site directions"
    return f"{d['pad']} ({op}) — haul route & directions"


def description_of(d):
    where = place_bits(d)
    where = f" in {where}"
    op = OPERATOR_NAMES.get(operator(d), operator(d))
    if kind(d) == 'frac':
        s = f"Traffic control plan, staging and truck directions for the {d['pad']}{where}. For water haulers working the frac."
    elif kind(d) == 'disposal':
        s = f"Directions and route to the {d['pad']} saltwater disposal site{where}, for produced-water haulers."
    else:
        # "3M 19-11-3 PAD" / "Reed Haul Route" -> "the 3M 19-11-3 pad" / "the Reed pad"
        name = re.sub(r'\s*\b(haul route|route|pad)\s*$', '', d['pad'], flags=re.I).strip() or d['pad']
        s = (f"Approved haul route and turn-by-turn directions to the {name} pad ({op}){where}. "
             f"Route map, entrance GPS, wells and tank info for water haulers.")
    return s if len(s) <= 300 else s[:297] + '...'


def miles(a, b):
    r = 3958.8
    p1, p2 = math.radians(a['lat']), math.radians(b['lat'])
    dp, dl = p2 - p1, math.radians(b['lon'] - a['lon'])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def nearby(d, located, n=6, limit=15.0):
    if not (d.get('lat') and d.get('lon')):
        return []
    near = sorted(((miles(d, x), x) for x in located if x is not d), key=lambda t: t[0])
    return [(m, x) for m, x in near if m <= limit][:n]


STYLE = """
:root{--bg:#eef0f4;--card:#fff;--text:#15171d;--dim:#4a5262;--line:#d5d9e2;--accent:#075e86;--amber:#8a4f00;--warn:#fff4e0;--warnline:#e0a030;color-scheme:light;
--font-body:"Inter","Segoe UI",Roboto,Helvetica,Arial,sans-serif;--font-display:"Barlow Condensed","Arial Narrow","Segoe UI",sans-serif;}
@media (prefers-color-scheme: dark){:root:not(.light){--bg:#1b1e24;--card:#262a33;--text:#e8eaef;--dim:#a6acb8;--line:#3a3f4b;--accent:#2bb0e8;--amber:#f5a623;--warn:#3a2f1a;--warnline:#b07d00;color-scheme:dark;}}
:root.dark{--bg:#1b1e24;--card:#262a33;--text:#e8eaef;--dim:#a6acb8;--line:#3a3f4b;--accent:#2bb0e8;--amber:#f5a623;--warn:#3a2f1a;--warnline:#b07d00;color-scheme:dark;}
body{font-family:var(--font-body);background:var(--bg);color:var(--text);margin:0;padding:16px;line-height:1.55;}
.wrap{max-width:680px;margin:0 auto;overflow-wrap:anywhere;}
.thdr{display:flex;align-items:center;gap:10px;background:linear-gradient(160deg,#0d1338 0%,#141c52 55%,#1e2a78 100%);border-bottom:3px solid #2bb0e8;border-radius:12px;padding:10px 12px;margin-bottom:16px;}
.logobadge{display:inline-flex;align-items:center;background:#fff;border-radius:8px;padding:5px 11px;}
.logobadge img{display:block;height:36px;width:auto;}
.thdr a.hback{margin-left:auto;color:#7fd2f5;text-decoration:none;font-weight:700;font-size:13px;white-space:nowrap;}
h1{font-family:var(--font-display);font-weight:700;font-size:28px;line-height:1.15;margin:4px 0 4px;text-wrap:balance;}
h2{font-family:var(--font-display);font-weight:600;font-size:19px;letter-spacing:.3px;margin:24px 0 8px;color:var(--accent);}
.meta{color:var(--dim);font-size:14.5px;margin-bottom:14px;}
.crumbs{font-size:13px;color:var(--dim);margin-bottom:6px;} .crumbs a{color:var(--accent);text-decoration:none;}
.btns{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0;}
.btn{display:inline-block;padding:12px 16px;border-radius:10px;font-weight:700;text-decoration:none;font-size:15px;}
.btn.go{background:#1e2a78;color:#fff;border:2px solid #2bb0e8;} .btn.pdf{background:var(--card);color:var(--text);border:1.5px solid var(--line);}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:12px 0;}
.note{background:var(--card);border-left:4px solid #2bb0e8;border-radius:8px;padding:10px 12px;margin:12px 0;font-size:15px;}
.warn{background:var(--warn);border-left:4px solid var(--warnline);border-radius:8px;padding:10px 12px;margin:12px 0;font-size:14px;}
ol.steps{padding-left:24px;margin:6px 0 10px;font-size:15.5px;} ol.steps li{margin:6px 0;}
h3{font-size:15px;margin:16px 0 4px;}
ul.plain{list-style:none;padding:0;margin:4px 0;} ul.plain li{padding:6px 0;border-bottom:1px solid var(--line);font-size:14.5px;} ul.plain li:last-child{border-bottom:0;}
.dim{color:var(--dim);font-size:13.5px;} a{color:var(--accent);}
.hire{background:linear-gradient(160deg,#0d1338,#1e2a78);color:#fff;border-radius:12px;padding:14px 16px;margin:26px 0 10px;}
.hire .yards{font-size:13.5px;opacity:.9;}
.callbar{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:26px 0 0;font-size:14.5px;}
.callbar a{display:flex;align-items:center;min-height:44px;font-weight:700;text-decoration:none;font-size:16px;}
.hire{margin-top:10px !important;}
.hire a{color:#fff;background:#d21f2c;padding:9px 14px;border-radius:8px;font-weight:700;text-decoration:none;display:inline-block;margin-top:8px;}
.az{columns:2;column-gap:20px;} .az a{display:block;padding:3px 0;text-decoration:none;font-size:14px;break-inside:avoid;}
@media (max-width:480px){.az{columns:1;}}
.azsw{display:inline-flex;border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:4px 0 12px;}
.azsw button{min-height:44px;padding:0 16px;background:var(--card);border:0;color:var(--text);font:inherit;font-weight:700;cursor:pointer;}
.azsw button+button{border-left:1px solid var(--line);}
.azsw button[aria-pressed="true"]{background:#1e2a78;color:#fff;}
[hidden]{display:none!important;}
footer{margin-top:24px;font-size:12.5px;color:var(--dim);}
"""

HEAD_THEME = ("<script>(function(){try{var t=localStorage.getItem('titan_theme');"
              "if(t==='light'||t==='dark')document.documentElement.classList.add(t);}catch(e){}})();</script>")
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Inter:wght@400;600;700&display=swap">')
GOAT = '<script data-goatcounter="https://titanroutes.goatcounter.com/count" async src="../vendor/goatcounter-count.js"></script>'
# Content-Security-Policy for the pad pages: same rules as the info pages (inline script/style are still needed)
CSP = ('<meta http-equiv="Content-Security-Policy" content="'
       "default-src 'self'; script-src 'self' 'unsafe-inline'; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
       "img-src 'self' data: https://titanroutes.goatcounter.com; connect-src 'self' https://titanroutes.goatcounter.com; "
       "frame-src 'none'; worker-src 'self'; media-src 'self'; manifest-src 'self'; "
       "base-uri 'none'; object-src 'none'; form-action 'self'"
       '">'
       '<meta name="referrer" content="strict-origin-when-cross-origin">')


def page(title, desc, path, body, jsonld=None):
    url = SITE + '/' + path
    ld = ''
    for block in (jsonld or []):
        ld += '<script type="application/ld+json">' + json.dumps(block, ensure_ascii=False).replace('</', '<\\/') + '</script>'
    return ('<!DOCTYPE html><html lang="en"><head>' + CSP + HEAD_THEME +
            '<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{e(title)} | Titan Energy Transportation</title>'
            f'<meta name="description" content="{e(desc)}">'
            f'<link rel="canonical" href="{e(url)}">'
            '<meta property="og:type" content="website"><meta property="og:site_name" content="Titan Energy Transportation — Haul Routes">'
            f'<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">'
            f'<meta property="og:url" content="{e(url)}"><meta property="og:image" content="{SITE}/icon-512.png">'
            '<meta name="theme-color" content="#0d1338"><link rel="icon" type="image/png" href="../img/favicon.png">'
            + FONTS + '<style>' + STYLE + '</style>' + ld + '</head><body><div class="wrap">'
            '<div class="thdr"><a class="logobadge" href="../index.html" aria-label="Titan Energy Transportation — Haul Routes">'
            '<img src="../img/titan-logo.png" alt="Titan Energy Transportation LLC" width="120" height="36"></a>'
            '<a class="hback" href="../index.html">&larr; Route lookup</a></div>'
            + body +
            '<div class="callbar">Questions on this route? <a href="tel:+17404335399" data-goatcounter-click="call-padpage" '
            'data-goatcounter-title="Call dispatch (pad page)">&#128222; Call 24/7 Dispatch &mdash; (740) 433-5399</a></div>'
            '<div class="hire"><b>Drive for the #1 water hauler in Ohio.</b><br>'
            '<span class="yards">Yards in Barnesville, Cambridge, Coshocton, New Philadelphia, Newcomerstown, Sardis, Sherrodsville and East Canton, Ohio.</span><br>'
            f'<a href="{APPLY}" target="_blank" rel="noopener" data-goatcounter-click="apply-padpage" data-goatcounter-title="Apply click (pad page)">Apply here &rarr;</a></div>'
            '<footer>Haul routes come from the operators\' own RUMA and route documents, with well records from the Ohio Department of Natural Resources. '
            'Always follow the approved haul route and verify with dispatch before your first haul to a new pad. '
            '<a href="index.html">All pads A–Z</a> · <a href="../info/about.html">About this site</a> · <a href="../info/contact.html">Contact dispatch</a></footer>'
            '</div>' + GOAT + '</body></html>')


def pad_page(d, located):
    op = operator(d)
    opname = OPERATOR_NAMES.get(op, op)
    where = place_bits(d)
    pid = d['_id']
    lookup = f"../index.html#pad={pid}"
    b = ['<div class="crumbs"><a href="../index.html">Haul routes</a> › <a href="index.html">All pads</a>'
         + (f" › {e(d['county'])}" if d.get('county') else '') + '</div>',
         f"<h1>{e(d['pad'])}</h1>"]
    meta = [x for x in [opname if kind(d) != 'disposal' else (('Disposal' + (' · ' + opname if opname else ''))), where] if x]
    b.append('<div class="meta">' + e(' · '.join(meta)) + '</div>')
    for a in pads.card_alerts(d, RULESETS, TODAY):  # shared rule sets first, then the card's own alerts; past "until" dropped
        if a.get('t'):
            b.append('<div class="warn">🚧 <b>Road alert:</b> ' + e(a['t']) + '</div>')
    b.append('<div class="btns">'
             f'<a class="btn go" href="{e(lookup)}">🧭 Open in the route lookup — Navigate, map &amp; calculator</a>')
    docs = d.get('docs') or ([{'url': d['url'], 'label': 'Traffic Control Plan' if d['src'] == 'Frac' else 'Route map'}] if d.get('url') else [])
    for doc in docs:
        label = doc['label'] if d.get('docs') is None else doc['label'] + ' route'
        href = doc['url'] if doc['url'].startswith('http') else FILES + doc['url']   # route maps: the files site (v31.0)
        b.append(f'<a class="btn pdf" href="{e(href)}" target="_blank" rel="noopener">📄 {e(label)} (PDF)</a>')
    b.append('</div>')
    if d.get('addr'):
        b.append('<div class="box">📍 <b>' + e(d['addr']) + '</b></div>')
    if d.get('note'):
        b.append('<div class="note">' + e(d['note']) + '</div>')
    b.append('<h2>Directions</h2>')
    if d.get('segs'):
        for g in d['segs']:
            b.append('<h3>' + e(g.get('t') or 'Route') + '</h3><ol class="steps">' + ''.join('<li>' + e(s) + '</li>' for s in g.get('s', [])) + '</ol>')
    elif d.get('steps'):
        b.append('<ol class="steps">' + ''.join('<li>' + e(s) + '</li>' for s in d['steps']) + '</ol>')
    else:
        b.append('<p>No written directions on file — use the route map PDF, or call dispatch.</p>')
    b.append('<div class="warn"><b>⚠ Follow the approved haul route.</b> A phone maps app will not follow the haul route — '
             'trucks must follow the written directions or route map. The route lookup adds truck-route waypoints where we have them.</div>')
    if d.get('buffer'):
        b.append('<div class="box">🛢️ ' + e(d['buffer']) + '</div>')
    if d.get('bpi'):
        b.append(f'<div class="warn">📏 <b>Tank strapping at this pad: 1" = {e(d["bpi"])} bbl</b> — not the standard 1.67.</div>')
    if d.get('props'):
        b.append('<h2>Property numbers (for your BOL)</h2><ul class="plain">' + ''.join(
            f"<li><b>{e(p.get('w'))}</b> — Prop {e(p.get('p'))}" + (f" · API {e(p['a'])}" if p.get('a') else '') + '</li>' for p in d['props']) + '</ul>')
    wells = d.get('wells') or []
    if wells:
        label = 'Injection wells at this site' if d['src'] == 'Disposal' else 'Wells on this pad'
        b.append(f'<h2>{label} ({len(wells)})</h2><ul class="plain">' + ''.join(
            f"<li><b>{e(w.get('n'))}</b>" + (f" · API {e(w['api'])}" if w.get('api') else '') + (f" · {e(w['s'])}" if w.get('s') else '') + '</li>' for w in wells) + '</ul>'
            + (f"<div class=\"dim\">{e(d['wsrc'])} records</div>" if d.get('wsrc') else ''))
    elif d.get('well'):
        b.append('<h2>Well</h2><div class="box"><b>' + e(d['well']) + '</b>' + (f" · API {e(d['api'])}" if d.get('api') else '') + '</div>')
    if d.get('tanks'):
        sv = {'water': 'produced water', 'mixed': 'oil / produced water (shared)'}
        b.append('<h2>Tanks</h2><ul class="plain">' + ''.join(
            f"<li><b>{e(t['n'])} × {e(t['bbl'])} bbl</b> {e(sv.get(t.get('svc'), t.get('svc')))}"
            + (f" · {e(re.sub(r'\.0$', '', str(t['dia'])))}′ dia × {e(t.get('h'))}′ tall" if t.get('dia') else '') + '</li>' for t in d['tanks']) + '</ul>'
            + (f"<div class=\"dim\">{e(d['tsrc'])}</div>" if d.get('tsrc') else ''))
    if d.get('sites'):
        b.append(f"<h2>Sites on this route ({len(d['sites'])})</h2><ul class=\"plain\">" + ''.join(
            f"<li><b>{e(w.get('n'))}</b>" + (f" — {e(w['w'])}" if w.get('w') else '') + '</li>' for w in d['sites']) + '</ul>')
    near = nearby(d, located)
    if near:
        b.append('<h2>Nearby pads</h2><ul class="plain">' + ''.join(
            f'<li><a href="{e(x["_id"])}.html">{e(x["pad"])}</a> <span class="dim">{e(operator(x))} · {m:.1f} mi</span></li>' for m, x in near) + '</ul>')
    ld = [{'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
        {'@type': 'ListItem', 'position': 1, 'name': 'Haul routes', 'item': SITE + '/'},
        {'@type': 'ListItem', 'position': 2, 'name': 'All pads', 'item': SITE + '/pad/'},
        {'@type': 'ListItem', 'position': 3, 'name': d['pad'], 'item': SITE + f'/pad/{pid}.html'}]}]
    if d.get('lat') and d.get('lon'):
        place = {'@context': 'https://schema.org', '@type': 'Place', 'name': d['pad'],
                 'geo': {'@type': 'GeoCoordinates', 'latitude': d['lat'], 'longitude': d['lon']},
                 'address': {'@type': 'PostalAddress', 'addressRegion': state_of(d)[1], 'addressCountry': 'US'}}
        if d.get('county'):
            place['containedInPlace'] = {'@type': 'AdministrativeArea',
                                         'name': d['county'].replace(', WV', '') + ', ' + state_of(d)[0]}
        ld.append(place)
    return page(title_of(d), description_of(d), f'pad/{pid}.html', ''.join(b), ld)


def az_page(cards):
    """All pads, two ways on one page: by customer and by county (a switch at the top; the phone remembers)."""
    by_name = lambda d: norm(d['pad'])

    def section(prefix, groups, order, label, sub):
        out = ['<div class="box">' + ' · '.join(f'<a href="#{prefix}{slug(g)}">{e(label(g))}</a>' for g in order) + '</div>']
        for g in order:
            out.append(f'<h2 id="{prefix}{slug(g)}">{e(label(g))} ({len(groups[g])})</h2><div class="az">' + ''.join(
                f'<a href="{e(d["_id"])}.html">{e(d["pad"])} <span class="dim">{e(sub(d))}</span></a>'
                for d in sorted(groups[g], key=by_name)) + '</div>')
        return ''.join(out)

    county, cust = {}, {}
    for d in cards:
        county.setdefault(d.get('county') or 'County not listed', []).append(d)
        cust.setdefault(d['src'], []).append(d)
    county_order = sorted(county, key=lambda c: (c == 'County not listed', c))
    src_order = ['Ascent', 'EOG', 'Gulfport', 'Infinity', 'Expand', 'Tiburon', 'Frac', 'Disposal']
    cust_order = sorted(cust, key=lambda c: (src_order.index(c) if c in src_order else 99, c))
    cust_label = lambda c: {'Frac': 'Active fracs', 'Disposal': 'Disposal sites'}.get(c, OPERATOR_NAMES.get(c, c))
    b = ['<h1>All pads A–Z</h1>',
         f'<div class="meta">{len(cards):,} pads, disposal sites and active fracs across eastern Ohio and nearby West Virginia and Pennsylvania — '
         'EOG, Ascent, Gulfport, Infinity, Expand and Tiburon. Pick one for its haul route and directions.</div>',
         '<div class="azsw" role="group" aria-label="Group the list">'
         '<button type="button" data-by="cust" aria-pressed="false">By customer</button>'
         '<button type="button" data-by="county" aria-pressed="true">By county</button></div>',
         '<div id="by-county">' + section('', county, county_order, lambda c: c, lambda d: operator(d) or d['src']) + '</div>',
         '<div id="by-cust" hidden>' + section('c-', cust, cust_order, cust_label, lambda d: (d.get('county') or '').replace(' County', '')) + '</div>',
         # the switch: plain page first (works with no script), then the phone's last choice
         "<script>(function(){var bs=document.querySelectorAll('.azsw button'),A=document.getElementById('by-county'),B=document.getElementById('by-cust');"
         "function set(by,save){A.hidden=by==='cust';B.hidden=by!=='cust';bs.forEach(function(x){x.setAttribute('aria-pressed',String(x.dataset.by===by));});"
         "if(save){try{localStorage.setItem('titan_az',by);}catch(e){}}}"
         "bs.forEach(function(x){x.addEventListener('click',function(){set(x.dataset.by,true);});});"
         "var by='county';try{if(localStorage.getItem('titan_az')==='cust')by='cust';}catch(e){}"
         "if(/^#c-/.test(location.hash))by='cust';set(by,false);"
         "if(location.hash){var t=document.getElementById(location.hash.slice(1));if(t)t.scrollIntoView();}})();</script>"]
    desc = (f"Every approved haul route Titan Energy Transportation drivers use — {len(cards):,} well pads, disposal sites and "
            "frac locations in eastern Ohio, West Virginia and Pennsylvania, listed by customer and by county.")
    return page('All pads A–Z — haul routes by customer and county', desc, 'pad/', ''.join(b))


def redirect_page(d, to):
    """a hidden card's old pad page (shared links, Google) forwards to the card that replaces it (its "goto")"""
    url = f"{to['_id']}.html"
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
            f'<meta http-equiv="refresh" content="0; url={e(url)}">'
            f'<link rel="canonical" href="{e(SITE)}/pad/{e(url)}"><meta name="robots" content="noindex">'
            f'<title>{e(d["pad"])} — see {e(to["pad"])}</title></head><body>'
            f'<p>{e(d["pad"])} — use <a href="{e(url)}">{e(to["pad"])}</a>.</p></body></html>\n')


def main():
    every = load_all()
    cards = [d for d in every if shown(d)]
    located = [d for d in cards if d.get('lat') and d.get('lon') and d['src'] != 'Frac']
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):           # clear last build so removed cards don't linger
        if f.endswith('.html'):
            os.remove(os.path.join(OUT, f))
    for d in cards:
        with open(os.path.join(OUT, d['_id'] + '.html'), 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(pad_page(d, located))
    built = {d['_id']: d for d in cards}
    moved = 0
    for d in every:                     # hidden cards with a "goto": their old page forwards (not in the sitemap)
        if d['_id'] not in built and d.get('goto') in built:
            with open(os.path.join(OUT, d['_id'] + '.html'), 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(redirect_page(d, built[d['goto']]))
            moved += 1
    with open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(az_page(cards))
    urls = [SITE + '/', SITE + '/pad/'] + [SITE + '/info/' + f for f in sorted(os.listdir(os.path.join(ROOT, 'info'))) if f.endswith('.html')]
    urls += [SITE + f"/pad/{d['_id']}.html" for d in cards]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f'<url><loc>{e(u)}</loc></url>' for u in urls]
    sm.append('</urlset>')
    with open(os.path.join(ROOT, 'sitemap.xml'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(sm) + '\n')
    print(f'{len(cards)} pad pages, {moved} forwarding pages, A-Z list and sitemap ({len(urls)} urls) built for {TODAY}')


if __name__ == '__main__':
    sys.exit(main())
