#!/usr/bin/env python3
"""
OHGO -> per-pad road alerts for the Titan Haul Routes site.

Reads the pad data out of index.html, pulls live OHGO events (construction,
incidents, dangerous slowdowns), matches them to the roads named in each pad's
turn-by-turn list, and writes alerts.json (keyed by the site's pad _id).

Runs from a GitHub Action on a schedule. Needs env var OHGO_API_KEY.
Tuning knobs are the CONSTANTS block below.
"""
import os, re, json, math, sys, urllib.request, urllib.parse, datetime

# ---------------- CONSTANTS (tune these once it's live) ----------------
OHGO_BASE   = "https://publicapi.ohgo.com/api/v1"
ENDPOINTS   = ["construction", "incidents", "dangerous-slowdowns"]  # add "weather-sensor-sites" later
REGION      = None            # e.g. "east" / "central"; None = statewide (we filter by pad anyway)
ROUTE_RADIUS_MI = 3.0         # a state-route event must be within this many miles of the pad to count
                              # (lower = fewer, tighter matches; raise if you're missing real ones.
                              #  Local-road-name matches ignore this and always count — they're precise.)
# construction is high-volume; keep only events that actually close/restrict a road
CLOSE_RE = re.compile(r'clos|detour|blocked|restrict|ramp closed|road closed|lane closed', re.I)
INDEX_PATH  = "index.html"
OUT_PATH    = "alerts.json"
CATEGORY_LABEL = {"construction":"Construction/closure","incidents":"Incident","dangerous-slowdowns":"Slowdown"}

# ---------------- road extraction ----------------
# route designators in the turn lists: SR-147, OH-9, US-250, I-77, CR-71, TR-627, TWP-54
ROUTE_RE = re.compile(r'\b(?:SR|OH|US|I|IR|CR|TR|TWP)\s*-?\s*(\d{1,4})\b', re.I)
ROUTE_TYPE_RE = re.compile(r'\b(SR|OH|US|I|IR|CR|TR|TWP)\s*-?\s*(\d{1,4})\b', re.I)
# named local roads: "Cobbler Rd", "Key Bellaire Rd", "Old Infirmary Rd", "Pipe Creek Rd"
NAME_RE = re.compile(r'\b([A-Z][A-Za-z\.]+(?:\s+[A-Z][A-Za-z\.]+){0,3}\s+(?:Rd|Road|Ln|Lane|Ave|Avenue|St|Street|Dr|Drive|Pike|Hwy|Highway|Ridge|Run|Hill|Creek|Hollow|Church))\b')
# state-route families that are "major" (apply the distance filter); local designators are trusted without it
MAJOR_TYPES = {"SR","OH","US","I","IR"}

def norm_route(t, n):
    t=t.upper()
    if t=="OH": t="SR"            # OHGO uses SR/US/I; treat OH as SR
    if t=="IR": t="I"
    return (t, n)

def extract_roads(steps):
    routes=set(); names=set()
    text=" ".join(steps)
    for m in ROUTE_TYPE_RE.finditer(text):
        routes.add(norm_route(m.group(1), m.group(2)))
    for m in NAME_RE.finditer(text):
        nm=re.sub(r'\s+',' ',m.group(1)).strip().lower()
        nm=re.sub(r'\broad\b','rd',nm)
        names.add(nm)
    return routes, names

def haversine_mi(a_lat,a_lon,b_lat,b_lon):
    R=3958.8
    p1,p2=math.radians(a_lat),math.radians(b_lat)
    dp=math.radians(b_lat-a_lat); dl=math.radians(b_lon-a_lon)
    h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(h))

# ---------------- load pads from index.html ----------------
def load_pads(path):
    html=open(path,encoding='utf-8').read()
    m=re.search(r'const DATA\s*=\s*(\[.*?\]);', html, re.S)
    if not m:
        m=re.search(r'(\[\{.*\}\]);', html, re.S)
    data=json.loads(m.group(1))
    def normid(s): return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9 ]+',' ',(s or '').lower())).strip().replace(' ','-')
    pads=[]
    for d in data:
        if not (d.get('lat') and d.get('lon')): continue
        steps=[]
        if d.get('steps'): steps+=d['steps']
        if d.get('segs'):
            for g in d['segs']: steps+=g.get('s',[])
        if not steps: continue
        routes,names=extract_roads(steps)
        if not routes and not names: continue
        pads.append({'id':normid(d['src']+'-'+d['pad']),'pad':d['pad'],'src':d['src'],
                     'lat':d['lat'],'lon':d['lon'],'routes':routes,'names':names})
    return pads

# ---------------- OHGO fetch ----------------
def ohgo_get(endpoint, key):
    params={}
    if REGION: params['region']=REGION
    url=OHGO_BASE+"/"+endpoint+("?"+urllib.parse.urlencode(params) if params else "")
    req=urllib.request.Request(url, headers={"Authorization":"APIKEY "+key})
    out=[]
    for _ in range(20):  # follow paging
        with urllib.request.urlopen(req, timeout=30) as r:
            j=json.load(r)
        rows=j.get('results') or j.get('Results') or []
        out+=rows
        nxt=j.get('pagination',{}).get('nextUrl') or j.get('Pagination',{}).get('NextUrl')
        if not nxt: break
        req=urllib.request.Request(nxt, headers={"Authorization":"APIKEY "+key})
    return out

def event_fields(ev):
    def g(*ks):
        for k in ks:
            for kk in (k, k[0].upper()+k[1:]):
                if kk in ev and ev[kk] not in (None,""): return ev[kk]
        return ""
    lat=g('latitude'); lon=g('longitude')
    try: lat=float(lat); lon=float(lon)
    except: lat=lon=None
    road=str(g('routeName','roadName','route'))
    desc=str(g('description','category','eventDescription')).strip()
    loc=str(g('location','locationDescription')).strip()
    blob=(road+" "+desc+" "+loc)
    routes=set()
    for m in ROUTE_TYPE_RE.finditer(blob):
        routes.add(norm_route(m.group(1),m.group(2)))
    return {'lat':lat,'lon':lon,'road':road,'desc':desc or loc,'loc':loc,'routes':routes,'blob':blob.lower()}

def match(pads, events, cat):
    hits={}
    for ev in events:
        e=event_fields(ev)
        if cat=='construction' and not CLOSE_RE.search(e['blob']):
            continue   # only real closures/restrictions from construction
        for p in pads:
            matched=False; why=""
            # 1) local road-name match (high confidence, no distance needed)
            for nm in p['names']:
                if nm and nm in e['blob']:
                    matched=True; why=nm; break
            # 2) route-number match with distance filter
            if not matched and e['routes']:
                common=p['routes'] & e['routes']
                major=[r for r in common if r[0] in MAJOR_TYPES]
                if common and e['lat'] is not None:
                    dist=haversine_mi(p['lat'],p['lon'],e['lat'],e['lon'])
                    if (not major) or dist<=ROUTE_RADIUS_MI:
                        matched=True; why=(major or list(common))[0][0]+"-"+(major or list(common))[0][1]
                elif common and e['lat'] is None and not major:
                    matched=True; why=list(common)[0][0]+"-"+list(common)[0][1]
            if matched:
                label=CATEGORY_LABEL.get(cat,cat)
                txt=f"{label}: {e['desc'] or e['road']}".strip()
                if e['road'] and e['road'].lower() not in txt.lower(): txt+=f" ({e['road']})"
                hits.setdefault(p['id'],[]).append(txt[:240])
    return hits

def main():
    key=os.environ.get("OHGO_API_KEY")
    if not key:
        print("OHGO_API_KEY not set", file=sys.stderr); sys.exit(1)
    pads=load_pads(INDEX_PATH)
    print(f"pads with routable roads: {len(pads)}")
    allhits={}
    for cat in ENDPOINTS:
        try:
            evs=ohgo_get(cat,key)
        except Exception as e:
            print(f"  {cat}: fetch error {e}", file=sys.stderr); continue
        if evs:
            print(f"  [{cat}] sample event keys: {list(evs[0].keys())}")
            for s in evs[:2]:
                ef=event_fields(s)
                print(f"   [{cat}] road={ef['road']!r} desc={ef['desc'][:80]!r} loc={ef['loc'][:60]!r} routes={sorted(ef['routes'])}")
        h=match(pads,evs,cat)
        print(f"  {cat}: {len(evs)} events -> {sum(len(v) for v in h.values())} pad-matches on {len(h)} pads")
        for k,v in h.items(): allhits.setdefault(k,[]).extend(v)
    # dedupe per pad
    for k in allhits: allhits[k]=list(dict.fromkeys(allhits[k]))
    out={"updated":datetime.datetime.now(datetime.timezone.utc).isoformat(),"source":"OHGO (ODOT)","alerts":allhits}
    json.dump(out,open(OUT_PATH,'w'))
    print(f"wrote {OUT_PATH}: {len(allhits)} pads flagged")

if __name__=="__main__":
    main()
